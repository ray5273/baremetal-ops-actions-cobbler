#!/usr/bin/env python3
"""클러스터 단위 배치 배포 관리자.

clusters/*.yaml에 정의된 클러스터를 읽어서
소속 노드 전체를 한번에 또는 롤링 방식으로 재배포한다.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# YAML / Schema helpers
# ---------------------------------------------------------------------------


def load_yaml(path: str) -> Any:
    """YAML 파일을 로드한다."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_cluster_files(clusters_dir: str) -> list[Path]:
    """클러스터 디렉토리에서 검증 대상 YAML 파일 목록을 반환한다.

    언더스코어(_)로 시작하는 파일과 schema.yaml은 제외한다.
    """
    path = Path(clusters_dir)
    files = sorted(path.glob("*.yaml"))
    return [f for f in files if not f.name.startswith("_") and f.name != "schema.yaml"]


def load_cluster(cluster_path: str) -> dict:
    """단일 클러스터 YAML을 로드한다."""
    return load_yaml(cluster_path)


def load_all_clusters(clusters_dir: str) -> dict[str, dict]:
    """모든 클러스터를 {name: config} 딕셔너리로 로드한다."""
    clusters: dict[str, dict] = {}
    for filepath in get_cluster_files(clusters_dir):
        data = load_yaml(str(filepath))
        if data and "name" in data:
            clusters[data["name"]] = data
    return clusters


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_clusters(
    clusters_dir: str = "clusters",
    schema_path: str = "clusters/schema.yaml",
    systems_dir: str = "inventory/systems",
    catalog_path: str = "profiles/_catalog.yaml",
) -> bool:
    """모든 클러스터 YAML을 검증한다.

    검증 항목:
    - JSON Schema 검증
    - 파일명-name 일치
    - default_profile이 카탈로그에 존재
    - profile_override가 카탈로그에 존재
    - 노드가 inventory/systems/에 존재
    - 동일 클러스터 내 노드 중복 없음

    Returns:
        True: 모든 검증 통과, False: 하나 이상 실패
    """
    schema = load_yaml(schema_path)
    validator = Draft7Validator(schema)

    # 프로파일 카탈로그 로드
    catalog = load_yaml(catalog_path)
    valid_profiles = [p["name"] for p in catalog.get("profiles", [])]

    # inventory 시스템 이름 목록
    systems_path = Path(systems_dir)
    existing_systems = {
        f.stem for f in systems_path.glob("*.yaml") if not f.name.startswith("_")
    }

    cluster_files = get_cluster_files(clusters_dir)
    if not cluster_files:
        logger.warning("검증 대상 클러스터 파일이 없습니다: %s", clusters_dir)
        return True

    all_valid = True

    for filepath in cluster_files:
        filename = filepath.stem
        try:
            data = load_yaml(str(filepath))
        except yaml.YAMLError as e:
            logger.error("❌ %s - YAML 파싱 오류: %s", filepath.name, e)
            all_valid = False
            continue

        # JSON Schema 검증
        errors = list(validator.iter_errors(data))
        if errors:
            for err in errors:
                path_str = (
                    ".".join(str(p) for p in err.absolute_path)
                    if err.absolute_path
                    else "(root)"
                )
                logger.error(
                    "❌ %s - 스키마 오류 [%s]: %s",
                    filepath.name,
                    path_str,
                    err.message,
                )
            all_valid = False
            continue

        # name과 파일명 일치 확인
        if data.get("name") != filename:
            logger.error(
                "❌ %s - name 필드(%s)가 파일명(%s)과 일치하지 않음",
                filepath.name,
                data.get("name"),
                filename,
            )
            all_valid = False

        # default_profile 유효성 확인
        default_profile = data.get("default_profile", "")
        if default_profile not in valid_profiles:
            logger.error(
                "❌ %s - default_profile '%s'이(가) 카탈로그에 없음 (사용 가능: %s)",
                filepath.name,
                default_profile,
                ", ".join(valid_profiles),
            )
            all_valid = False

        # 노드 검증
        seen_nodes: set[str] = set()
        for i, node in enumerate(data.get("nodes", [])):
            node_name = node.get("name", "")

            # 노드 중복 검사
            if node_name in seen_nodes:
                logger.error(
                    "❌ %s - 노드 '%s'이(가) 중복 정의됨",
                    filepath.name,
                    node_name,
                )
                all_valid = False
            else:
                seen_nodes.add(node_name)

            # inventory에 존재하는지 확인
            if node_name not in existing_systems:
                logger.error(
                    "❌ %s - 노드 '%s'이(가) inventory/systems/에 없음",
                    filepath.name,
                    node_name,
                )
                all_valid = False

            # profile_override 유효성 확인
            override = node.get("profile_override")
            if override and override not in valid_profiles:
                logger.error(
                    "❌ %s - 노드 '%s'의 profile_override '%s'이(가) 카탈로그에 없음",
                    filepath.name,
                    node_name,
                    override,
                )
                all_valid = False

        if all_valid:
            logger.info("✅ %s - valid", filepath.name)

    return all_valid


# ---------------------------------------------------------------------------
# Cluster node resolution
# ---------------------------------------------------------------------------


def resolve_cluster_nodes(
    cluster: dict,
    systems_dir: str = "inventory/systems",
) -> list[dict]:
    """클러스터의 노드 목록을 resolve 하여 배포에 필요한 정보를 반환한다.

    각 노드에 대해:
    - 최종 profile 결정 (profile_override > default_profile)
    - inventory에서 bmc_ip 조회

    Returns:
        [{"name": ..., "profile": ..., "bmc_ip": ..., "use_efi": ...}, ...]
    """
    default_profile = cluster.get("default_profile", "")
    use_efi = cluster.get("use_efi", True)
    resolved: list[dict] = []

    for node in cluster.get("nodes", []):
        node_name = node["name"]
        profile = node.get("profile_override", default_profile)

        # inventory에서 bmc_ip 읽기
        system_path = Path(systems_dir) / f"{node_name}.yaml"
        if not system_path.exists():
            logger.error("노드 시스템 파일이 없습니다: %s", system_path)
            continue

        system_data = load_yaml(str(system_path))
        bmc_ip = system_data.get("bmc_ip", "")

        resolved.append(
            {
                "name": node_name,
                "profile": profile,
                "bmc_ip": bmc_ip,
                "use_efi": use_efi,
            }
        )

    return resolved


def split_batches(nodes: list[dict], batch_size: int) -> list[list[dict]]:
    """노드 목록을 batch_size 단위로 분할한다."""
    if batch_size <= 0:
        batch_size = len(nodes)
    return [nodes[i : i + batch_size] for i in range(0, len(nodes), batch_size)]


def get_deploy_plan(
    cluster: dict,
    systems_dir: str = "inventory/systems",
) -> dict:
    """클러스터 배포 계획을 생성한다.

    Returns:
        {
            "cluster_name": str,
            "rolling_enabled": bool,
            "batch_size": int,
            "total_nodes": int,
            "batches": [[node_dict, ...], ...]
        }
    """
    nodes = resolve_cluster_nodes(cluster, systems_dir)
    rolling = cluster.get("rolling", {})
    rolling_enabled = rolling.get("enabled", False)
    batch_size = rolling.get("batch_size", 1) if rolling_enabled else len(nodes)
    pause = rolling.get("pause_between_batches", False)

    batches = split_batches(nodes, batch_size)

    return {
        "cluster_name": cluster["name"],
        "description": cluster.get("description", ""),
        "rolling_enabled": rolling_enabled,
        "batch_size": batch_size,
        "pause_between_batches": pause,
        "total_nodes": len(nodes),
        "total_batches": len(batches),
        "batches": batches,
    }


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------


def format_plan_human(plan: dict) -> str:
    """배포 계획을 사람이 읽기 편한 형태로 출력한다."""
    lines = []
    lines.append(f"🚀 클러스터 배포 계획: {plan['cluster_name']}")
    lines.append(f"   설명: {plan['description']}")
    lines.append("─" * 50)
    lines.append(f"   전략: {'롤링' if plan['rolling_enabled'] else '전체 동시'}")
    lines.append(f"   총 노드: {plan['total_nodes']}")
    lines.append(f"   총 배치: {plan['total_batches']}")
    if plan["rolling_enabled"]:
        lines.append(f"   배치 크기: {plan['batch_size']}")
        lines.append(
            f"   배치 간 대기: {'수동 승인' if plan['pause_between_batches'] else '자동 진행'}"
        )
    lines.append("─" * 50)

    for i, batch in enumerate(plan["batches"], 1):
        lines.append(f"  배치 {i}/{plan['total_batches']}:")
        for node in batch:
            lines.append(
                f"    - {node['name']} → {node['profile']} "
                f"(BMC: {node['bmc_ip']}, EFI: {node['use_efi']})"
            )

    return "\n".join(lines)


def format_plan_json(plan: dict) -> str:
    """배포 계획을 JSON 형식으로 출력한다."""
    return json.dumps(plan, ensure_ascii=False, indent=2)


def format_plan_github(plan: dict) -> str:
    """배포 계획을 GitHub Actions step summary 마크다운으로 출력한다."""
    lines = []
    lines.append(f"## 🚀 클러스터 배포 계획: `{plan['cluster_name']}`")
    lines.append("")
    lines.append(f"**설명**: {plan['description']}")
    lines.append(f"**전략**: {'롤링' if plan['rolling_enabled'] else '전체 동시'}")
    lines.append(
        f"**총 노드**: {plan['total_nodes']}개 / **총 배치**: {plan['total_batches']}개"
    )
    if plan["rolling_enabled"]:
        lines.append(f"**배치 크기**: {plan['batch_size']}")
    lines.append("")
    lines.append("| 배치 | 서버 | 프로파일 | BMC IP | EFI |")
    lines.append("|------|------|----------|--------|-----|")

    for i, batch in enumerate(plan["batches"], 1):
        for node in batch:
            lines.append(
                f"| {i} | `{node['name']}` | `{node['profile']}` | "
                f"`{node['bmc_ip']}` | {node['use_efi']} |"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_validate(args: argparse.Namespace) -> None:
    """클러스터 YAML 검증."""
    valid = validate_clusters(
        clusters_dir=args.clusters_dir,
        schema_path=args.schema,
        systems_dir=args.systems_dir,
        catalog_path=args.catalog,
    )
    if not valid:
        logger.error("클러스터 검증 실패")
        sys.exit(1)
    logger.info("모든 클러스터 검증 통과")


def cmd_list(args: argparse.Namespace) -> None:
    """클러스터 목록 출력."""
    clusters = load_all_clusters(args.clusters_dir)
    if not clusters:
        print("정의된 클러스터가 없습니다.")
        return

    for name, cluster in clusters.items():
        node_count = len(cluster.get("nodes", []))
        rolling = cluster.get("rolling", {}).get("enabled", False)
        desc = cluster.get("description", "")
        strategy = "롤링" if rolling else "전체 동시"
        print(f"  {name}: {desc} ({node_count}개 노드, {strategy})")


def cmd_show(args: argparse.Namespace) -> None:
    """특정 클러스터 배포 계획 출력."""
    clusters = load_all_clusters(args.clusters_dir)
    if args.name not in clusters:
        logger.error("클러스터를 찾을 수 없습니다: %s", args.name)
        sys.exit(1)

    cluster = clusters[args.name]
    plan = get_deploy_plan(cluster, systems_dir=args.systems_dir)

    formatters = {
        "human": format_plan_human,
        "json": format_plan_json,
        "github": format_plan_github,
    }
    print(formatters[args.output_format](plan))


def cmd_resolve(args: argparse.Namespace) -> None:
    """클러스터 노드를 JSON matrix로 출력 (GitHub Actions용)."""
    clusters = load_all_clusters(args.clusters_dir)
    if args.name not in clusters:
        logger.error("클러스터를 찾을 수 없습니다: %s", args.name)
        sys.exit(1)

    cluster = clusters[args.name]
    plan = get_deploy_plan(cluster, systems_dir=args.systems_dir)

    # GitHub Actions matrix 형식으로 출력
    output = {
        "cluster_name": plan["cluster_name"],
        "rolling_enabled": plan["rolling_enabled"],
        "total_nodes": plan["total_nodes"],
        "total_batches": plan["total_batches"],
        "batches": plan["batches"],
    }
    print(json.dumps(output, ensure_ascii=False))


def main() -> None:
    """CLI 엔트리포인트."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="클러스터 배치 배포 관리자")
    parser.add_argument(
        "--clusters-dir",
        default="clusters",
        help="클러스터 YAML 디렉토리 (기본: clusters)",
    )
    parser.add_argument(
        "--systems-dir",
        default="inventory/systems",
        help="시스템 YAML 디렉토리 (기본: inventory/systems)",
    )
    parser.add_argument(
        "--catalog",
        default="profiles/_catalog.yaml",
        help="프로파일 카탈로그 경로",
    )
    parser.add_argument(
        "--schema",
        default="clusters/schema.yaml",
        help="클러스터 스키마 경로",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # validate
    subparsers.add_parser("validate", help="클러스터 YAML 검증")

    # list
    subparsers.add_parser("list", help="클러스터 목록 출력")

    # show
    p_show = subparsers.add_parser("show", help="클러스터 배포 계획 출력")
    p_show.add_argument("name", help="클러스터 이름")
    p_show.add_argument(
        "--output-format",
        choices=["human", "json", "github"],
        default="human",
        help="출력 형식",
    )

    # resolve (GitHub Actions matrix output)
    p_resolve = subparsers.add_parser(
        "resolve", help="클러스터 노드 resolve (JSON matrix)"
    )
    p_resolve.add_argument("name", help="클러스터 이름")

    args = parser.parse_args()

    commands = {
        "validate": cmd_validate,
        "list": cmd_list,
        "show": cmd_show,
        "resolve": cmd_resolve,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
