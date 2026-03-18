#!/usr/bin/env python3
"""Cobbler CI test data 초기화 스크립트.

Apache/WSGI를 통해 Cobbler XMLRPC API에 접속하여 테스트용 distro/profile을 생성한다.
컨테이너 외부(CI runner)에서 실행된다.
"""
import os
import socket
import sys
import time
import xmlrpc.client

COBBLER_URL = os.environ.get("COBBLER_URL", "http://localhost/cobbler_api")
COBBLER_USER = os.environ.get("COBBLER_USER", "cobbler")
COBBLER_PASS = os.environ.get("COBBLER_PASS", "cobbler")

PROFILES = [
    "rhel9-x86_64",
    "rhel8-x86_64",
    "ubuntu2204-x86_64",
    "ubuntu2404-x86_64",
    "rocky9-x86_64",
]

# 소켓 타임아웃 설정 (초) - XMLRPC 호출이 hang되는 것을 방지
socket.setdefaulttimeout(15)


def wait_for_api(url: str, user: str, password: str, max_retries: int = 30, delay: int = 2) -> tuple:
    """Cobbler XMLRPC API가 응답할 때까지 대기. (server, token) 반환."""
    print(f"Cobbler API 대기 중: {url}")
    server = xmlrpc.client.ServerProxy(url)
    for i in range(1, max_retries + 1):
        try:
            # Cobbler의 login() 메서드로 API 준비 상태 확인
            token = server.login(user, password)
            if token:
                print(f"Cobbler API 준비 완료 (attempt {i}/{max_retries})")
                return server, token
        except xmlrpc.client.Fault as e:
            print(f"  대기 중... ({i}/{max_retries}): Fault: {e}")
            time.sleep(delay)
        except Exception as e:
            print(f"  대기 중... ({i}/{max_retries}): {type(e).__name__}: {e}")
            time.sleep(delay)
    print("ERROR: Cobbler API 시작 시간 초과")
    sys.exit(1)


def setup_test_data(server: xmlrpc.client.ServerProxy, token: str) -> None:
    """테스트용 distro + profile 생성."""
    for name in PROFILES:
        print(f"프로파일 생성 중: {name}")

        # distro 존재 확인
        existing = server.get_distro(name, token)
        if existing == "~":
            # 더미 kernel/initrd 경로 (컨테이너 내부에 생성해야 함)
            distro_id = server.new_distro(token)
            server.modify_distro(distro_id, "name", name, token)
            server.modify_distro(distro_id, "kernel", f"/var/www/cobbler/distro_mirror/{name}/vmlinuz", token)
            server.modify_distro(distro_id, "initrd", f"/var/www/cobbler/distro_mirror/{name}/initrd.img", token)
            server.modify_distro(distro_id, "arch", "x86_64", token)
            server.save_distro(distro_id, token)
            print(f"  distro 생성 완료: {name}")
        else:
            print(f"  distro 이미 존재: {name}")

        # profile 존재 확인
        existing_profile = server.get_profile(name, token)
        if existing_profile == "~":
            profile_id = server.new_profile(token)
            server.modify_profile(profile_id, "name", name, token)
            server.modify_profile(profile_id, "distro", name, token)
            server.save_profile(profile_id, token)
            print(f"  profile 생성 완료: {name}")
        else:
            print(f"  profile 이미 존재: {name}")


def main() -> None:
    print("=== Cobbler CI 초기화 시작 ===")

    server, token = wait_for_api(COBBLER_URL, COBBLER_USER, COBBLER_PASS)
    print(f"로그인 성공 (token: {token[:20]}...)")

    setup_test_data(server, token)

    # sync
    print("cobbler sync 실행 중...")
    try:
        server.sync(token)
        print("sync 완료")
    except Exception as e:
        print(f"WARNING: sync 실패 (non-fatal): {e}")

    # 결과 확인
    profiles = server.get_profiles(token)
    print(f"\n=== Cobbler CI 초기화 완료 ===")
    print(f"생성된 프로파일: {[p['name'] for p in profiles]}")


if __name__ == "__main__":
    main()
