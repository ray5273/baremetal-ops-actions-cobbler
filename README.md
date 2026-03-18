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

## 클러스터 배치 재배포

클러스터 배포는 `clusters/*.yaml` 정의를 기준으로 여러 서버를 한 번에 또는 롤링 방식으로 재배포합니다.

### 클러스터 정의 예시

```yaml
name: r3-cluster
description: R3 rack application servers
default_profile: rocky9-x86_64
use_efi: true
rolling:
  enabled: true
  batch_size: 1
  pause_between_batches: false
nodes:
  - name: rack01-srv001
  - name: rack01-srv002
    profile_override: ubuntu2404-x86_64
```

### 배포 전 확인 커맨드

```bash
# 정의된 클러스터 목록 확인
python scripts/cluster_manager.py list

# 클러스터 YAML 검증
python scripts/cluster_manager.py validate

# 실제 배포 전에 계획 확인
python scripts/cluster_manager.py show r3-cluster

# GitHub Actions에서 사용하는 JSON 계획 출력
python scripts/cluster_manager.py resolve r3-cluster
```

### GitHub Actions 수동 실행 입력값

- `cluster_name`: 배포할 클러스터 이름
- `profile_override`: 모든 노드에 강제로 적용할 Cobbler profile, 비우면 클러스터 기본값 사용
- `confirm_cluster_name`: 오입력 방지를 위한 확인용 클러스터 이름 재입력

### 워크플로우 동작 순서

1. 클러스터명 재입력 확인
2. `validate_inventory.py`와 `cluster_manager.py validate`로 사전 검증
3. `cluster_manager.py resolve`와 `show --output-format github`로 배포 계획 생성 및 Summary 출력
4. 대상 노드가 Cobbler에 등록되어 있는지 확인
5. 각 노드에 대해 Cobbler profile 설정, netboot 활성화, IPMI PXE 부팅, 전원 재시작 수행
6. 모든 노드의 SSH 복구를 기다린 뒤 netboot 비활성화 및 Cobbler sync 수행
7. 실행 결과를 GitHub Actions Step Summary에 표 형태로 정리

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

# 클러스터 목록 확인
python scripts/cluster_manager.py list

# 클러스터 배포 계획 확인
python scripts/cluster_manager.py show r3-cluster

# 클러스터 배포용 JSON 계획 확인
python scripts/cluster_manager.py resolve r3-cluster
```

## 기술 스택

- **Cobbler 3.3.7**: PXE/DHCP/TFTP 관리 (XML-RPC API)
- **GitHub Actions**: CI/CD 파이프라인
- **Self-hosted Runner**: 관리망 내 실행
- **ipmitool**: BMC/IPMI 전원 제어
- **Python 3.10+**: 스크립트 언어
