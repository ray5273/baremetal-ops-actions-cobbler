#!/usr/bin/env python3
"""Cobbler XML-RPC API 래퍼 클라이언트.

Cobbler 3.3.7 서버와 XML-RPC를 통해 통신하여
시스템 조회, 프로파일 변경, netboot 제어, sync 등을 수행한다.
"""

import argparse
import logging
import os
import ssl
import sys
import xmlrpc.client
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


class CobblerClient:
    """Cobbler XML-RPC API 래퍼 클래스."""

    def __init__(self, url: str, username: str, password: str) -> None:
        """Cobbler 서버에 연결하고 인증 토큰을 획득한다.

        Args:
            url: Cobbler API URL (예: https://cobbler.internal/cobbler_api)
            username: Cobbler 사용자명
            password: Cobbler 비밀번호
        """
        context = None
        if os.environ.get("COBBLER_INSECURE", "").lower() == "true":
            context = ssl._create_unverified_context()

        try:
            self.server = xmlrpc.client.ServerProxy(url, context=context)
            self.token = self.server.login(username, password)
            logger.info("Cobbler 서버 연결 성공: %s", url)
        except xmlrpc.client.Fault as e:
            logger.error("Cobbler 인증 실패: %s", e.faultString)
            raise SystemExit(1)
        except Exception as e:
            logger.error("Cobbler 서버 연결 실패: %s", e)
            raise SystemExit(1)

    def get_system(self, name: str) -> Optional[dict]:
        """시스템 정보를 조회한다.

        Args:
            name: Cobbler 시스템 이름

        Returns:
            시스템 정보 딕셔너리, 없으면 None
        """
        try:
            result: dict = self.server.get_system(name)  # type: ignore[assignment]
            if result and result != "~":
                logger.info("시스템 조회 성공: %s", name)
                return result
            return None
        except xmlrpc.client.Fault:
            logger.warning("시스템을 찾을 수 없음: %s", name)
            return None

    def list_systems(self) -> list:
        """모든 시스템 목록을 조회한다."""
        systems: list = self.server.get_systems()  # type: ignore[assignment]
        logger.info("시스템 목록 조회: %d개", len(systems))
        return systems

    def list_profiles(self) -> list:
        """모든 프로파일 목록을 조회한다."""
        profiles: list = self.server.get_profiles()  # type: ignore[assignment]
        logger.info("프로파일 목록 조회: %d개", len(profiles))
        return profiles

    def _get_profile_names(self) -> list[str]:
        """프로파일 이름 목록을 반환한다."""
        return [p["name"] for p in self.list_profiles()]

    def set_system_profile(self, system_name: str, profile: str) -> None:
        """시스템의 프로파일을 변경한다.

        Args:
            system_name: 시스템 이름
            profile: 새 프로파일 이름
        """
        profile_names = self._get_profile_names()
        if profile not in profile_names:
            logger.error(
                "프로파일이 존재하지 않음: %s (사용 가능: %s)",
                profile,
                ", ".join(profile_names),
            )
            raise SystemExit(1)

        handle = self.server.get_system_handle(system_name, self.token)
        self.server.modify_system(handle, "profile", profile, self.token)
        self.server.save_system(handle, self.token)
        logger.info("프로파일 변경 완료: %s → %s", system_name, profile)

    def enable_netboot(self, system_name: str) -> None:
        """시스템의 netboot를 활성화한다."""
        handle = self.server.get_system_handle(system_name, self.token)
        self.server.modify_system(handle, "netboot_enabled", True, self.token)
        self.server.save_system(handle, self.token)
        logger.info("Netboot 활성화: %s", system_name)

    def disable_netboot(self, system_name: str) -> None:
        """시스템의 netboot를 비활성화한다."""
        handle = self.server.get_system_handle(system_name, self.token)
        self.server.modify_system(handle, "netboot_enabled", False, self.token)
        self.server.save_system(handle, self.token)
        logger.info("Netboot 비활성화: %s", system_name)

    def sync(self) -> None:
        """Cobbler sync를 실행하여 DHCP/TFTP/PXE 설정을 재생성한다."""
        self.server.sync(self.token)
        logger.info("Cobbler sync 완료")

    def add_system(self, config: dict) -> None:
        """새 시스템을 추가한다.

        Args:
            config: 시스템 설정 딕셔너리
                필수 키: name, profile, hostname, interfaces
                각 interface: name, mac_address, ip_address, netmask, static(bool)
        """
        required_keys = ["name", "profile", "hostname", "interfaces"]
        for key in required_keys:
            if key not in config:
                logger.error("필수 키 누락: %s", key)
                raise SystemExit(1)

        handle = self.server.new_system(self.token)
        self.server.modify_system(handle, "name", config["name"], self.token)
        self.server.modify_system(handle, "profile", config["profile"], self.token)
        self.server.modify_system(handle, "hostname", config["hostname"], self.token)

        if "gateway" in config:
            self.server.modify_system(handle, "gateway", config["gateway"], self.token)

        if "name_servers" in config:
            self.server.modify_system(
                handle, "name_servers", config["name_servers"], self.token
            )

        if "boot_loader" in config:
            self.server.modify_system(
                handle, "boot_loader", config["boot_loader"], self.token
            )

        if "comment" in config:
            self.server.modify_system(handle, "comment", config["comment"], self.token)

        for iface in config["interfaces"]:
            iface_name = iface["name"]
            self.server.modify_system(
                handle,
                "modify_interface",
                {
                    f"macaddress-{iface_name}": iface["mac_address"],
                    f"ipaddress-{iface_name}": iface["ip_address"],
                    f"netmask-{iface_name}": iface["netmask"],
                    f"static-{iface_name}": iface.get("static", True),
                    f"interfacetype-{iface_name}": iface.get("interface_type", "na"),
                },
                self.token,
            )

        self.server.save_system(handle, self.token)
        logger.info("시스템 추가 완료: %s", config["name"])

    def modify_system_field(self, system_name: str, field: str, value: Any) -> None:
        """시스템의 특정 필드를 수정한다."""
        handle = self.server.get_system_handle(system_name, self.token)
        self.server.modify_system(handle, field, value, self.token)
        self.server.save_system(handle, self.token)
        logger.info("시스템 필드 수정: %s.%s", system_name, field)

    def modify_system_interface(self, system_name: str, iface_data: dict) -> None:
        """시스템의 인터페이스를 수정한다."""
        handle = self.server.get_system_handle(system_name, self.token)
        self.server.modify_system(handle, "modify_interface", iface_data, self.token)
        self.server.save_system(handle, self.token)
        logger.info("시스템 인터페이스 수정: %s", system_name)

    def remove_system(self, name: str) -> None:
        """시스템을 삭제한다."""
        self.server.remove_system(name, self.token)
        logger.info("시스템 삭제 완료: %s", name)

    def get_system_status(self, name: str) -> dict:
        """시스템의 렌더링된 상태를 조회한다."""
        try:
            result: dict = self.server.get_system_as_rendered(name, self.token)  # type: ignore[assignment]
            return result
        except xmlrpc.client.Fault:
            logger.warning("시스템 상태 조회 실패: %s", name)
            return {}


def _create_client_from_env() -> CobblerClient:
    """환경변수에서 Cobbler 연결 정보를 읽어 클라이언트를 생성한다."""
    url = os.environ.get("COBBLER_URL")
    user = os.environ.get("COBBLER_USER")
    password = os.environ.get("COBBLER_PASS")

    if not all([url, user, password]):
        logger.error("환경변수 COBBLER_URL, COBBLER_USER, COBBLER_PASS를 설정하세요.")
        sys.exit(1)

    return CobblerClient(url, user, password)


def cmd_list_systems(_args: argparse.Namespace) -> None:
    """시스템 목록을 출력한다."""
    client = _create_client_from_env()
    systems = client.list_systems()
    for s in systems:
        print(f"  {s['name']} (profile: {s.get('profile', 'N/A')})")


def cmd_list_profiles(_args: argparse.Namespace) -> None:
    """프로파일 목록을 출력한다."""
    client = _create_client_from_env()
    profiles = client.list_profiles()
    for p in profiles:
        print(f"  {p['name']}")


def cmd_get_system(args: argparse.Namespace) -> None:
    """시스템 정보를 출력한다."""
    client = _create_client_from_env()
    system = client.get_system(args.name)
    if system is None:
        logger.error("시스템을 찾을 수 없습니다: %s", args.name)
        sys.exit(1)
    print(f"Name: {system['name']}")
    print(f"Profile: {system.get('profile', 'N/A')}")
    print(f"Hostname: {system.get('hostname', 'N/A')}")
    print(f"Netboot Enabled: {system.get('netboot_enabled', 'N/A')}")


def cmd_reprovision(args: argparse.Namespace) -> None:
    """시스템 재배포를 준비한다 (프로파일 변경 + netboot 활성화 + sync)."""
    client = _create_client_from_env()

    system = client.get_system(args.name)
    if system is None:
        logger.error("시스템을 찾을 수 없습니다: %s", args.name)
        sys.exit(1)

    old_profile = system.get("profile", "N/A")
    logger.info("재배포 시작: %s (%s → %s)", args.name, old_profile, args.profile)

    client.set_system_profile(args.name, args.profile)
    client.enable_netboot(args.name)
    client.sync()

    logger.info("재배포 준비 완료: %s (PXE 부팅 대기 중)", args.name)


def cmd_add_system(args: argparse.Namespace) -> None:
    """YAML 파일에서 시스템 설정을 읽어 추가한다."""
    with open(args.config, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    client = _create_client_from_env()
    client.add_system(config)
    client.sync()


def cmd_remove_system(args: argparse.Namespace) -> None:
    """시스템을 삭제한다."""
    client = _create_client_from_env()
    client.remove_system(args.name)
    client.sync()


def main() -> None:
    """CLI 엔트리포인트."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Cobbler XML-RPC 클라이언트")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-systems", help="시스템 목록 조회")
    subparsers.add_parser("list-profiles", help="프로파일 목록 조회")

    p_get = subparsers.add_parser("get-system", help="시스템 정보 조회")
    p_get.add_argument("name", help="시스템 이름")

    p_reprov = subparsers.add_parser("reprovision", help="시스템 재배포 준비")
    p_reprov.add_argument("name", help="시스템 이름")
    p_reprov.add_argument("profile", help="새 OS 프로파일")

    p_add = subparsers.add_parser("add-system", help="시스템 추가")
    p_add.add_argument("--config", required=True, help="YAML 설정 파일 경로")

    p_rm = subparsers.add_parser("remove-system", help="시스템 삭제")
    p_rm.add_argument("name", help="시스템 이름")

    args = parser.parse_args()

    commands = {
        "list-systems": cmd_list_systems,
        "list-profiles": cmd_list_profiles,
        "get-system": cmd_get_system,
        "reprovision": cmd_reprovision,
        "add-system": cmd_add_system,
        "remove-system": cmd_remove_system,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
