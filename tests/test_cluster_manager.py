"""cluster_manager 단위 테스트."""

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.cluster_manager import (
    format_plan_github,
    format_plan_human,
    format_plan_json,
    get_cluster_files,
    get_deploy_plan,
    load_all_clusters,
    resolve_cluster_nodes,
    split_batches,
    validate_clusters,
)


class TestClusterFiles(unittest.TestCase):
    """클러스터 파일 로딩 테스트."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()

    def _write_yaml(self, name: str, data: dict) -> None:
        path = Path(self.tmpdir) / name
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

    def test_get_cluster_files_excludes_underscore(self) -> None:
        """언더스코어 프리픽스 파일은 제외된다."""
        self._write_yaml("test-cluster.yaml", {"name": "test-cluster"})
        self._write_yaml("_example.yaml", {"name": "example"})
        self._write_yaml("schema.yaml", {"type": "object"})

        files = get_cluster_files(self.tmpdir)
        names = [f.name for f in files]
        self.assertIn("test-cluster.yaml", names)
        self.assertNotIn("_example.yaml", names)
        self.assertNotIn("schema.yaml", names)

    def test_load_all_clusters(self) -> None:
        """모든 클러스터를 로드한다."""
        self._write_yaml(
            "c1.yaml",
            {"name": "c1", "nodes": [{"name": "n1"}]},
        )
        self._write_yaml(
            "c2.yaml",
            {"name": "c2", "nodes": [{"name": "n2"}]},
        )
        clusters = load_all_clusters(self.tmpdir)
        self.assertEqual(len(clusters), 2)
        self.assertIn("c1", clusters)
        self.assertIn("c2", clusters)


class TestClusterValidation(unittest.TestCase):
    """클러스터 YAML 검증 테스트."""

    def setUp(self) -> None:
        """테스트용 임시 디렉토리 구조를 생성한다."""
        self.tmpdir = tempfile.mkdtemp()

        # clusters 디렉토리
        self.clusters_dir = Path(self.tmpdir) / "clusters"
        self.clusters_dir.mkdir()

        # systems 디렉토리
        self.systems_dir = Path(self.tmpdir) / "systems"
        self.systems_dir.mkdir()

        # 프로파일 카탈로그
        self.catalog_path = Path(self.tmpdir) / "catalog.yaml"
        with open(self.catalog_path, "w", encoding="utf-8") as f:
            yaml.dump(
                {
                    "profiles": [
                        {"name": "rhel9-x86_64"},
                        {"name": "ubuntu2204-x86_64"},
                        {"name": "rocky9-x86_64"},
                    ]
                },
                f,
            )

        # 클러스터 스키마 (프로젝트 실제 스키마 복사)
        self.schema_path = Path(self.tmpdir) / "schema.yaml"
        schema = {
            "type": "object",
            "required": ["name", "description", "default_profile", "nodes"],
            "properties": {
                "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*[a-z0-9]$"},
                "description": {"type": "string"},
                "default_profile": {"type": "string"},
                "use_efi": {"type": "boolean"},
                "rolling": {
                    "type": "object",
                    "properties": {
                        "enabled": {"type": "boolean"},
                        "batch_size": {"type": "integer", "minimum": 1},
                        "pause_between_batches": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "nodes": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {
                            "name": {
                                "type": "string",
                                "pattern": "^[a-z0-9][a-z0-9-]*[a-z0-9]$",
                            },
                            "profile_override": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                },
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": False,
        }
        with open(self.schema_path, "w", encoding="utf-8") as f:
            yaml.dump(schema, f)

        # 시스템 YAML 예시
        self._add_system("srv01", "rhel9-x86_64", "10.0.100.1")
        self._add_system("srv02", "rhel9-x86_64", "10.0.100.2")

    def _add_system(self, name: str, profile: str, bmc_ip: str) -> None:
        path = self.systems_dir / f"{name}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                {
                    "name": name,
                    "profile": profile,
                    "hostname": f"{name}.test.internal",
                    "bmc_ip": bmc_ip,
                    "interfaces": [
                        {
                            "name": "eth0",
                            "mac_address": f"aa:bb:cc:dd:ee:{name[-2:]}",
                            "ip_address": f"10.0.1.{int(name[-2:])}",
                            "netmask": "255.255.255.0",
                        }
                    ],
                },
                f,
            )

    def _add_cluster(self, name: str, data: dict) -> None:
        path = self.clusters_dir / f"{name}.yaml"
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f)

    def test_valid_cluster(self) -> None:
        """유효한 클러스터 검증 통과."""
        self._add_cluster(
            "test-cluster",
            {
                "name": "test-cluster",
                "description": "Test cluster",
                "default_profile": "rhel9-x86_64",
                "nodes": [{"name": "srv01"}, {"name": "srv02"}],
            },
        )
        result = validate_clusters(
            clusters_dir=str(self.clusters_dir),
            schema_path=str(self.schema_path),
            systems_dir=str(self.systems_dir),
            catalog_path=str(self.catalog_path),
        )
        self.assertTrue(result)

    def test_invalid_profile(self) -> None:
        """카탈로그에 없는 프로파일은 실패."""
        self._add_cluster(
            "bad-cluster",
            {
                "name": "bad-cluster",
                "description": "Bad",
                "default_profile": "nonexistent-profile",
                "nodes": [{"name": "srv01"}],
            },
        )
        result = validate_clusters(
            clusters_dir=str(self.clusters_dir),
            schema_path=str(self.schema_path),
            systems_dir=str(self.systems_dir),
            catalog_path=str(self.catalog_path),
        )
        self.assertFalse(result)

    def test_missing_node_in_inventory(self) -> None:
        """inventory에 없는 노드 참조는 실패."""
        self._add_cluster(
            "bad-cluster",
            {
                "name": "bad-cluster",
                "description": "Bad",
                "default_profile": "rhel9-x86_64",
                "nodes": [{"name": "nonexistent-node"}],
            },
        )
        result = validate_clusters(
            clusters_dir=str(self.clusters_dir),
            schema_path=str(self.schema_path),
            systems_dir=str(self.systems_dir),
            catalog_path=str(self.catalog_path),
        )
        self.assertFalse(result)

    def test_duplicate_node(self) -> None:
        """같은 노드를 두 번 넣으면 실패."""
        self._add_cluster(
            "dup-cluster",
            {
                "name": "dup-cluster",
                "description": "Dup",
                "default_profile": "rhel9-x86_64",
                "nodes": [{"name": "srv01"}, {"name": "srv01"}],
            },
        )
        result = validate_clusters(
            clusters_dir=str(self.clusters_dir),
            schema_path=str(self.schema_path),
            systems_dir=str(self.systems_dir),
            catalog_path=str(self.catalog_path),
        )
        self.assertFalse(result)

    def test_filename_name_mismatch(self) -> None:
        """파일명과 name 필드가 다르면 실패."""
        self._add_cluster(
            "file-name",
            {
                "name": "different-name",
                "description": "Mismatch",
                "default_profile": "rhel9-x86_64",
                "nodes": [{"name": "srv01"}],
            },
        )
        result = validate_clusters(
            clusters_dir=str(self.clusters_dir),
            schema_path=str(self.schema_path),
            systems_dir=str(self.systems_dir),
            catalog_path=str(self.catalog_path),
        )
        self.assertFalse(result)

    def test_invalid_profile_override(self) -> None:
        """카탈로그에 없는 profile_override는 실패."""
        self._add_cluster(
            "override-cluster",
            {
                "name": "override-cluster",
                "description": "Override test",
                "default_profile": "rhel9-x86_64",
                "nodes": [{"name": "srv01", "profile_override": "nonexistent-os"}],
            },
        )
        result = validate_clusters(
            clusters_dir=str(self.clusters_dir),
            schema_path=str(self.schema_path),
            systems_dir=str(self.systems_dir),
            catalog_path=str(self.catalog_path),
        )
        self.assertFalse(result)

    def test_valid_profile_override(self) -> None:
        """유효한 profile_override는 통과."""
        self._add_cluster(
            "override-cluster",
            {
                "name": "override-cluster",
                "description": "Override test",
                "default_profile": "rhel9-x86_64",
                "nodes": [{"name": "srv01", "profile_override": "ubuntu2204-x86_64"}],
            },
        )
        result = validate_clusters(
            clusters_dir=str(self.clusters_dir),
            schema_path=str(self.schema_path),
            systems_dir=str(self.systems_dir),
            catalog_path=str(self.catalog_path),
        )
        self.assertTrue(result)

    def test_no_cluster_files(self) -> None:
        """클러스터 파일이 없으면 True 반환."""
        empty_dir = Path(self.tmpdir) / "empty"
        empty_dir.mkdir()
        result = validate_clusters(
            clusters_dir=str(empty_dir),
            schema_path=str(self.schema_path),
            systems_dir=str(self.systems_dir),
            catalog_path=str(self.catalog_path),
        )
        self.assertTrue(result)

    def test_schema_violation_missing_description(self) -> None:
        """필수 필드 누락은 실패."""
        self._add_cluster(
            "no-desc",
            {
                "name": "no-desc",
                # description 누락
                "default_profile": "rhel9-x86_64",
                "nodes": [{"name": "srv01"}],
            },
        )
        result = validate_clusters(
            clusters_dir=str(self.clusters_dir),
            schema_path=str(self.schema_path),
            systems_dir=str(self.systems_dir),
            catalog_path=str(self.catalog_path),
        )
        self.assertFalse(result)


class TestSplitBatches(unittest.TestCase):
    """배치 분할 테스트."""

    def test_single_batch(self) -> None:
        """batch_size가 노드 수 이상이면 단일 배치."""
        nodes = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        batches = split_batches(nodes, batch_size=5)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]), 3)

    def test_multiple_batches(self) -> None:
        """batch_size=1이면 노드 수만큼 배치."""
        nodes = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        batches = split_batches(nodes, batch_size=1)
        self.assertEqual(len(batches), 3)
        self.assertEqual(len(batches[0]), 1)

    def test_uneven_batches(self) -> None:
        """노드 수가 batch_size로 나누어지지 않으면 마지막 배치가 작다."""
        nodes = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        batches = split_batches(nodes, batch_size=2)
        self.assertEqual(len(batches), 2)
        self.assertEqual(len(batches[0]), 2)
        self.assertEqual(len(batches[1]), 1)

    def test_zero_batch_size(self) -> None:
        """batch_size=0이면 전체를 한 배치로."""
        nodes = [{"name": "a"}, {"name": "b"}]
        batches = split_batches(nodes, batch_size=0)
        self.assertEqual(len(batches), 1)


class TestResolveClusterNodes(unittest.TestCase):
    """클러스터 노드 resolve 테스트."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.systems_dir = Path(self.tmpdir) / "systems"
        self.systems_dir.mkdir()

        # 시스템 파일 생성
        for name, bmc in [("srv01", "10.0.100.1"), ("srv02", "10.0.100.2")]:
            path = self.systems_dir / f"{name}.yaml"
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(
                    {
                        "name": name,
                        "profile": "rhel9-x86_64",
                        "hostname": f"{name}.test",
                        "bmc_ip": bmc,
                        "interfaces": [
                            {
                                "name": "eth0",
                                "mac_address": "aa:bb:cc:dd:ee:01",
                                "ip_address": "10.0.1.1",
                                "netmask": "255.255.255.0",
                            }
                        ],
                    },
                    f,
                )

    def test_resolve_uses_default_profile(self) -> None:
        """profile_override가 없으면 default_profile 사용."""
        cluster = {
            "name": "test-cluster",
            "default_profile": "rocky9-x86_64",
            "use_efi": True,
            "nodes": [{"name": "srv01"}],
        }
        nodes = resolve_cluster_nodes(cluster, str(self.systems_dir))
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["profile"], "rocky9-x86_64")
        self.assertEqual(nodes[0]["bmc_ip"], "10.0.100.1")
        self.assertTrue(nodes[0]["use_efi"])

    def test_resolve_uses_profile_override(self) -> None:
        """profile_override가 있으면 그것을 사용."""
        cluster = {
            "name": "test-cluster",
            "default_profile": "rhel9-x86_64",
            "use_efi": False,
            "nodes": [{"name": "srv01", "profile_override": "ubuntu2204-x86_64"}],
        }
        nodes = resolve_cluster_nodes(cluster, str(self.systems_dir))
        self.assertEqual(nodes[0]["profile"], "ubuntu2204-x86_64")
        self.assertFalse(nodes[0]["use_efi"])

    def test_resolve_skips_missing_system(self) -> None:
        """시스템 파일이 없으면 해당 노드는 건너뛴다."""
        cluster = {
            "name": "test-cluster",
            "default_profile": "rhel9-x86_64",
            "nodes": [{"name": "nonexistent"}],
        }
        nodes = resolve_cluster_nodes(cluster, str(self.systems_dir))
        self.assertEqual(len(nodes), 0)


class TestDeployPlan(unittest.TestCase):
    """배포 계획 생성 테스트."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.systems_dir = Path(self.tmpdir) / "systems"
        self.systems_dir.mkdir()

        for name, bmc in [
            ("srv01", "10.0.100.1"),
            ("srv02", "10.0.100.2"),
            ("srv03", "10.0.100.3"),
        ]:
            path = self.systems_dir / f"{name}.yaml"
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(
                    {
                        "name": name,
                        "profile": "rhel9-x86_64",
                        "hostname": f"{name}.test",
                        "bmc_ip": bmc,
                        "interfaces": [
                            {
                                "name": "eth0",
                                "mac_address": "aa:bb:cc:dd:ee:01",
                                "ip_address": "10.0.1.1",
                                "netmask": "255.255.255.0",
                            }
                        ],
                    },
                    f,
                )

    def test_non_rolling_plan(self) -> None:
        """rolling 비활성화 → 단일 배치."""
        cluster = {
            "name": "test-cluster",
            "description": "Test",
            "default_profile": "rhel9-x86_64",
            "use_efi": True,
            "rolling": {"enabled": False},
            "nodes": [{"name": "srv01"}, {"name": "srv02"}, {"name": "srv03"}],
        }
        plan = get_deploy_plan(cluster, str(self.systems_dir))
        self.assertEqual(plan["total_nodes"], 3)
        self.assertEqual(plan["total_batches"], 1)
        self.assertFalse(plan["rolling_enabled"])

    def test_rolling_plan(self) -> None:
        """rolling 활성화 → batch_size에 따른 분할."""
        cluster = {
            "name": "test-cluster",
            "description": "Test",
            "default_profile": "rhel9-x86_64",
            "use_efi": True,
            "rolling": {"enabled": True, "batch_size": 1},
            "nodes": [{"name": "srv01"}, {"name": "srv02"}, {"name": "srv03"}],
        }
        plan = get_deploy_plan(cluster, str(self.systems_dir))
        self.assertEqual(plan["total_batches"], 3)
        self.assertTrue(plan["rolling_enabled"])
        self.assertEqual(plan["batch_size"], 1)

    def test_rolling_batch_size_2(self) -> None:
        """batch_size=2 → 2개 배치 (2+1)."""
        cluster = {
            "name": "test-cluster",
            "description": "Test",
            "default_profile": "rocky9-x86_64",
            "rolling": {"enabled": True, "batch_size": 2},
            "nodes": [{"name": "srv01"}, {"name": "srv02"}, {"name": "srv03"}],
        }
        plan = get_deploy_plan(cluster, str(self.systems_dir))
        self.assertEqual(plan["total_batches"], 2)
        self.assertEqual(len(plan["batches"][0]), 2)
        self.assertEqual(len(plan["batches"][1]), 1)


class TestFormatters(unittest.TestCase):
    """출력 포맷터 테스트."""

    def _make_plan(self) -> dict:
        return {
            "cluster_name": "test-cluster",
            "description": "Test cluster",
            "rolling_enabled": True,
            "batch_size": 1,
            "pause_between_batches": False,
            "total_nodes": 2,
            "total_batches": 2,
            "batches": [
                [
                    {
                        "name": "srv01",
                        "profile": "rhel9-x86_64",
                        "bmc_ip": "10.0.100.1",
                        "use_efi": True,
                    }
                ],
                [
                    {
                        "name": "srv02",
                        "profile": "rhel9-x86_64",
                        "bmc_ip": "10.0.100.2",
                        "use_efi": True,
                    }
                ],
            ],
        }

    def test_format_human(self) -> None:
        """human 포맷에 핵심 정보가 포함된다."""
        output = format_plan_human(self._make_plan())
        self.assertIn("test-cluster", output)
        self.assertIn("srv01", output)
        self.assertIn("srv02", output)
        self.assertIn("rhel9-x86_64", output)
        self.assertIn("롤링", output)

    def test_format_json(self) -> None:
        """json 포맷이 유효한 JSON이다."""
        output = format_plan_json(self._make_plan())
        parsed = json.loads(output)
        self.assertEqual(parsed["cluster_name"], "test-cluster")
        self.assertEqual(len(parsed["batches"]), 2)

    def test_format_github(self) -> None:
        """github 포맷이 마크다운 테이블을 포함한다."""
        output = format_plan_github(self._make_plan())
        self.assertIn("| 배치 |", output)
        self.assertIn("`srv01`", output)
        self.assertIn("`srv02`", output)


if __name__ == "__main__":
    unittest.main()
