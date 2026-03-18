# 아키텍처 설명

## 1. 아키텍처 다이어그램

```
                    ┌──────────────────────────────────┐
                    │          GitHub.com               │
                    │  ┌────────────────────────────┐   │
                    │  │  bare-metal-ops Repository  │   │
                    │  │                            │   │
                    │  │  inventory/systems/*.yaml  │   │
                    │  │  (Desired State)           │   │
                    │  └──────────┬─────────────────┘   │
                    │             │                      │
                    │  ┌──────────▼─────────────────┐   │
                    │  │  GitHub Actions Workflows   │   │
                    │  │  - reprovision.yml          │   │
                    │  │  - cluster-reprovision.yml  │   │
                    │  │  - validate-pr.yml          │   │
                    │  │  - manual-sync.yml          │   │
                    │  │  - ci-test.yml              │   │
                    │  └──────────┬─────────────────┘   │
                    └─────────────┼──────────────────────┘
                                  │ HTTPS (443)
                    ┌─────────────▼──────────────────────┐
                    │     Self-hosted Runner              │
                    │     (Ubuntu 22.04, 관리망)           │
                    │                                     │
                    │  scripts/cobbler_client.py ─────┐   │
                    │  scripts/ipmi_control.py ───┐   │   │
                    │  scripts/wait_for_ssh.py ┐  │   │   │
                    └──────────────────────────┼──┼───┼───┘
                                               │  │   │
                              SSH (22/TCP) ────┘  │   │
                              IPMI (623/UDP) ─────┘   │
                              XML-RPC (HTTPS) ────────┘
                                               │  │   │
                    ┌──────────────────────────┼──┼───┼───┐
                    │     내부 관리 네트워크      │  │   │   │
                    │                          │  │   │   │
                    │  ┌───────────────────┐   │  │   │   │
                    │  │   Cobbler 서버     │◄──┼──┼───┘   │
                    │  │   (3.3.7)         │   │  │       │
                    │  │   DHCP/TFTP/PXE   │   │  │       │
                    │  └───────────────────┘   │  │       │
                    │                          │  │       │
                    │  ┌───────────────────┐   │  │       │
                    │  │   BMC/IPMI        │◄──┼──┘       │
                    │  │   (각 서버)        │   │          │
                    │  └────────┬──────────┘   │          │
                    │           │               │          │
                    │  ┌────────▼──────────┐   │          │
                    │  │   Bare-Metal 서버  │◄──┘          │
                    │  │   (PXE Boot)      │              │
                    │  └───────────────────┘              │
                    └─────────────────────────────────────┘
```

## 2. 데이터 흐름

### OS 재배포 (reprovision.yml)

1. 운영자가 GitHub UI에서 `workflow_dispatch` 트리거
2. 서버명 이중 확인 (typo 방지)
3. Cobbler API로 시스템/프로파일 존재 확인
4. GitHub Environment `bare-metal-prod` 승인 대기
5. Cobbler: 프로파일 설정 + netboot 활성화 + sync
6. IPMI: PXE 부팅 설정 + 전원 재시작
7. SSH 폴링으로 설치 완료 대기 (최대 30분)
8. 완료 후 netboot 비활성화 (재부팅 루프 방지)

### 클러스터 배치 배포 (cluster-reprovision.yml)

1. 운영자가 GitHub UI에서 클러스터 선택 후 `workflow_dispatch` 트리거
2. 클러스터명 이중 확인 (typo 방지)
3. `cluster_manager.py`가 클러스터 YAML을 파싱하여 배포 계획 생성
4. 각 노드별 최종 프로파일 결정 (profile_override > default_profile)
5. 롤링 모드: batch_size 단위로 순차 배포
6. 배치 내 모든 노드: Cobbler 설정 → IPMI PXE 부팅 → 전원 재시작
7. 모든 노드 SSH 대기 후 netboot 비활성화

### 설정 동기화 (manual-sync.yml)

1. 운영자가 inventory YAML 수정 → PR → 리뷰 → Merge
2. 수동으로 `manual-sync.yml` 트리거
3. dry-run: Git과 Cobbler 상태 비교 (CREATE/UPDATE/ORPHAN)
4. apply: 실제 Cobbler에 반영 (삭제는 하지 않음)

## 3. 보안 모델

- **GitOps 원칙**: Git이 Single Source of Truth
- **수동 반영**: 자동 sync 없음, 반드시 사람이 트리거
- **이중 확인**: reprovision 시 서버명 재입력 + Environment 승인
- **삭제 방지**: sync에서 시스템 삭제 절대 불가 (orphan 경고만)
- **비밀번호 보호**: GitHub Secrets, 로그 출력 없음
- **네트워크 격리**: Runner는 관리망에 위치, 외부 접근 불가

## 4. 클러스터 아키텍처

```
clusters/*.yaml          inventory/systems/*.yaml
    │                          │
    ▼                          ▼
cluster_manager.py ──────► resolve_cluster_nodes()
    │                          │
    ▼                          ▼
 배포 계획 생성            노드별 bmc_ip, profile 조회
    │
    ▼
 batches[][] ──────► cluster-reprovision.yml
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
          Cobbler     IPMI      SSH 대기
          설정        PXE+재시작  (30분)
```

### 클러스터 정의 구조

- `clusters/*.yaml`: 클러스터 단위 서버 그룹 정의
- `clusters/schema.yaml`: 클러스터 YAML 검증 스키마
- 노드는 `inventory/systems/`에 정의된 서버를 참조
- `profile_override`로 노드별 OS 프로파일 개별 지정 가능

## 5. 향후 계획

- **Terraform Provider**: Cobbler Terraform Provider로 마이그레이션 검토
- **MAAS**: Canonical MAAS 마이그레이션 옵션 평가
- **Webhook 통합**: Cobbler 이벤트를 Slack/Teams로 알림
- **대시보드**: 서버 상태 실시간 모니터링 대시보드
- **클러스터 상태 추적**: 배포 히스토리 및 노드별 상태 대시보드
- **배치 간 수동 승인**: 롤링 배포 시 배치 사이에 수동 확인 단계 추가
