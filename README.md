# bare-metal-ops

사내 bare-metal 서버 OS 재배포 자동화 파이프라인

## 주요 기능

- GitHub Actions UI에서 원클릭 OS 재배포
- **클러스터 단위 배치 배포** (여러 서버를 묶어서 한번에 재배포)
- 서버 인벤토리 Git 관리 (YAML)
- PR 시 자동 검증 및 Cobbler diff 미리보기
- 수동 트리거로 Cobbler 동기화 (dry-run / apply 2단계)
- IPMI/BMC 전원 제어 자동화
- 롤링 배포 지원 (배치 크기 조절 가능)

## 빠른 시작

> [docs/SETUP.md](docs/SETUP.md) 참조

## 사용법

> [docs/USAGE.md](docs/USAGE.md) 참조

## 아키텍처

> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 참조

## 워크플로우 목록

| 워크플로우 | 트리거 | 역할 |
|---|---|---|
| `reprovision.yml` | 수동 | 서버 1대 OS 재설치 (IPMI 재부팅까지) |
| `cluster-reprovision.yml` | 수동 | **클러스터 단위 배치 OS 재설치** |
| `validate-pr.yml` | PR 자동 | YAML 검증 + diff 미리보기 |
| `manual-sync.yml` | 수동 | Git -> Cobbler 설정 동기화 (OS 재설치 없음) |
| `ci-test.yml` | Push/PR | 단위 테스트 + lint + YAML 검증 |

## 로컬 테스트

```bash
# 의존성 설치
pip install -r requirements.txt
pip install pytest pytest-cov

# 단위 테스트 실행
python -m pytest tests/ -v

# 인벤토리 검증
python scripts/validate_inventory.py

# 클러스터 검증
python scripts/cluster_manager.py validate

# 클러스터 배포 계획 확인
python scripts/cluster_manager.py show r3-cluster
```

## 기술 스택

- **Cobbler 3.3.7**: PXE/DHCP/TFTP 관리 (XML-RPC API)
- **GitHub Actions**: CI/CD 파이프라인
- **Self-hosted Runner**: 관리망 내 실행
- **ipmitool**: BMC/IPMI 전원 제어
- **Python 3.10+**: 스크립트 언어
