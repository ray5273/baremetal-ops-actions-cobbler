#!/usr/bin/env python3
"""Git의 YAML 상태와 Cobbler 현재 상태를 비교하여 차이점을 출력한다.

inventory/systems/*.yaml (desired state)과 Cobbler API (actual state)를
비교하여 CREATE/UPDATE/ORPHAN을 분류한다.
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import yaml

from scripts.cobbler_client import CobblerClient

logger = logging.getLogger(__name__)


def load_git_systems(systems_dir: str) -> dict[str, dict]:
    """Git의 시스템 YAML 파일들을 로드한다.

    언더스코어(_)로 시작하는 파일은 제외한다.

    Returns:
        {system_name: config_dict} 딕셔너리
    """
    systems = {}
    path = Path(systems_dir)
    for filepath in sorted(path.glob("*.yaml")):
        if filepath.name.startswith("_"):
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data and "name" in data:
            systems[data["name"]] = data
    return systems


def normalize_cobbler_system(cobbler_sys: dict) -> dict:
    """Cobbler 시스템 데이터를 비교 가능한 형태로 정규화한다."""
    interfaces = []
    iface_data = cobbler_sys.get("interfaces", {})
    for iface_name, iface_info in iface_data.items():
        interfaces.append(
            {
                "name": iface_name,
                "mac_address": iface_info.get("mac_address", ""),
                "ip_address": iface_info.get("ip_address", ""),
                "netmask": iface_info.get("netmask", ""),
                "static": iface_info.get("static", True),
            }
        )

    return {
        "name": cobbler_sys.get("name", ""),
        "profile": cobbler_sys.get("profile", ""),
        "hostname": cobbler_sys.get("hostname", ""),
        "gateway": cobbler_sys.get("gateway", ""),
        "name_servers": cobbler_sys.get("name_servers", []),
        "boot_loader": cobbler_sys.get("boot_loader", "grub"),
        "interfaces": sorted(interfaces, key=lambda x: x["name"]),
    }


def normalize_git_system(git_sys: dict) -> dict:
    """Git 시스템 데이터를 비교 가능한 형태로 정규화한다."""
    interfaces = []
    for iface in git_sys.get("interfaces", []):
        interfaces.append(
            {
                "name": iface.get("name", ""),
                "mac_address": iface.get("mac_address", ""),
                "ip_address": iface.get("ip_address", ""),
                "netmask": iface.get("netmask", ""),
                "static": iface.get("static", True),
            }
        )

    return {
        "name": git_sys.get("name", ""),
        "profile": git_sys.get("profile", ""),
        "hostname": git_sys.get("hostname", ""),
        "gateway": git_sys.get("gateway", ""),
        "name_servers": git_sys.get("name_servers", []),
        "boot_loader": git_sys.get("boot_loader", "grub"),
        "interfaces": sorted(interfaces, key=lambda x: x["name"]),
    }


def compute_field_changes(git_norm: dict, cobbler_norm: dict) -> list[dict]:
    """두 정규화된 시스템 간의 필드별 차이를 계산한다."""
    changes = []
    compare_fields = ["profile", "hostname", "gateway", "name_servers", "boot_loader"]

    for field in compare_fields:
        git_val = git_norm.get(field)
        cobbler_val = cobbler_norm.get(field)
        if git_val != cobbler_val:
            changes.append(
                {
                    "field": field,
                    "from": cobbler_val,
                    "to": git_val,
                }
            )

    # 인터페이스 비교
    git_ifaces = {i["name"]: i for i in git_norm.get("interfaces", [])}
    cobbler_ifaces = {i["name"]: i for i in cobbler_norm.get("interfaces", [])}

    all_iface_names = set(git_ifaces.keys()) | set(cobbler_ifaces.keys())
    for iface_name in sorted(all_iface_names):
        git_iface = git_ifaces.get(iface_name, {})
        cobbler_iface = cobbler_ifaces.get(iface_name, {})
        for key in ["mac_address", "ip_address", "netmask", "static"]:
            if git_iface.get(key) != cobbler_iface.get(key):
                changes.append(
                    {
                        "field": f"interfaces.{iface_name}.{key}",
                        "from": cobbler_iface.get(key),
                        "to": git_iface.get(key),
                    }
                )

    return changes


def compute_diff(
    systems_dir: str,
    client: CobblerClient,
    target: str | None = None,
) -> dict:
    """Git과 Cobbler의 차이를 계산한다.

    Returns:
        {"creates": [...], "updates": [...], "orphans": [...]}
    """
    git_systems = load_git_systems(systems_dir)
    cobbler_systems_list = client.list_systems()
    cobbler_systems = {s["name"]: s for s in cobbler_systems_list}

    if target:
        git_systems = {k: v for k, v in git_systems.items() if k == target}

    creates = []
    updates = []
    orphans = []

    # Git에 있는 시스템 확인
    for name, git_config in git_systems.items():
        if name not in cobbler_systems:
            creates.append(
                {
                    "name": name,
                    "profile": git_config.get("profile", ""),
                    "action": "create",
                }
            )
        else:
            git_norm = normalize_git_system(git_config)
            cobbler_norm = normalize_cobbler_system(cobbler_systems[name])
            changes = compute_field_changes(git_norm, cobbler_norm)
            if changes:
                updates.append(
                    {
                        "name": name,
                        "changes": changes,
                        "action": "update",
                    }
                )

    # Cobbler에만 있는 시스템 (orphan)
    if not target:
        for name in cobbler_systems:
            if name not in git_systems:
                orphans.append(
                    {
                        "name": name,
                        "action": "orphan",
                    }
                )

    return {"creates": creates, "updates": updates, "orphans": orphans}


def format_human(diff: dict) -> str:
    """사람이 읽기 편한 형식으로 출력한다."""
    lines = []
    lines.append("🔄 Cobbler Sync Plan")
    lines.append("─" * 40)

    if not diff["creates"] and not diff["updates"] and not diff["orphans"]:
        lines.append("✅ Git과 Cobbler가 동기화 상태입니다.")
        return "\n".join(lines)

    for item in diff["creates"]:
        lines.append(f"+ {item['name']}: 신규 등록 (profile: {item['profile']})")

    for item in diff["updates"]:
        for change in item["changes"]:
            lines.append(
                f"~ {item['name']}: {change['field']} 변경 ({change['from']} → {change['to']})"
            )

    for item in diff["orphans"]:
        lines.append(f"⚠ {item['name']}: Cobbler에 존재하지만 Git에 정의 없음")

    lines.append("")
    lines.append(
        f"요약: 신규 {len(diff['creates'])} | 변경 {len(diff['updates'])} | 미관리 {len(diff['orphans'])}"
    )

    return "\n".join(lines)


def format_github(diff: dict) -> str:
    """GitHub PR 코멘트용 마크다운 형식으로 출력한다."""
    lines = []

    if not diff["creates"] and not diff["updates"] and not diff["orphans"]:
        lines.append("✅ Git과 Cobbler가 동기화 상태입니다.")
        return "\n".join(lines)

    for item in diff["creates"]:
        lines.append(
            f"- **+** `{item['name']}`: 신규 등록 (profile: `{item['profile']}`)"
        )

    for item in diff["updates"]:
        for change in item["changes"]:
            lines.append(
                f"- **~** `{item['name']}`: `{change['field']}` 변경 (`{change['from']}` → `{change['to']}`)"
            )

    for item in diff["orphans"]:
        lines.append(f"- **⚠** `{item['name']}`: Cobbler에 존재하지만 Git에 정의 없음")

    lines.append("")
    lines.append(
        f"**요약**: 신규 {len(diff['creates'])} | 변경 {len(diff['updates'])} | 미관리 {len(diff['orphans'])}"
    )

    return "\n".join(lines)


def format_json(diff: dict) -> str:
    """JSON 형식으로 출력한다."""
    return json.dumps(diff, ensure_ascii=False, indent=2)


def main() -> None:
    """CLI 엔트리포인트."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Cobbler Diff - Git vs Cobbler 상태 비교"
    )
    parser.add_argument(
        "--systems-dir",
        default="inventory/systems",
        help="시스템 YAML 디렉토리",
    )
    parser.add_argument(
        "--output-format",
        choices=["human", "github", "json"],
        default="human",
        help="출력 형식 (기본: human)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="특정 시스템만 비교",
    )

    args = parser.parse_args()

    url = os.environ.get("COBBLER_URL")
    user = os.environ.get("COBBLER_USER")
    password = os.environ.get("COBBLER_PASS")
    if not all([url, user, password]):
        logger.error("환경변수 COBBLER_URL, COBBLER_USER, COBBLER_PASS를 설정하세요.")
        sys.exit(1)

    client = CobblerClient(url, user, password)
    diff = compute_diff(args.systems_dir, client, target=args.target)

    formatters = {
        "human": format_human,
        "github": format_github,
        "json": format_json,
    }

    print(formatters[args.output_format](diff))


if __name__ == "__main__":
    main()
