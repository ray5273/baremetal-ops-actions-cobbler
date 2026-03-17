"""cobbler_diff 로직 테스트."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

import yaml

from scripts.cobbler_diff import (
    compute_diff,
    format_github,
    format_human,
    format_json,
)


class TestCobblerDiff(unittest.TestCase):
    """cobbler_diff 테스트."""

    def setUp(self) -> None:
        """임시 디렉토리와 모킹 클라이언트를 설정한다."""
        self.tmpdir = tempfile.mkdtemp()
        self.systems_dir = os.path.join(self.tmpdir, "systems")
        os.makedirs(self.systems_dir)

    def _write_system(self, name: str, data: dict) -> None:
        """시스템 YAML 파일을 생성한다."""
        filepath = os.path.join(self.systems_dir, f"{name}.yaml")
        with open(filepath, "w") as f:
            yaml.dump(data, f)

    def _make_git_system(
        self, name: str, profile: str = "rhel9-x86_64", ip: str = "10.0.1.1"
    ) -> dict:
        """Git 시스템 데이터를 생성한다."""
        return {
            "name": name,
            "profile": profile,
            "hostname": f"{name}.internal",
            "gateway": "10.0.1.1",
            "name_servers": ["8.8.8.8"],
            "boot_loader": "grub",
            "interfaces": [
                {
                    "name": "eth0",
                    "mac_address": "aa:bb:cc:dd:ee:01",
                    "ip_address": ip,
                    "netmask": "255.255.255.0",
                    "static": True,
                }
            ],
        }

    def _make_cobbler_system(
        self, name: str, profile: str = "rhel9-x86_64", ip: str = "10.0.1.1"
    ) -> dict:
        """Cobbler 시스템 데이터를 생성한다."""
        return {
            "name": name,
            "profile": profile,
            "hostname": f"{name}.internal",
            "gateway": "10.0.1.1",
            "name_servers": ["8.8.8.8"],
            "boot_loader": "grub",
            "interfaces": {
                "eth0": {
                    "mac_address": "aa:bb:cc:dd:ee:01",
                    "ip_address": ip,
                    "netmask": "255.255.255.0",
                    "static": True,
                }
            },
        }

    def _make_mock_client(self, cobbler_systems: list[dict]) -> MagicMock:
        """모킹된 CobblerClient를 생성한다."""
        client = MagicMock()
        client.list_systems.return_value = cobbler_systems
        return client

    def test_no_changes(self) -> None:
        """동일 상태 → 빈 diff 테스트."""
        self._write_system("srv01", self._make_git_system("srv01"))
        client = self._make_mock_client([self._make_cobbler_system("srv01")])

        diff = compute_diff(self.systems_dir, client)

        self.assertEqual(len(diff["creates"]), 0)
        self.assertEqual(len(diff["updates"]), 0)
        self.assertEqual(len(diff["orphans"]), 0)

    def test_new_system(self) -> None:
        """Git에만 존재 → CREATE 테스트."""
        self._write_system("srv01", self._make_git_system("srv01"))
        client = self._make_mock_client([])

        diff = compute_diff(self.systems_dir, client)

        self.assertEqual(len(diff["creates"]), 1)
        self.assertEqual(diff["creates"][0]["name"], "srv01")

    def test_profile_changed(self) -> None:
        """프로파일 변경 → UPDATE 테스트."""
        self._write_system(
            "srv01", self._make_git_system("srv01", profile="ubuntu2204-x86_64")
        )
        client = self._make_mock_client(
            [self._make_cobbler_system("srv01", profile="rhel9-x86_64")]
        )

        diff = compute_diff(self.systems_dir, client)

        self.assertEqual(len(diff["updates"]), 1)
        changes = diff["updates"][0]["changes"]
        profile_change = [c for c in changes if c["field"] == "profile"]
        self.assertEqual(len(profile_change), 1)
        self.assertEqual(profile_change[0]["from"], "rhel9-x86_64")
        self.assertEqual(profile_change[0]["to"], "ubuntu2204-x86_64")

    def test_ip_changed(self) -> None:
        """IP 변경 → UPDATE 테스트."""
        self._write_system("srv01", self._make_git_system("srv01", ip="10.0.1.100"))
        client = self._make_mock_client(
            [self._make_cobbler_system("srv01", ip="10.0.1.1")]
        )

        diff = compute_diff(self.systems_dir, client)

        self.assertEqual(len(diff["updates"]), 1)
        changes = diff["updates"][0]["changes"]
        ip_change = [c for c in changes if "ip_address" in c["field"]]
        self.assertEqual(len(ip_change), 1)

    def test_orphan_system(self) -> None:
        """Cobbler에만 존재 → ORPHAN 테스트."""
        client = self._make_mock_client([self._make_cobbler_system("orphan-srv")])

        diff = compute_diff(self.systems_dir, client)

        self.assertEqual(len(diff["orphans"]), 1)
        self.assertEqual(diff["orphans"][0]["name"], "orphan-srv")

    def test_multiple_changes(self) -> None:
        """복합 변경 테스트."""
        # 신규 시스템
        self._write_system("new-srv", self._make_git_system("new-srv", ip="10.0.1.10"))
        # 변경된 시스템
        self._write_system(
            "changed-srv",
            self._make_git_system(
                "changed-srv", profile="ubuntu2204-x86_64", ip="10.0.1.20"
            ),
        )
        client = self._make_mock_client(
            [
                self._make_cobbler_system(
                    "changed-srv", profile="rhel9-x86_64", ip="10.0.1.20"
                ),
                self._make_cobbler_system("orphan-srv", ip="10.0.1.30"),
            ]
        )

        diff = compute_diff(self.systems_dir, client)

        self.assertEqual(len(diff["creates"]), 1)
        self.assertEqual(len(diff["updates"]), 1)
        self.assertEqual(len(diff["orphans"]), 1)

    def test_output_format_json(self) -> None:
        """JSON 출력 형식 테스트."""
        self._write_system("srv01", self._make_git_system("srv01"))
        client = self._make_mock_client([])

        diff = compute_diff(self.systems_dir, client)
        output = format_json(diff)
        parsed = json.loads(output)

        self.assertIn("creates", parsed)
        self.assertIn("updates", parsed)
        self.assertIn("orphans", parsed)
        self.assertEqual(len(parsed["creates"]), 1)

    def test_output_format_github(self) -> None:
        """GitHub 마크다운 출력 테스트."""
        self._write_system("srv01", self._make_git_system("srv01"))
        client = self._make_mock_client([])

        diff = compute_diff(self.systems_dir, client)
        output = format_github(diff)

        self.assertIn("srv01", output)
        self.assertIn("신규 등록", output)

    def test_output_format_human_no_changes(self) -> None:
        """변경 없을 때 human 출력 테스트."""
        diff = {"creates": [], "updates": [], "orphans": []}
        output = format_human(diff)
        self.assertIn("동기화 상태", output)

    def test_target_filter(self) -> None:
        """--target 필터링 테스트."""
        self._write_system("srv01", self._make_git_system("srv01", ip="10.0.1.1"))
        self._write_system("srv02", self._make_git_system("srv02", ip="10.0.1.2"))
        client = self._make_mock_client([])

        diff = compute_diff(self.systems_dir, client, target="srv01")

        self.assertEqual(len(diff["creates"]), 1)
        self.assertEqual(diff["creates"][0]["name"], "srv01")


if __name__ == "__main__":
    unittest.main()
