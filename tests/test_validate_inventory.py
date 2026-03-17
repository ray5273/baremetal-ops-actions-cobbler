"""YAML 검증 로직 테스트."""

import os
import tempfile
import unittest

import yaml

from scripts.validate_inventory import validate_systems


class TestValidateInventory(unittest.TestCase):
    """validate_inventory 테스트."""

    def setUp(self) -> None:
        """임시 디렉토리에 테스트 파일들을 생성한다."""
        self.tmpdir = tempfile.mkdtemp()
        self.systems_dir = os.path.join(self.tmpdir, "systems")
        os.makedirs(self.systems_dir)

        # 스키마 파일 생성
        self.schema_path = os.path.join(self.tmpdir, "schema.yaml")
        schema = {
            "type": "object",
            "required": ["name", "profile", "hostname", "bmc_ip", "interfaces"],
            "properties": {
                "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*[a-z0-9]$"},
                "profile": {"type": "string"},
                "hostname": {"type": "string"},
                "bmc_ip": {"type": "string"},
                "gateway": {"type": "string"},
                "name_servers": {"type": "array", "items": {"type": "string"}},
                "interfaces": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["name", "mac_address", "ip_address", "netmask"],
                        "properties": {
                            "name": {"type": "string"},
                            "mac_address": {
                                "type": "string",
                                "pattern": "^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$",
                            },
                            "ip_address": {"type": "string"},
                            "netmask": {"type": "string"},
                            "static": {"type": "boolean"},
                        },
                    },
                },
                "tags": {"type": "array", "items": {"type": "string"}},
                "boot_loader": {"type": "string", "enum": ["grub", "pxelinux"]},
                "comment": {"type": "string"},
            },
        }
        with open(self.schema_path, "w") as f:
            yaml.dump(schema, f)

        # 카탈로그 파일 생성
        self.catalog_path = os.path.join(self.tmpdir, "catalog.yaml")
        catalog = {
            "profiles": [
                {"name": "rhel9-x86_64"},
                {"name": "ubuntu2204-x86_64"},
            ]
        }
        with open(self.catalog_path, "w") as f:
            yaml.dump(catalog, f)

    def _write_system(self, filename: str, data: dict) -> None:
        """시스템 YAML 파일을 생성한다."""
        filepath = os.path.join(self.systems_dir, filename)
        with open(filepath, "w") as f:
            yaml.dump(data, f)

    def _valid_system(self, name: str = "test-srv01", **overrides) -> dict:
        """유효한 시스템 데이터를 반환한다."""
        data = {
            "name": name,
            "profile": "rhel9-x86_64",
            "hostname": f"{name}.internal",
            "bmc_ip": "10.0.100.1",
            "interfaces": [
                {
                    "name": "eth0",
                    "mac_address": "aa:bb:cc:dd:ee:01",
                    "ip_address": "10.0.1.1",
                    "netmask": "255.255.255.0",
                    "static": True,
                }
            ],
        }
        data.update(overrides)
        return data

    def test_valid_system(self) -> None:
        """정상 YAML 통과 테스트."""
        self._write_system("test-srv01.yaml", self._valid_system())
        result = validate_systems(self.systems_dir, self.schema_path, self.catalog_path)
        self.assertTrue(result)

    def test_missing_required_field(self) -> None:
        """필수 필드 누락 → 실패 테스트."""
        data = self._valid_system()
        del data["hostname"]
        self._write_system("test-srv01.yaml", data)
        result = validate_systems(self.systems_dir, self.schema_path, self.catalog_path)
        self.assertFalse(result)

    def test_invalid_mac_format(self) -> None:
        """MAC 주소 형식 오류 테스트."""
        data = self._valid_system()
        data["interfaces"][0]["mac_address"] = "invalid-mac"
        self._write_system("test-srv01.yaml", data)
        result = validate_systems(self.systems_dir, self.schema_path, self.catalog_path)
        self.assertFalse(result)

    def test_invalid_profile(self) -> None:
        """카탈로그에 없는 프로파일 테스트."""
        data = self._valid_system(profile="nonexistent-x86_64")
        self._write_system("test-srv01.yaml", data)
        result = validate_systems(self.systems_dir, self.schema_path, self.catalog_path)
        self.assertFalse(result)

    def test_duplicate_mac(self) -> None:
        """MAC 주소 중복 감지 테스트."""
        data1 = self._valid_system("test-srv01", bmc_ip="10.0.100.1")
        data2 = self._valid_system("test-srv02", bmc_ip="10.0.100.2")
        # 같은 MAC 주소
        data2["interfaces"][0]["ip_address"] = "10.0.1.2"
        self._write_system("test-srv01.yaml", data1)
        self._write_system("test-srv02.yaml", data2)
        result = validate_systems(self.systems_dir, self.schema_path, self.catalog_path)
        self.assertFalse(result)

    def test_duplicate_ip(self) -> None:
        """IP 주소 중복 감지 테스트."""
        data1 = self._valid_system("test-srv01", bmc_ip="10.0.100.1")
        data2 = self._valid_system("test-srv02", bmc_ip="10.0.100.2")
        data2["interfaces"][0]["mac_address"] = "aa:bb:cc:dd:ee:02"
        # 같은 IP 주소 (10.0.1.1)
        self._write_system("test-srv01.yaml", data1)
        self._write_system("test-srv02.yaml", data2)
        result = validate_systems(self.systems_dir, self.schema_path, self.catalog_path)
        self.assertFalse(result)

    def test_filename_mismatch(self) -> None:
        """파일명과 name 불일치 테스트."""
        data = self._valid_system("different-name")
        self._write_system("test-srv01.yaml", data)
        result = validate_systems(self.systems_dir, self.schema_path, self.catalog_path)
        self.assertFalse(result)

    def test_underscore_prefix_skipped(self) -> None:
        """_example.yaml 건너뜀 테스트."""
        data = self._valid_system("example")  # name 불일치해도 스킵되어야 함
        self._write_system("_example.yaml", data)
        result = validate_systems(self.systems_dir, self.schema_path, self.catalog_path)
        self.assertTrue(result)

    def test_duplicate_bmc_ip(self) -> None:
        """BMC IP 중복 감지 테스트."""
        data1 = self._valid_system("test-srv01")
        data2 = self._valid_system("test-srv02")
        data2["interfaces"][0]["mac_address"] = "aa:bb:cc:dd:ee:02"
        data2["interfaces"][0]["ip_address"] = "10.0.1.2"
        # 같은 BMC IP
        self._write_system("test-srv01.yaml", data1)
        self._write_system("test-srv02.yaml", data2)
        result = validate_systems(self.systems_dir, self.schema_path, self.catalog_path)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
