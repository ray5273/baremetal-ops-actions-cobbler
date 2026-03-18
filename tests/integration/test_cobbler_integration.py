#!/usr/bin/env python3
"""Cobbler XML-RPC API 통합 테스트.

실제 Cobbler 서버(Docker)에 접속하여 cobbler_client, cobbler_diff, cobbler_sync를
검증한다. COBBLER_URL 환경변수가 설정되어 있을 때만 실행된다.
"""

import os
import unittest

COBBLER_URL = os.environ.get("COBBLER_URL", "")
COBBLER_USER = os.environ.get("COBBLER_USER", "cobbler")
COBBLER_PASS = os.environ.get("COBBLER_PASS", "cobbler")

SKIP_MSG = "COBBLER_URL not set — skipping integration tests"


@unittest.skipUnless(COBBLER_URL, SKIP_MSG)
class TestCobblerClientIntegration(unittest.TestCase):
    """CobblerClient 기본 동작 테스트."""

    def setUp(self):
        from scripts.cobbler_client import CobblerClient

        self.client = CobblerClient(COBBLER_URL, COBBLER_USER, COBBLER_PASS)

    def test_login_success(self):
        """인증 토큰이 정상적으로 발급되는지 확인."""
        self.assertIsNotNone(self.client.token)
        self.assertNotEqual(self.client.token, "")

    def test_list_profiles(self):
        """CI에서 생성한 5개 프로파일이 존재하는지 확인."""
        profiles = self.client.list_profiles()
        profile_names = [p["name"] for p in profiles]
        expected = [
            "rhel9-x86_64",
            "rhel8-x86_64",
            "ubuntu2204-x86_64",
            "ubuntu2404-x86_64",
            "rocky9-x86_64",
        ]
        for name in expected:
            self.assertIn(name, profile_names, f"Profile missing: {name}")

    def test_list_systems_empty(self):
        """초기 상태에서 시스템 목록이 비어 있거나 조회 가능한지 확인."""
        systems = self.client.list_systems()
        self.assertIsInstance(systems, list)

    def test_add_and_get_system(self):
        """시스템 추가 후 조회가 가능한지 확인."""
        config = {
            "name": "test-integration-srv",
            "profile": "rhel9-x86_64",
            "hostname": "test-integration.local",
            "interfaces": [
                {
                    "name": "eth0",
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "ip_address": "192.168.1.100",
                    "netmask": "255.255.255.0",
                    "static": True,
                }
            ],
        }
        self.client.add_system(config)
        self.client.sync()

        system = self.client.get_system("test-integration-srv")
        self.assertIsNotNone(system)
        self.assertEqual(system["name"], "test-integration-srv")
        self.assertEqual(system["profile"], "rhel9-x86_64")

    def test_remove_system(self):
        """시스템 삭제 후 조회되지 않는지 확인."""
        config = {
            "name": "test-remove-srv",
            "profile": "rhel9-x86_64",
            "hostname": "test-remove.local",
            "interfaces": [
                {
                    "name": "eth0",
                    "mac_address": "AA:BB:CC:DD:EE:01",
                    "ip_address": "192.168.1.101",
                    "netmask": "255.255.255.0",
                    "static": True,
                }
            ],
        }
        self.client.add_system(config)
        self.client.sync()

        self.client.remove_system("test-remove-srv")
        system = self.client.get_system("test-remove-srv")
        self.assertIsNone(system)

    def tearDown(self):
        """테스트에서 생성한 시스템 정리."""
        for name in ["test-integration-srv", "test-remove-srv"]:
            try:
                self.client.remove_system(name)
            except Exception:
                pass


@unittest.skipUnless(COBBLER_URL, SKIP_MSG)
class TestCobblerDiffIntegration(unittest.TestCase):
    """cobbler_diff 스크립트 통합 테스트."""

    def setUp(self):
        from scripts.cobbler_client import CobblerClient

        self.client = CobblerClient(COBBLER_URL, COBBLER_USER, COBBLER_PASS)

    def test_diff_detects_creates(self):
        """Git에 정의된 시스템이 Cobbler에 없으면 CREATE로 감지되는지 확인."""
        from scripts.cobbler_diff import compute_diff, load_git_systems

        systems_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "inventory", "systems"
        )
        git_systems = load_git_systems(systems_dir)
        diff = compute_diff(self.client, git_systems)

        # 초기 상태이므로 모든 Git 시스템이 create에 있어야 함
        create_names = [c["name"] for c in diff["creates"]]
        self.assertGreater(len(create_names), 0, "Should detect systems to create")

    def test_diff_json_output(self):
        """JSON 출력 포맷이 올바른 키를 포함하는지 확인."""
        from scripts.cobbler_diff import compute_diff, load_git_systems

        systems_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "inventory", "systems"
        )
        git_systems = load_git_systems(systems_dir)
        diff = compute_diff(self.client, git_systems)

        self.assertIn("creates", diff)
        self.assertIn("updates", diff)
        self.assertIn("orphans", diff)


@unittest.skipUnless(COBBLER_URL, SKIP_MSG)
class TestCobblerSyncIntegration(unittest.TestCase):
    """cobbler_sync 스크립트 통합 테스트."""

    def setUp(self):
        from scripts.cobbler_client import CobblerClient

        self.client = CobblerClient(COBBLER_URL, COBBLER_USER, COBBLER_PASS)

    def test_sync_dry_run(self):
        """dry-run 모드에서 실제 변경이 발생하지 않는지 확인."""
        from scripts.cobbler_diff import compute_diff, load_git_systems
        from scripts.cobbler_sync import apply_creates

        systems_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "inventory", "systems"
        )
        git_systems = load_git_systems(systems_dir)
        diff = compute_diff(self.client, git_systems)

        before_count = len(self.client.list_systems())
        apply_creates(self.client, diff["creates"], git_systems, dry_run=True)
        after_count = len(self.client.list_systems())

        self.assertEqual(before_count, after_count, "dry-run should not add systems")


if __name__ == "__main__":
    unittest.main()
