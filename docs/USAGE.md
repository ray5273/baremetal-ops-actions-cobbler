# 사용법 가이드

## 1. 서버 OS 재배포

1. GitHub UI > Actions > **"Server OS Reprovision"** > **Run workflow**
2. 입력값:
   - `server_name`: Cobbler 시스템 이름 (예: `rack01-srv001`)
   - `profile`: OS 프로파일 선택 (예: `rhel9-x86_64`)
   - `bmc_ip`: BMC/IPMI IP 주소 (예: `10.0.100.101`)
   - `use_efi`: EFI 부팅 사용 여부
   - `confirm_server_name`: 서버명 재입력 (안전 확인)
3. `pre-check` 잡에서 시스템/프로파일 존재 여부 확인
4. `bare-metal-prod` 환경의 Required Reviewer가 승인
5. Cobbler 설정 반영 → IPMI PXE 부팅 → 전원 재시작 → SSH 대기
6. 설치 완료 후 Netboot 자동 비활성화

## 2. 클러스터 배치 배포

여러 서버를 묶어 한번에 OS를 재배포합니다.

### 클러스터 정의

`clusters/` 디렉토리에 클러스터 YAML을 작성합니다:

```yaml
# clusters/r3-cluster.yaml
name: r3-cluster
description: "Rack 3 Ceph OSD 클러스터"
default_profile: rhel9-x86_64
use_efi: true
rolling:
  enabled: true
  batch_size: 1
  pause_between_batches: false
nodes:
  - name: rack01-srv001
  - name: rack01-srv002
tags:
  - rack3
  - production
```

### 사용 가능한 클러스터

| 클러스터 | 설명 | 노드 수 | 기본 프로파일 | 전략 |
|----------|------|---------|-------------|------|
| `r3-cluster` | Rack 3 Ceph OSD | 2 | rhel9-x86_64 | 롤링 (1개씩) |
| `r4-cluster` | Rack 4 GPU 컴퓨트 | 1 | ubuntu2204-x86_64 | 전체 동시 |
| `r6-1-cluster` | Rack 6-1 하이브리드 | 3 | rocky9-x86_64 | 롤링 (2개씩) |

### 클러스터 배포 실행

1. GitHub UI > Actions > **"Cluster Batch Reprovision"** > **Run workflow**
2. 입력값:
   - `cluster_name`: 배포할 클러스터 선택 (예: `r3-cluster`)
   - `profile_override`: 프로파일 강제 지정 (비워두면 클러스터 기본값)
   - `confirm_cluster_name`: 클러스터명 재입력 (안전 확인)
3. `pre-check` 잡에서 클러스터/노드 검증 및 배포 계획 생성
4. `bare-metal-prod` 환경의 Required Reviewer가 승인
5. 클러스터 전체 노드를 배치 단위로 순차 배포:
   - Cobbler 프로파일 설정 + Netboot 활성화
   - IPMI PXE 부팅 + 전원 재시작
   - SSH 대기 (최대 30분/노드)
   - Netboot 비활성화

### 롤링 배포 vs 전체 동시 배포

- **전체 동시** (`rolling.enabled: false`): 모든 노드를 한번에 PXE 트리거
- **롤링** (`rolling.enabled: true`): `batch_size`개씩 나눠서 순차 배포

### 로컬에서 배포 계획 확인

```bash
# 클러스터 목록
python scripts/cluster_manager.py list

# 특정 클러스터 배포 계획
python scripts/cluster_manager.py show r3-cluster

# JSON 형식 (스크립트 연동용)
python scripts/cluster_manager.py show r6-1-cluster --output-format json
```

## 3. 새 서버 추가

1. `inventory/systems/`에 YAML 파일 생성

```yaml
# inventory/systems/rack01-srv003.yaml
name: rack01-srv003
profile: rhel9-x86_64
hostname: rack01-srv003.ai-center.internal
bmc_ip: "10.0.100.103"
gateway: "10.0.1.1"
name_servers:
  - "10.0.0.53"
  - "8.8.8.8"
interfaces:
  - name: ens1f0
    mac_address: "aa:bb:cc:dd:ee:03"
    ip_address: "10.0.1.103"
    netmask: "255.255.255.0"
    static: true
tags:
  - ceph-osd
  - rack01
boot_loader: grub
```

2. PR 생성 → `validate-pr.yml`이 자동 검증 + diff 미리보기
3. 리뷰 → Merge
4. Actions > **"Manual Cobbler Sync"** > `dry-run`으로 확인
5. 확인 후 `apply`로 실제 반영

## 4. 서버 설정 변경

1. 해당 서버의 YAML 파일 수정 (예: 프로파일 변경)
2. PR 생성 → 자동 검증 + diff 미리보기
3. 리뷰 → Merge
4. Actions > **"Manual Cobbler Sync"** > `dry-run` → `apply`

> **주의**: 프로파일 변경은 Cobbler 설정만 바뀝니다. 실제 OS 재설치는 별도로 **"Server OS Reprovision"** 워크플로우를 실행해야 합니다.

## 5. Cobbler 동기화 워크플로우 사용법

### dry-run 모드
변경사항만 확인하고 Cobbler에 아무것도 반영하지 않습니다.

### apply 모드
실제 Cobbler에 반영합니다. GitHub Environment 승인이 필요합니다.

### target 옵션
특정 서버 하나만 동기화합니다 (예: `rack01-srv001`).

> **주의**: apply 모드에서도 서버 삭제는 절대 하지 않습니다. Cobbler에만 존재하는 미관리 시스템은 경고만 출력됩니다.

## 6. 트러블슈팅

### Cobbler 연결 실패

- `COBBLER_URL` 시크릿이 올바른지 확인
- Runner에서 Cobbler 서버에 네트워크 접근 가능한지 확인
- Self-signed 인증서인 경우 `COBBLER_INSECURE=true` 환경변수 설정

### IPMI 타임아웃

- BMC IP가 올바른지 확인
- Runner에서 BMC 서브넷에 UDP 623 포트 접근 가능한지 확인
- `ipmitool` 패키지가 설치되어 있는지 확인

### SSH 폴링 실패

- 기본 타임아웃은 30분, 필요시 `--timeout` 조정
- 서버의 SSH 서비스가 설치 후 자동 시작되는지 확인
- 방화벽에서 SSH 포트(22) 허용 여부 확인

### PXE 부팅이 안 될 때

- Cobbler sync가 정상 완료되었는지 확인
- DHCP/TFTP 서비스 상태 확인
- EFI/BIOS 부팅 모드가 올바른지 확인
- 서버의 NIC가 PXE 부팅을 지원하는지 확인
