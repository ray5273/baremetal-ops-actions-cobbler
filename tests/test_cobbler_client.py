"""CobblerClient 단위 테스트 (XML-RPC 모킹)."""

import unittest
from unittest.mock import MagicMock, patch

from scripts.cobbler_client import CobblerClient


class TestCobblerClient(unittest.TestCase):
    """CobblerClient 테스트."""

    def _make_client(self, mock_server: MagicMock) -> CobblerClient:
        """모킹된 서버로 CobblerClient를 생성한다."""
        mock_server.login.return_value = "test-token"
        with patch(
            "scripts.cobbler_client.xmlrpc.client.ServerProxy", return_value=mock_server
        ):
            return CobblerClient("http://test/cobbler_api", "admin", "password")

    def test_login_success(self) -> None:
        """정상 로그인 테스트."""
        mock_server = MagicMock()
        client = self._make_client(mock_server)
        self.assertEqual(client.token, "test-token")
        mock_server.login.assert_called_once_with("admin", "password")

    def test_login_failure(self) -> None:
        """잘못된 인증정보로 로그인 실패 테스트."""
        import xmlrpc.client

        mock_server = MagicMock()
        mock_server.login.side_effect = xmlrpc.client.Fault(1, "login failed")
        with patch(
            "scripts.cobbler_client.xmlrpc.client.ServerProxy", return_value=mock_server
        ):
            with self.assertRaises(SystemExit):
                CobblerClient("http://test/cobbler_api", "admin", "wrong")

    def test_get_system_exists(self) -> None:
        """존재하는 시스템 조회 테스트."""
        mock_server = MagicMock()
        mock_server.get_system.return_value = {
            "name": "rack01-srv001",
            "profile": "rhel9-x86_64",
        }
        client = self._make_client(mock_server)
        result = client.get_system("rack01-srv001")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "rack01-srv001")

    def test_get_system_not_found(self) -> None:
        """없는 시스템 조회 → None 반환 테스트."""
        import xmlrpc.client

        mock_server = MagicMock()
        mock_server.get_system.side_effect = xmlrpc.client.Fault(1, "not found")
        client = self._make_client(mock_server)
        result = client.get_system("nonexistent")
        self.assertIsNone(result)

    def test_set_system_profile(self) -> None:
        """프로파일 변경 테스트."""
        mock_server = MagicMock()
        mock_server.get_profiles.return_value = [
            {"name": "rhel9-x86_64"},
            {"name": "ubuntu2204-x86_64"},
        ]
        mock_server.get_system_handle.return_value = "handle-123"
        client = self._make_client(mock_server)

        client.set_system_profile("rack01-srv001", "rhel9-x86_64")

        mock_server.get_system_handle.assert_called_once_with(
            "rack01-srv001", "test-token"
        )
        mock_server.modify_system.assert_called_once_with(
            "handle-123", "profile", "rhel9-x86_64", "test-token"
        )
        mock_server.save_system.assert_called_once_with("handle-123", "test-token")

    def test_set_system_profile_invalid(self) -> None:
        """없는 프로파일로 변경 시 에러 테스트."""
        mock_server = MagicMock()
        mock_server.get_profiles.return_value = [{"name": "rhel9-x86_64"}]
        client = self._make_client(mock_server)

        with self.assertRaises(SystemExit):
            client.set_system_profile("rack01-srv001", "nonexistent-profile")

    def test_enable_netboot(self) -> None:
        """Netboot 활성화 테스트."""
        mock_server = MagicMock()
        mock_server.get_system_handle.return_value = "handle-123"
        client = self._make_client(mock_server)

        client.enable_netboot("rack01-srv001")

        mock_server.modify_system.assert_called_once_with(
            "handle-123", "netboot_enabled", True, "test-token"
        )
        mock_server.save_system.assert_called_once()

    def test_sync(self) -> None:
        """Sync 호출 테스트."""
        mock_server = MagicMock()
        client = self._make_client(mock_server)

        client.sync()

        mock_server.sync.assert_called_once_with("test-token")

    def test_add_system(self) -> None:
        """시스템 추가 테스트 (인터페이스 포함)."""
        mock_server = MagicMock()
        mock_server.new_system.return_value = "new-handle"
        client = self._make_client(mock_server)

        config = {
            "name": "rack01-srv003",
            "profile": "rhel9-x86_64",
            "hostname": "rack01-srv003.internal",
            "gateway": "10.0.1.1",
            "interfaces": [
                {
                    "name": "ens1f0",
                    "mac_address": "aa:bb:cc:dd:ee:33",
                    "ip_address": "10.0.1.103",
                    "netmask": "255.255.255.0",
                    "static": True,
                }
            ],
        }

        client.add_system(config)

        mock_server.new_system.assert_called_once_with("test-token")
        # name, profile, hostname, gateway 설정 + interface 설정 = 5 호출
        self.assertEqual(mock_server.modify_system.call_count, 5)
        mock_server.save_system.assert_called_once_with("new-handle", "test-token")

    def test_remove_system(self) -> None:
        """시스템 삭제 테스트."""
        mock_server = MagicMock()
        client = self._make_client(mock_server)

        client.remove_system("rack01-srv001")

        mock_server.remove_system.assert_called_once_with("rack01-srv001", "test-token")


if __name__ == "__main__":
    unittest.main()
