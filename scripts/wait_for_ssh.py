#!/usr/bin/env python3
"""OS 설치 완료 후 SSH 접속 가능 여부를 폴링하여 확인한다.

지정된 호스트의 SSH 포트에 주기적으로 연결을 시도하여
OS 설치가 완료되었는지 확인한다.
"""

import argparse
import logging
import socket
import sys
import time

logger = logging.getLogger(__name__)


def wait_for_ssh(
    host: str,
    port: int = 22,
    timeout_minutes: int = 30,
    interval_seconds: int = 60,
) -> bool:
    """SSH 접속이 가능해질 때까지 대기한다.

    Args:
        host: 대상 호스트명 또는 IP
        port: SSH 포트 (기본 22)
        timeout_minutes: 최대 대기 시간 (분)
        interval_seconds: 폴링 간격 (초)

    Returns:
        True: SSH 접속 성공, False: 타임아웃
    """
    max_attempts = (timeout_minutes * 60) // interval_seconds
    start_time = time.time()

    for attempt in range(1, max_attempts + 1):
        try:
            sock = socket.create_connection((host, port), timeout=5)
            sock.close()
            elapsed = int((time.time() - start_time) / 60)
            logger.info("✅ %s SSH 연결 성공 (%d분 경과)", host, elapsed)
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            logger.info(
                "⏳ 시도 %d/%d - %s 아직 준비되지 않음...",
                attempt, max_attempts, host,
            )
            if attempt < max_attempts:
                time.sleep(interval_seconds)

    logger.error("❌ %s에 %d분 내 SSH 연결 실패", host, timeout_minutes)
    return False


def main() -> None:
    """CLI 엔트리포인트."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="SSH 접속 대기")
    parser.add_argument("hostname", help="대상 호스트명 또는 IP")
    parser.add_argument("--timeout", type=int, default=30, help="최대 대기 시간 (분, 기본 30)")
    parser.add_argument("--interval", type=int, default=60, help="폴링 간격 (초, 기본 60)")
    parser.add_argument("--port", type=int, default=22, help="SSH 포트 (기본 22)")

    args = parser.parse_args()

    success = wait_for_ssh(
        host=args.hostname,
        port=args.port,
        timeout_minutes=args.timeout,
        interval_seconds=args.interval,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
