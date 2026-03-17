#!/usr/bin/env python3
"""Git의 YAML 정의를 Cobbler에 반영한다 (create/update only).

핵심 원칙:
- DELETE는 절대 자동으로 하지 않음 (orphan은 경고만)
- 기본값은 --dry-run (안전 장치)
- --apply 플래그가 있을 때만 실제 반영
"""

import argparse
import logging
import os
import sys

from scripts.cobbler_client import CobblerClient
from scripts.cobbler_diff import compute_diff, load_git_systems

logger = logging.getLogger(__name__)


def apply_creates(
    client: CobblerClient,
    creates: list[dict],
    git_systems: dict[str, dict],
    dry_run: bool = True,
) -> int:
    """신규 시스템을 Cobbler에 등록한다.

    Returns:
        적용된 시스템 수
    """
    count = 0
    for item in creates:
        name = item["name"]
        config = git_systems.get(name)
        if not config:
            logger.warning("Git에서 시스템 설정을 찾을 수 없음: %s", name)
            continue

        if dry_run:
            logger.info(
                "[DRY-RUN] 신규 등록: %s (profile: %s)", name, config.get("profile")
            )
        else:
            logger.info("신규 등록 중: %s", name)
            client.add_system(config)
            count += 1
            logger.info("신규 등록 완료: %s", name)

    return count


def apply_updates(
    client: CobblerClient,
    updates: list[dict],
    git_systems: dict[str, dict],
    dry_run: bool = True,
) -> int:
    """변경된 시스템 설정을 Cobbler에 반영한다.

    주의: 프로파일이 변경되더라도 netboot_enabled는 건드리지 않는다.

    Returns:
        적용된 시스템 수
    """
    count = 0
    for item in updates:
        name = item["name"]
        changes = item["changes"]
        config = git_systems.get(name)
        if not config:
            logger.warning("Git에서 시스템 설정을 찾을 수 없음: %s", name)
            continue

        if dry_run:
            for change in changes:
                logger.info(
                    "[DRY-RUN] 수정: %s.%s (%s → %s)",
                    name,
                    change["field"],
                    change["from"],
                    change["to"],
                )
        else:
            logger.info("수정 중: %s (%d개 필드)", name, len(changes))

            for change in changes:
                field = change["field"]

                if field.startswith("interfaces."):
                    # 인터페이스 필드 처리
                    parts = field.split(".")
                    iface_name = parts[1]
                    iface_field = parts[2]

                    field_map = {
                        "mac_address": "macaddress",
                        "ip_address": "ipaddress",
                        "netmask": "netmask",
                        "static": "static",
                    }
                    cobbler_field = field_map.get(iface_field, iface_field)
                    client.modify_system_interface(
                        name,
                        {f"{cobbler_field}-{iface_name}": change["to"]},
                    )
                else:
                    client.modify_system_field(name, field, change["to"])

            count += 1
            logger.info("수정 완료: %s", name)

    return count


def main() -> None:
    """CLI 엔트리포인트."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Cobbler Sync - Git → Cobbler 동기화")
    parser.add_argument(
        "--systems-dir",
        default="inventory/systems",
        help="시스템 YAML 디렉토리",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="실제 반영하지 않고 변경사항만 출력 (기본값)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="실제 Cobbler에 반영",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="특정 시스템만 동기화",
    )

    args = parser.parse_args()
    dry_run = not args.apply

    url = os.environ.get("COBBLER_URL")
    user = os.environ.get("COBBLER_USER")
    password = os.environ.get("COBBLER_PASS")
    if not all([url, user, password]):
        logger.error("환경변수 COBBLER_URL, COBBLER_USER, COBBLER_PASS를 설정하세요.")
        sys.exit(1)

    client = CobblerClient(url, user, password)
    diff = compute_diff(args.systems_dir, client, target=args.target)
    git_systems = load_git_systems(args.systems_dir)

    mode = "DRY-RUN" if dry_run else "APPLY"
    logger.info("=== Cobbler Sync [%s] ===", mode)

    created = apply_creates(client, diff["creates"], git_systems, dry_run=dry_run)
    updated = apply_updates(client, diff["updates"], git_systems, dry_run=dry_run)

    # Orphan 경고
    for item in diff["orphans"]:
        logger.warning(
            "⚠ 미관리 시스템: %s (Cobbler에 존재하지만 Git에 정의 없음)", item["name"]
        )

    if not dry_run and (created > 0 or updated > 0):
        logger.info("Cobbler sync 실행 중...")
        client.sync()
        logger.info("Cobbler sync 완료")

    logger.info(
        "=== 결과: 신규 %d | 수정 %d | 미관리 %d ===",
        created if not dry_run else len(diff["creates"]),
        updated if not dry_run else len(diff["updates"]),
        len(diff["orphans"]),
    )


if __name__ == "__main__":
    main()
