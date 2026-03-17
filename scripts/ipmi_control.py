#!/usr/bin/env python3
"""IPMI 전원 제어 래퍼.

ipmitool 서브프로세스를 호출하여 BMC/IPMI를 통한
PXE 부팅 설정, 전원 제어 등을 수행한다.
"""

import argparse
import logging
import os
import re
import subprocess
import sys

logger = logging.getLogger(__name__)

IPMI_TIMEOUT = 30


class IPMIController:
    """ipmitool 래퍼 클래스."""

    def __init__(self, bmc_ip: str, username: str, password: str) -> None:
        """IPMI 컨트롤러를 초기화한다.

        Args:
            bmc_ip: BMC/IPMI IP 주소
            username: IPMI 사용자명
            password: IPMI 비밀번호
        """
        self.bmc_ip = bmc_ip
        self.username = username
        self.password = password

    def _run_ipmi(self, *args: str) -> subprocess.CompletedProcess:
        """ipmitool 명령을 실행한다.

        Args:
            *args: ipmitool에 전달할 인자들

        Returns:
            subprocess.CompletedProcess 결과
        """
        cmd = [
            "ipmitool",
            "-I",
            "lanplus",
            "-H",
            self.bmc_ip,
            "-U",
            self.username,
            "-P",
            self.password,
            *args,
        ]
        # 로그에 비밀번호 노출 방지
        safe_cmd = cmd.copy()
        pw_idx = safe_cmd.index("-P") + 1
        safe_cmd[pw_idx] = "****"
        logger.info("IPMI 명령 실행: %s", " ".join(safe_cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=IPMI_TIMEOUT,
                check=False,
            )
            if result.returncode != 0:
                logger.error("IPMI 명령 실패: %s", result.stderr.strip())
                raise RuntimeError(f"ipmitool 실행 실패: {result.stderr.strip()}")
            return result
        except subprocess.TimeoutExpired:
            logger.error(
                "IPMI 명령 타임아웃 (%d초): %s", IPMI_TIMEOUT, " ".join(safe_cmd)
            )
            raise RuntimeError(f"ipmitool 타임아웃 ({IPMI_TIMEOUT}초)")

    def set_boot_pxe(self, efi: bool = True) -> None:
        """다음 부팅을 PXE로 설정한다.

        Args:
            efi: True이면 EFI 부팅 옵션 사용
        """
        args = ["chassis", "bootdev", "pxe"]
        if efi:
            args.append("options=efiboot")

        self._run_ipmi(*args)
        logger.info("PXE 부팅 설정 완료: %s (EFI: %s)", self.bmc_ip, efi)

    def power_cycle(self) -> None:
        """서버 전원을 재시작한다. 꺼져있으면 켠다."""
        status = self.power_status()
        if status == "off":
            logger.info("서버가 꺼져있어 전원을 켭니다: %s", self.bmc_ip)
            self._run_ipmi("power", "on")
        else:
            self._run_ipmi("power", "cycle")
        logger.info("전원 재시작 완료: %s", self.bmc_ip)

    def power_status(self) -> str:
        """서버 전원 상태를 확인한다.

        Returns:
            "on" 또는 "off"
        """
        result = self._run_ipmi("power", "status")
        output = result.stdout.strip().lower()
        if "on" in output:
            return "on"
        return "off"

    def get_bmc_info(self) -> dict:
        """BMC 정보를 조회한다.

        Returns:
            BMC 정보 딕셔너리
        """
        result = self._run_ipmi("mc", "info")
        info: dict[str, str] = {}
        for line in result.stdout.strip().split("\n"):
            match = re.match(r"^(.+?)\s*:\s*(.+)$", line)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()
                info[key] = value
        return info


def _get_credentials() -> tuple[str, str]:
    """환경변수에서 IPMI 인증 정보를 읽는다."""
    username = os.environ.get("IPMI_USER")
    password = os.environ.get("IPMI_PASS")
    if not username or not password:
        logger.error("환경변수 IPMI_USER, IPMI_PASS를 설정하세요.")
        sys.exit(1)
    return username, password


def cmd_status(args: argparse.Namespace) -> None:
    """전원 상태를 출력한다."""
    username, password = _get_credentials()
    ctrl = IPMIController(args.bmc_ip, username, password)
    status = ctrl.power_status()
    print(f"전원 상태: {status}")


def cmd_pxe_boot(args: argparse.Namespace) -> None:
    """PXE 부팅을 설정한다."""
    username, password = _get_credentials()
    ctrl = IPMIController(args.bmc_ip, username, password)
    ctrl.set_boot_pxe(efi=args.efi)
    print(f"PXE 부팅 설정 완료 (EFI: {args.efi})")


def cmd_power_cycle(args: argparse.Namespace) -> None:
    """전원을 재시작한다."""
    username, password = _get_credentials()
    ctrl = IPMIController(args.bmc_ip, username, password)
    ctrl.power_cycle()
    print("전원 재시작 완료")


def main() -> None:
    """CLI 엔트리포인트."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="IPMI 전원 제어")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_status = subparsers.add_parser("status", help="전원 상태 확인")
    p_status.add_argument("bmc_ip", help="BMC IP 주소")

    p_pxe = subparsers.add_parser("pxe-boot", help="PXE 부팅 설정")
    p_pxe.add_argument("bmc_ip", help="BMC IP 주소")
    p_pxe.add_argument("--efi", action="store_true", default=True, help="EFI 부팅 사용")

    p_cycle = subparsers.add_parser("power-cycle", help="전원 재시작")
    p_cycle.add_argument("bmc_ip", help="BMC IP 주소")

    args = parser.parse_args()

    commands = {
        "status": cmd_status,
        "pxe-boot": cmd_pxe_boot,
        "power-cycle": cmd_power_cycle,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
