#!/usr/bin/env python3
"""서버 인벤토리 YAML 파일을 스키마 기준으로 검증한다.

inventory/systems/*.yaml 파일들을 schema.yaml과 대조하고,
MAC/IP 중복, 프로파일 유효성, 파일명-name 일치 등을 검사한다.
"""

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator, ValidationError

logger = logging.getLogger(__name__)


def load_yaml(path: str) -> Any:
    """YAML 파일을 로드한다."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_catalog_profiles(catalog_path: str) -> list[str]:
    """프로파일 카탈로그에서 프로파일 이름 목록을 반환한다."""
    catalog = load_yaml(catalog_path)
    return [p["name"] for p in catalog.get("profiles", [])]


def get_system_files(systems_dir: str) -> list[Path]:
    """시스템 디렉토리에서 검증 대상 YAML 파일 목록을 반환한다.

    언더스코어(_)로 시작하는 파일은 제외한다.
    """
    path = Path(systems_dir)
    files = sorted(path.glob("*.yaml"))
    return [f for f in files if not f.name.startswith("_")]


def validate_systems(
    systems_dir: str = "inventory/systems",
    schema_path: str = "inventory/schema.yaml",
    catalog_path: str = "profiles/_catalog.yaml",
) -> bool:
    """모든 시스템 YAML을 검증한다.

    Returns:
        True: 모든 검증 통과, False: 하나 이상 실패
    """
    schema = load_yaml(schema_path)
    validator = Draft7Validator(schema)
    valid_profiles = load_catalog_profiles(catalog_path)
    system_files = get_system_files(systems_dir)

    if not system_files:
        logger.warning("검증 대상 시스템 파일이 없습니다: %s", systems_dir)
        return True

    all_valid = True
    seen_macs: dict[str, str] = {}
    seen_ips: dict[str, str] = {}
    seen_bmc_ips: dict[str, str] = {}

    for filepath in system_files:
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
                path_str = ".".join(str(p) for p in err.absolute_path) if err.absolute_path else "(root)"
                logger.error("❌ %s - 스키마 오류 [%s]: %s", filepath.name, path_str, err.message)
            all_valid = False
            continue

        # name과 파일명 일치 확인
        if data.get("name") != filename:
            logger.error(
                "❌ %s - name 필드(%s)가 파일명(%s)과 일치하지 않음",
                filepath.name, data.get("name"), filename,
            )
            all_valid = False

        # 프로파일 유효성 확인
        profile = data.get("profile", "")
        if profile not in valid_profiles:
            logger.error(
                "❌ %s - 프로파일 '%s'이(가) 카탈로그에 없음 (사용 가능: %s)",
                filepath.name, profile, ", ".join(valid_profiles),
            )
            all_valid = False

        # MAC 주소 중복 검사
        for iface in data.get("interfaces", []):
            mac = iface.get("mac_address", "").lower()
            if mac in seen_macs:
                logger.error(
                    "❌ %s - MAC 주소 %s가 %s와 중복",
                    filepath.name, mac, seen_macs[mac],
                )
                all_valid = False
            else:
                seen_macs[mac] = filepath.name

            # IP 주소 중복 검사
            ip = iface.get("ip_address", "")
            if ip in seen_ips:
                logger.error(
                    "❌ %s - IP 주소 %s가 %s와 중복",
                    filepath.name, ip, seen_ips[ip],
                )
                all_valid = False
            else:
                seen_ips[ip] = filepath.name

        # BMC IP 중복 검사
        bmc_ip = data.get("bmc_ip", "")
        if bmc_ip in seen_bmc_ips:
            logger.error(
                "❌ %s - BMC IP %s가 %s와 중복",
                filepath.name, bmc_ip, seen_bmc_ips[bmc_ip],
            )
            all_valid = False
        else:
            seen_bmc_ips[bmc_ip] = filepath.name

        if all_valid or data.get("name") == filename:
            logger.info("✅ %s - valid", filepath.name)

    return all_valid


def main() -> None:
    """CLI 엔트리포인트."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="서버 인벤토리 YAML 검증")
    parser.add_argument(
        "--systems-dir", default="inventory/systems", help="시스템 YAML 디렉토리",
    )
    parser.add_argument(
        "--schema", default="inventory/schema.yaml", help="스키마 파일 경로",
    )
    parser.add_argument(
        "--catalog", default="profiles/_catalog.yaml", help="프로파일 카탈로그 경로",
    )

    args = parser.parse_args()
    valid = validate_systems(args.systems_dir, args.schema, args.catalog)

    if not valid:
        logger.error("검증 실패: 위 오류를 확인하세요.")
        sys.exit(1)

    logger.info("모든 시스템 검증 통과")


if __name__ == "__main__":
    main()
