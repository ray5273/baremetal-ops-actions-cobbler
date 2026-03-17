# Cobbler + GitHub Actions: Bare-Metal OS 재배포 자동화 구현 플랜

> 이 문서는 Claude Code에 직접 입력하여 프로젝트를 생성하기 위한 구현 명세서입니다.
> 각 Phase를 순서대로 실행하세요.

---

## 프로젝트 개요

- **레포지토리명**: `bare-metal-ops` (새로 생성하는 독립 레포)
- **목적**: GitHub Actions `workflow_dispatch`로 사내 bare-metal 서버의 OS를 Cobbler를 통해 재배포하는 자동화 파이프라인 구축
- **핵심 흐름**: Git PR/수동트리거 → Self-hosted Runner → Cobbler XML-RPC API → IPMI PXE Boot → 설치 완료 확인
- **Cobbler 버전**: 3.x (XML-RPC API at `/cobbler_api`)
- **Runner 환경**: Linux (Ubuntu 22.04+), 관리망에 위치, Cobbler 서버 및 BMC/IPMI 서브넷 접근 가능

---

## 최종 디렉토리 구조

아래 구조를 정확히 생성하세요:

```
bare-metal-ops/
├── README.md
├── requirements.txt
├── .gitignore
├── .github/
│   └── workflows/
│       ├── reprovision.yml          # Phase 1: 수동 트리거 OS 재배포
│       ├── validate-pr.yml          # Phase 2: PR 시 YAML 검증
│       └── manual-sync.yml          # Phase 3: 수동 트리거 Cobbler 동기화
├── inventory/
│   ├── schema.yaml                  # Phase 2: 서버 정의 YAML 스키마
│   └── systems/                     # Phase 2: 서버별 정의 파일
│       ├── _example.yaml            # 예시 (실제 배포 대상 아님)
│       ├── rack01-srv001.yaml
│       ├── rack01-srv002.yaml
│       └── rack02-srv001.yaml
├── profiles/
│   └── _catalog.yaml                # Phase 2: 사용 가능한 OS 프로파일 목록
├── kickstarts/                      # Phase 2: kickstart/preseed 템플릿 (참조용)
│   └── .gitkeep
├── scripts/
│   ├── cobbler_client.py            # Phase 1: Cobbler XML-RPC 클라이언트
│   ├── ipmi_control.py              # Phase 1: IPMI 전원 제어
│   ├── wait_for_ssh.py              # Phase 1: 설치 완료 대기
│   ├── validate_inventory.py        # Phase 2: YAML 스키마 검증
│   ├── cobbler_diff.py              # Phase 3: Git 상태 vs Cobbler 상태 비교
│   └── cobbler_sync.py              # Phase 3: Git → Cobbler 동기화
├── tests/
│   ├── test_cobbler_client.py
│   ├── test_validate_inventory.py
│   └── test_cobbler_diff.py
└── docs/
    ├── SETUP.md                     # Self-hosted runner 설정 가이드
    ├── USAGE.md                     # 사용법 가이드
    └── ARCHITECTURE.md              # 아키텍처 설명
```

---

## Phase 1: Self-hosted Runner + 수동 트리거 재배포

### 목표
`workflow_dispatch`로 서버명과 OS 프로파일을 선택하면, Cobbler에 설정을 반영하고 IPMI로 PXE 부팅하여 OS를 재설치한다.

### 1-1. `scripts/cobbler_client.py` 작성

```
파일: scripts/cobbler_client.py
목적: Cobbler XML-RPC API 래퍼 클래스
의존성: Python 표준 라이브러리만 사용 (xmlrpc.client)

클래스: CobblerClient
- __init__(self, url: str, username: str, password: str)
  - xmlrpc.client.Server(url) 으로 서버 연결
  - self.token = self.server.login(username, password)
  - 연결 실패 시 명확한 에러 메시지 출력

- get_system(self, name: str) -> dict
  - self.server.get_system(name) 호출
  - 시스템이 없으면 None 반환 (예외 처리)

- list_systems(self) -> list
  - self.server.get_systems() 호출

- list_profiles(self) -> list
  - self.server.get_profiles() 호출

- set_system_profile(self, system_name: str, profile: str) -> None
  - get_system_handle → modify_system("profile", profile) → save_system
  - 프로파일이 존재하는지 먼저 확인 (없으면 에러)

- enable_netboot(self, system_name: str) -> None
  - get_system_handle → modify_system("netboot_enabled", True) → save_system

- disable_netboot(self, system_name: str) -> None
  - get_system_handle → modify_system("netboot_enabled", False) → save_system

- sync(self) -> None
  - self.server.sync(self.token) 호출
  - DHCP/TFTP/PXE 설정 재생성

- add_system(self, config: dict) -> None
  - config 딕셔너리로 시스템 생성
  - 필수 키: name, profile, hostname, interfaces (list of dict)
  - 각 interface: name, mac_address, ip_address, netmask, static(bool)
  - gateway는 시스템 레벨에서 설정

- remove_system(self, name: str) -> None
  - self.server.remove_system(name, self.token)

- get_system_status(self, name: str) -> dict
  - get_system_as_rendered로 현재 렌더링된 상태 조회

환경변수:
- COBBLER_URL: Cobbler API URL (예: https://cobbler.internal/cobbler_api)
- COBBLER_USER: 사용자명
- COBBLER_PASS: 비밀번호

CLI 인터페이스 (if __name__ == "__main__"):
  argparse로 서브커맨드 구현
  - cobbler_client.py list-systems
  - cobbler_client.py list-profiles
  - cobbler_client.py get-system <name>
  - cobbler_client.py reprovision <name> <profile>
    → set_system_profile + enable_netboot + sync
  - cobbler_client.py add-system --config <yaml_file>
  - cobbler_client.py remove-system <name>

모든 동작에 로깅 포함 (logging 모듈, INFO 레벨)
에러 시 exit code 1과 명확한 에러 메시지
```

### 1-2. `scripts/ipmi_control.py` 작성

```
파일: scripts/ipmi_control.py
목적: ipmitool 래퍼 (서브프로세스 호출)
의존성: subprocess, shlex

클래스: IPMIController
- __init__(self, bmc_ip: str, username: str, password: str)

- _run_ipmi(self, *args) -> subprocess.CompletedProcess
  - ipmitool -I lanplus -H {bmc_ip} -U {username} -P {password} {args}
  - timeout 30초
  - 실패 시 예외 발생 + stderr 출력

- set_boot_pxe(self, efi: bool = True) -> None
  - chassis bootdev pxe (efi이면 options=efiboot 추가)

- power_cycle(self) -> None
  - power cycle
  - 이미 꺼져있으면 power on

- power_status(self) -> str
  - power status → "on" 또는 "off" 반환

- get_bmc_info(self) -> dict
  - mc info 파싱하여 딕셔너리 반환

CLI 인터페이스:
  - ipmi_control.py status <bmc_ip>
  - ipmi_control.py pxe-boot <bmc_ip> [--efi]
  - ipmi_control.py power-cycle <bmc_ip>

환경변수:
- IPMI_USER
- IPMI_PASS
```

### 1-3. `scripts/wait_for_ssh.py` 작성

```
파일: scripts/wait_for_ssh.py
목적: OS 설치 완료 후 SSH 접속 가능 여부를 폴링하여 확인

함수: wait_for_ssh(host, port=22, timeout_minutes=30, interval_seconds=60) -> bool
  - socket.create_connection((host, port), timeout=5) 로 확인
  - 성공 시 True, 타임아웃 초과 시 False
  - 매 시도마다 로깅: "⏳ Attempt {n}/{max} - {host} not ready yet..."
  - 성공 시: "✅ {host} is reachable via SSH after {n} minutes"
  - 실패 시: "❌ {host} not reachable after {timeout_minutes} minutes"

CLI:
  - wait_for_ssh.py <hostname> [--timeout 30] [--interval 60] [--port 22]
  - exit 0 on success, exit 1 on timeout
```

### 1-4. `.github/workflows/reprovision.yml` 작성

```yaml
파일: .github/workflows/reprovision.yml
목적: 수동 트리거로 단일 서버 OS 재배포

name: "🔄 Server OS Reprovision"

on:
  workflow_dispatch:
    inputs:
      server_name:
        description: "대상 서버 (Cobbler system name)"
        required: true
        type: string
      profile:
        description: "OS 프로파일"
        required: true
        type: choice
        options:
          - rhel9-x86_64
          - rhel8-x86_64
          - ubuntu2204-x86_64
          - ubuntu2404-x86_64
          - rocky9-x86_64
      bmc_ip:
        description: "BMC/IPMI IP 주소"
        required: true
        type: string
      use_efi:
        description: "EFI 부팅 사용"
        required: true
        type: boolean
        default: true
      confirm_server_name:
        description: "⚠️ 서버명을 다시 입력하세요 (확인용)"
        required: true
        type: string

jobs:
  pre-check:
    name: "🔍 사전 검증"
    runs-on: [self-hosted, linux, cobbler-mgmt]
    outputs:
      current_profile: ${{ steps.check.outputs.current_profile }}
    steps:
      - uses: actions/checkout@v4

      - name: 서버명 확인
        # inputs.server_name != inputs.confirm_server_name 이면 실패

      - name: Cobbler 시스템 존재 확인
        id: check
        env: (COBBLER_URL, COBBLER_USER, COBBLER_PASS from secrets)
        # python3 scripts/cobbler_client.py get-system 으로 확인
        # 현재 프로파일을 output으로 내보냄
        # 시스템이 없으면 실패

      - name: 프로파일 존재 확인
        # python3 scripts/cobbler_client.py list-profiles 에서 입력된 profile이 있는지 확인

      - name: 변경 사항 요약 출력
        # "🔄 {server_name}: {current_profile} → {new_profile}" 형태로 출력

  reprovision:
    name: "🚀 OS 재배포"
    needs: pre-check
    runs-on: [self-hosted, linux, cobbler-mgmt]
    environment: bare-metal-prod    # ← GitHub Environment (required reviewers 설정)
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip3 install -r requirements.txt

      - name: Cobbler 프로파일 설정 및 Netboot 활성화
        env: (COBBLER secrets)
        run: python3 scripts/cobbler_client.py reprovision ${{ inputs.server_name }} ${{ inputs.profile }}

      - name: IPMI PXE 부팅 설정 및 전원 재시작
        env: (IPMI secrets)
        run: |
          python3 scripts/ipmi_control.py pxe-boot ${{ inputs.bmc_ip }} ${{ inputs.use_efi && '--efi' || '' }}
          python3 scripts/ipmi_control.py power-cycle ${{ inputs.bmc_ip }}

      - name: OS 설치 완료 대기
        run: python3 scripts/wait_for_ssh.py ${{ inputs.server_name }} --timeout 30

      - name: Netboot 비활성화 (재부팅 루프 방지)
        if: success()
        env: (COBBLER secrets)
        run: |
          python3 -c "
          from scripts.cobbler_client import CobblerClient
          import os
          c = CobblerClient(os.environ['COBBLER_URL'], os.environ['COBBLER_USER'], os.environ['COBBLER_PASS'])
          c.disable_netboot('${{ inputs.server_name }}')
          c.sync()
          print('✅ Netboot disabled, Cobbler synced')
          "

      - name: 배포 결과 요약
        if: always()
        run: |
          echo "## 배포 결과" >> $GITHUB_STEP_SUMMARY
          echo "| 항목 | 값 |" >> $GITHUB_STEP_SUMMARY
          echo "|------|-----|" >> $GITHUB_STEP_SUMMARY
          echo "| 서버 | ${{ inputs.server_name }} |" >> $GITHUB_STEP_SUMMARY
          echo "| 프로파일 | ${{ inputs.profile }} |" >> $GITHUB_STEP_SUMMARY
          echo "| 이전 프로파일 | ${{ needs.pre-check.outputs.current_profile }} |" >> $GITHUB_STEP_SUMMARY
          echo "| 상태 | ${{ job.status }} |" >> $GITHUB_STEP_SUMMARY
          echo "| 실행자 | ${{ github.actor }} |" >> $GITHUB_STEP_SUMMARY
          echo "| 시간 | $(date -u '+%Y-%m-%d %H:%M:%S UTC') |" >> $GITHUB_STEP_SUMMARY
```

### 1-5. 부가 파일들

```
requirements.txt:
  PyYAML>=6.0
  jsonschema>=4.20

.gitignore:
  __pycache__/
  *.pyc
  .env
  .terraform/
  *.tfstate
  *.tfstate.backup
  .terraform.lock.hcl
  venv/
```

---

## Phase 2: 서버 인벤토리 Git 관리 + PR 검증

### 목표
서버 정의를 YAML로 관리하고, PR 시 자동으로 스키마 검증을 수행한다.

### 2-1. `inventory/schema.yaml` 작성

```yaml
파일: inventory/schema.yaml
목적: 서버 정의 YAML의 JSON Schema (YAML 형식으로 작성)

내용:
type: object
required:
  - name
  - profile
  - hostname
  - bmc_ip
  - interfaces
properties:
  name:
    type: string
    pattern: "^[a-z0-9][a-z0-9-]*[a-z0-9]$"
    description: "Cobbler system name (예: rack01-srv001)"
  profile:
    type: string
    description: "Cobbler profile name (예: rhel9-x86_64)"
  hostname:
    type: string
    format: hostname
    description: "FQDN (예: rack01-srv001.ai-center.internal)"
  bmc_ip:
    type: string
    format: ipv4
    description: "BMC/IPMI IP 주소"
  gateway:
    type: string
    format: ipv4
  name_servers:
    type: array
    items:
      type: string
      format: ipv4
    default: ["8.8.8.8", "8.8.4.4"]
  interfaces:
    type: array
    minItems: 1
    items:
      type: object
      required: [name, mac_address, ip_address, netmask]
      properties:
        name:
          type: string
          description: "인터페이스 이름 (예: eth0, ens1f0)"
        mac_address:
          type: string
          pattern: "^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$"
        ip_address:
          type: string
          format: ipv4
        netmask:
          type: string
          format: ipv4
        static:
          type: boolean
          default: true
        interface_type:
          type: string
          enum: [na, bond, bond_slave, bridge, bridge_slave]
          default: na
  tags:
    type: array
    items:
      type: string
    description: "서버 태그 (예: ceph-osd, gpu-node, rack01)"
  boot_loader:
    type: string
    enum: [grub, pxelinux]
    default: grub
  autoinstall:
    type: string
    description: "커스텀 autoinstall 템플릿 (선택)"
  comment:
    type: string
```

### 2-2. `inventory/systems/_example.yaml` 작성

```yaml
파일: inventory/systems/_example.yaml
목적: 예시 서버 정의 (언더스코어 prefix는 배포 대상 제외)

name: rack01-srv001
profile: rhel9-x86_64
hostname: rack01-srv001.ai-center.internal
bmc_ip: "10.0.100.101"
gateway: "10.0.1.1"
name_servers:
  - "10.0.0.53"
  - "8.8.8.8"
interfaces:
  - name: ens1f0
    mac_address: "aa:bb:cc:dd:ee:01"
    ip_address: "10.0.1.101"
    netmask: "255.255.255.0"
    static: true
  - name: ens1f1
    mac_address: "aa:bb:cc:dd:ee:02"
    ip_address: "10.0.2.101"
    netmask: "255.255.255.0"
    static: true
tags:
  - ceph-osd
  - rack01
boot_loader: grub
comment: "Ceph OSD node - 22x NVMe data + 1x NVMe DB/WAL"
```

### 2-3. 나머지 예시 시스템 파일

```
inventory/systems/rack01-srv001.yaml - 위 예시와 동일
inventory/systems/rack01-srv002.yaml - IP/MAC만 다르게 (srv002, .102)
inventory/systems/rack02-srv001.yaml - rack02, 다른 서브넷 (10.0.3.x)
```

### 2-4. `profiles/_catalog.yaml` 작성

```yaml
파일: profiles/_catalog.yaml
목적: 사용 가능한 OS 프로파일 목록 및 메타데이터

profiles:
  - name: rhel9-x86_64
    description: "Red Hat Enterprise Linux 9"
    arch: x86_64
    autoinstall: rhel9-default.ks

  - name: rhel8-x86_64
    description: "Red Hat Enterprise Linux 8"
    arch: x86_64
    autoinstall: rhel8-default.ks

  - name: ubuntu2204-x86_64
    description: "Ubuntu 22.04 LTS (Jammy Jellyfish)"
    arch: x86_64
    autoinstall: ubuntu2204.seed

  - name: ubuntu2404-x86_64
    description: "Ubuntu 24.04 LTS (Noble Numbat)"
    arch: x86_64
    autoinstall: ubuntu2404.seed

  - name: rocky9-x86_64
    description: "Rocky Linux 9"
    arch: x86_64
    autoinstall: rocky9-default.ks
```

### 2-5. `scripts/validate_inventory.py` 작성

```
파일: scripts/validate_inventory.py
목적: inventory/systems/*.yaml 파일들을 schema.yaml 기준으로 검증

의존성: PyYAML, jsonschema

기능:
1. inventory/schema.yaml 로드
2. inventory/systems/*.yaml 파일들 순회 (언더스코어 prefix 파일 제외)
3. 각 파일을 스키마 대비 검증
4. 추가 검증:
   a. name 필드가 파일명(확장자 제외)과 일치하는지
   b. profile이 profiles/_catalog.yaml에 존재하는지
   c. 같은 MAC 주소가 다른 시스템에서 중복되지 않는지
   d. 같은 IP 주소가 다른 시스템에서 중복되지 않는지
   e. BMC IP가 중복되지 않는지
5. 결과 출력:
   - 성공: "✅ {filename} - valid"
   - 실패: "❌ {filename} - {error_message}"
6. 하나라도 실패하면 exit code 1

CLI:
  validate_inventory.py [--systems-dir inventory/systems] [--schema inventory/schema.yaml] [--catalog profiles/_catalog.yaml]
```

### 2-6. `.github/workflows/validate-pr.yml` 작성

```yaml
파일: .github/workflows/validate-pr.yml
목적: PR에서 inventory/profiles/kickstarts/scripts 변경 시 자동 검증

name: "✅ Validate Infrastructure Config"

on:
  pull_request:
    branches: [main]
    paths:
      - "inventory/**"
      - "profiles/**"
      - "kickstarts/**"
      - "scripts/**"

jobs:
  validate:
    name: "📋 YAML 스키마 검증"
    runs-on: [self-hosted, linux, cobbler-mgmt]
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip3 install -r requirements.txt

      - name: Validate inventory
        run: python3 scripts/validate_inventory.py

  diff-preview:
    name: "🔍 Cobbler Diff Preview"
    needs: validate
    runs-on: [self-hosted, linux, cobbler-mgmt]
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip3 install -r requirements.txt

      - name: Generate diff
        id: diff
        env:
          COBBLER_URL: ${{ secrets.COBBLER_API_URL }}
          COBBLER_USER: ${{ secrets.COBBLER_USER }}
          COBBLER_PASS: ${{ secrets.COBBLER_PASS }}
        run: |
          python3 scripts/cobbler_diff.py --output-format github > diff_output.txt
          echo "diff<<EOF" >> $GITHUB_OUTPUT
          cat diff_output.txt >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT

      - name: Post diff as PR comment
        uses: actions/github-script@v7
        with:
          script: |
            const diff = `${{ steps.diff.outputs.diff }}`;
            if (diff.trim()) {
              await github.rest.issues.createComment({
                owner: context.repo.owner,
                repo: context.repo.repo,
                issue_number: context.issue.number,
                body: `## 🔄 Cobbler Sync Plan\n\n\`\`\`\n${diff}\n\`\`\`\n\n⚠️ 이 변경사항을 Cobbler에 반영하려면 merge 후 **Manual Cobbler Sync** 워크플로우를 수동으로 실행하세요.`
              });
            }
```

---

## Phase 3: 수동 Cobbler 동기화

### 목표
workflow_dispatch로 수동 트리거하여 Git의 서버 정의와 Cobbler 상태를 동기화한다.
자동 동기화는 하지 않는다 — bare-metal에 자동 반영은 위험하므로 반드시 사람이 확인 후 실행한다.

### 3-1. `scripts/cobbler_diff.py` 작성

```
파일: scripts/cobbler_diff.py
목적: Git의 YAML 상태와 Cobbler 현재 상태를 비교하여 차이점 출력

입력:
  - inventory/systems/*.yaml (Git 상태, "desired state")
  - Cobbler API로 조회한 현재 시스템들 ("actual state")

비교 로직:
1. Git에서 모든 시스템 정의 로드 (언더스코어 prefix 제외)
2. Cobbler에서 모든 시스템 조회
3. 비교 결과를 3가지로 분류:
   a. CREATE: Git에 있지만 Cobbler에 없는 시스템
   b. UPDATE: 양쪽에 있지만 설정이 다른 시스템
      - 비교 대상 필드: profile, hostname, interfaces(ip, mac, netmask), gateway, name_servers, boot_loader
   c. ORPHAN: Cobbler에 있지만 Git에 없는 시스템 (경고만, 삭제하지 않음)

출력 형식 (--output-format 옵션):
  human (기본):
    🔄 Cobbler Sync Plan
    ─────────────────────
    + rack02-srv005: 신규 등록 (profile: ubuntu2204-x86_64)
    ~ rack01-srv001: profile 변경 (rhel8-x86_64 → rhel9-x86_64)
    ~ rack01-srv002: IP 변경 (10.0.1.102 → 10.0.1.112)
    ⚠ rack03-srv001: Cobbler에 존재하지만 Git에 정의 없음

    요약: 신규 1 | 변경 2 | 미관리 1

  github (PR 코멘트용):
    동일하지만 마크다운 형식

  json:
    {"creates": [...], "updates": [...], "orphans": [...]}

CLI:
  cobbler_diff.py [--systems-dir inventory/systems] [--output-format human|github|json] [--target <system_name>]

환경변수: COBBLER_URL, COBBLER_USER, COBBLER_PASS
변경 없으면 "✅ Git과 Cobbler가 동기화 상태입니다." 출력 + exit 0
변경 있으면 diff 출력 + exit 0 (에러가 아님)
```

### 3-2. `scripts/cobbler_sync.py` 작성

```
파일: scripts/cobbler_sync.py
목적: Git의 YAML 정의를 Cobbler에 반영 (create/update only, delete는 하지 않음)

핵심 원칙:
  - DELETE는 절대 자동으로 하지 않음 (orphan은 경고만)
  - --dry-run 모드 지원 (기본 동작)
  - --apply 플래그가 있을 때만 실제 반영
  - --target 옵션으로 특정 시스템만 동기화 가능

동작:
1. cobbler_diff.py의 로직으로 diff 계산
2. --target이 지정되면 해당 시스템만 필터링
3. CREATE 대상:
   - cobbler_client.add_system(config) 호출
4. UPDATE 대상:
   - 변경된 필드만 modify_system으로 업데이트
   - 주의: 프로파일이 변경되더라도 netboot_enabled는 건드리지 않음
     (실제 재배포는 reprovision.yml 워크플로우로 별도 트리거)
5. 모든 변경 후 cobbler sync 한 번 호출
6. 결과 요약 출력

CLI:
  cobbler_sync.py [--systems-dir inventory/systems] [--dry-run] [--apply] [--target <system_name>]
  기본값은 --dry-run (안전 장치)

환경변수: COBBLER_URL, COBBLER_USER, COBBLER_PASS
```

### 3-3. `.github/workflows/manual-sync.yml` 작성

```yaml
파일: .github/workflows/manual-sync.yml
목적: 수동 트리거로 Git → Cobbler 설정 동기화 (자동 실행 없음)

name: "📡 Manual Cobbler Sync"

on:
  workflow_dispatch:
    inputs:
      mode:
        description: "실행 모드"
        required: true
        type: choice
        options:
          - dry-run (변경사항 확인만)
          - apply (실제 반영)
        default: "dry-run (변경사항 확인만)"
      target:
        description: "특정 시스템만 동기화 (비워두면 전체)"
        required: false
        type: string
        default: ""

jobs:
  validate:
    name: "📋 사전 검증"
    runs-on: [self-hosted, linux, cobbler-mgmt]
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip3 install -r requirements.txt

      - name: Validate inventory YAML
        run: python3 scripts/validate_inventory.py

  diff:
    name: "🔍 변경사항 확인"
    needs: validate
    runs-on: [self-hosted, linux, cobbler-mgmt]
    outputs:
      has_changes: ${{ steps.diff.outputs.has_changes }}
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip3 install -r requirements.txt

      - name: Cobbler Diff
        id: diff
        env:
          COBBLER_URL: ${{ secrets.COBBLER_API_URL }}
          COBBLER_USER: ${{ secrets.COBBLER_USER }}
          COBBLER_PASS: ${{ secrets.COBBLER_PASS }}
        run: |
          TARGET_OPT=""
          if [ -n "${{ inputs.target }}" ]; then
            TARGET_OPT="--target ${{ inputs.target }}"
          fi

          python3 scripts/cobbler_diff.py --output-format human $TARGET_OPT | tee diff_output.txt

          HAS=$(python3 scripts/cobbler_diff.py --output-format json $TARGET_OPT | python3 -c "
          import sys, json
          d = json.load(sys.stdin)
          print('true' if len(d.get('creates',[]))+len(d.get('updates',[]))>0 else 'false')
          ")
          echo "has_changes=$HAS" >> $GITHUB_OUTPUT

      - name: Diff 결과를 Step Summary에 출력
        run: |
          echo "## 🔄 Cobbler Sync Plan" >> $GITHUB_STEP_SUMMARY
          echo '```' >> $GITHUB_STEP_SUMMARY
          cat diff_output.txt >> $GITHUB_STEP_SUMMARY
          echo '```' >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          echo "**모드**: ${{ inputs.mode }}" >> $GITHUB_STEP_SUMMARY
          echo "**대상**: ${{ inputs.target || '전체' }}" >> $GITHUB_STEP_SUMMARY
          echo "**실행자**: ${{ github.actor }}" >> $GITHUB_STEP_SUMMARY
          echo "**시간**: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> $GITHUB_STEP_SUMMARY

  apply:
    name: "🚀 Cobbler 반영"
    needs: diff
    if: contains(inputs.mode, 'apply') && needs.diff.outputs.has_changes == 'true'
    runs-on: [self-hosted, linux, cobbler-mgmt]
    environment: bare-metal-prod    # ← required reviewers 설정으로 이중 확인
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip3 install -r requirements.txt

      - name: Apply 전 최종 diff 확인
        env:
          COBBLER_URL: ${{ secrets.COBBLER_API_URL }}
          COBBLER_USER: ${{ secrets.COBBLER_USER }}
          COBBLER_PASS: ${{ secrets.COBBLER_PASS }}
        run: |
          TARGET_OPT=""
          if [ -n "${{ inputs.target }}" ]; then
            TARGET_OPT="--target ${{ inputs.target }}"
          fi
          echo "=== 아래 변경사항을 Cobbler에 반영합니다 ==="
          python3 scripts/cobbler_sync.py --dry-run $TARGET_OPT

      - name: Cobbler에 변경사항 반영
        env:
          COBBLER_URL: ${{ secrets.COBBLER_API_URL }}
          COBBLER_USER: ${{ secrets.COBBLER_USER }}
          COBBLER_PASS: ${{ secrets.COBBLER_PASS }}
        run: |
          TARGET_OPT=""
          if [ -n "${{ inputs.target }}" ]; then
            TARGET_OPT="--target ${{ inputs.target }}"
          fi
          python3 scripts/cobbler_sync.py --apply $TARGET_OPT

      - name: 반영 후 검증
        env:
          COBBLER_URL: ${{ secrets.COBBLER_API_URL }}
          COBBLER_USER: ${{ secrets.COBBLER_USER }}
          COBBLER_PASS: ${{ secrets.COBBLER_PASS }}
        run: |
          echo "=== 동기화 후 상태 확인 ==="
          python3 scripts/cobbler_diff.py --output-format human

      - name: 결과 요약
        if: always()
        run: |
          echo "## 📡 Cobbler Sync 결과" >> $GITHUB_STEP_SUMMARY
          echo "| 항목 | 값 |" >> $GITHUB_STEP_SUMMARY
          echo "|------|-----|" >> $GITHUB_STEP_SUMMARY
          echo "| 모드 | apply |" >> $GITHUB_STEP_SUMMARY
          echo "| 대상 | ${{ inputs.target || '전체' }} |" >> $GITHUB_STEP_SUMMARY
          echo "| 상태 | ${{ job.status }} |" >> $GITHUB_STEP_SUMMARY
          echo "| 실행자 | ${{ github.actor }} |" >> $GITHUB_STEP_SUMMARY
          echo "| 시간 | $(date -u '+%Y-%m-%d %H:%M:%S UTC') |" >> $GITHUB_STEP_SUMMARY

  skip-apply:
    name: "ℹ️ Apply 건너뜀"
    needs: diff
    if: contains(inputs.mode, 'dry-run') || needs.diff.outputs.has_changes != 'true'
    runs-on: [self-hosted, linux, cobbler-mgmt]
    steps:
      - name: 상태 안내
        run: |
          if [[ "${{ inputs.mode }}" == *"dry-run"* ]]; then
            echo "ℹ️ dry-run 모드로 실행되었습니다. 실제 반영은 되지 않았습니다."
            echo "반영하려면 'apply' 모드로 다시 실행하세요."
          else
            echo "✅ 변경사항이 없습니다. Cobbler가 이미 Git과 동기화 상태입니다."
          fi
```

---

## Phase 4: 테스트

### 4-1. `tests/test_cobbler_client.py`

```
파일: tests/test_cobbler_client.py
목적: CobblerClient 단위 테스트 (XML-RPC 모킹)

테스트 케이스:
- test_login_success: 정상 로그인
- test_login_failure: 잘못된 인증정보
- test_get_system_exists: 존재하는 시스템 조회
- test_get_system_not_found: 없는 시스템 조회 → None
- test_set_system_profile: 프로파일 변경 → modify_system 호출 확인
- test_set_system_profile_invalid: 없는 프로파일 → 에러
- test_enable_netboot: netboot 활성화
- test_sync: sync 호출 확인
- test_add_system: 시스템 추가 (인터페이스 포함)

Mock 사용: unittest.mock.patch로 xmlrpc.client.Server 모킹
```

### 4-2. `tests/test_validate_inventory.py`

```
파일: tests/test_validate_inventory.py
목적: YAML 검증 로직 테스트

테스트 케이스:
- test_valid_system: 정상 YAML 통과
- test_missing_required_field: 필수 필드 누락 → 실패
- test_invalid_mac_format: MAC 주소 형식 오류
- test_invalid_ip_format: IP 형식 오류
- test_duplicate_mac: MAC 중복 감지
- test_duplicate_ip: IP 중복 감지
- test_invalid_profile: 카탈로그에 없는 프로파일
- test_filename_mismatch: 파일명과 name 불일치
- test_underscore_prefix_skipped: _example.yaml 건너뜀
```

### 4-3. `tests/test_cobbler_diff.py`

```
파일: tests/test_cobbler_diff.py
목적: diff 로직 테스트

테스트 케이스:
- test_no_changes: 동일 상태 → 빈 diff
- test_new_system: Git에만 존재 → CREATE
- test_profile_changed: 프로파일 변경 → UPDATE
- test_ip_changed: IP 변경 → UPDATE
- test_orphan_system: Cobbler에만 존재 → ORPHAN (경고)
- test_multiple_changes: 복합 변경
- test_output_format_json: JSON 출력 형식
- test_output_format_github: GitHub 마크다운 출력
```

---

## Phase 5: 문서

### 5-1. `docs/SETUP.md`

```markdown
내용:
1. Self-hosted Runner 설치
   - Ubuntu 22.04+ 서버에 GitHub Actions runner 설치
   - --labels "self-hosted,linux,cobbler-mgmt" 설정
   - --ephemeral 플래그 사용 (보안)
   - systemd 서비스 등록

2. 필수 패키지 설치
   - Python 3.11+
   - ipmitool
   - pip install -r requirements.txt

3. GitHub 설정
   - Repository secrets 등록:
     COBBLER_API_URL, COBBLER_USER, COBBLER_PASS
     IPMI_USER, IPMI_PASS
   - Environment "bare-metal-prod" 생성
   - Required reviewers 설정 (최소 1명)

4. 네트워크 요구사항
   - Runner → GitHub.com (HTTPS 443, outbound only)
   - Runner → Cobbler (HTTPS/HTTP, 내부)
   - Runner → BMC 서브넷 (IPMI 623/UDP)
   - Runner → 서버 SSH (22/TCP, 설치 확인용)

5. 보안 체크리스트
   - Runner는 비root 사용자로 실행
   - Runner가 속한 서브넷에 방화벽 규칙 적용
   - Repository는 private 설정
   - Fork PR에서 self-hosted runner 사용 비활성화
```

### 5-2. `docs/USAGE.md`

```markdown
내용:
1. 서버 OS 재배포 방법
   - GitHub UI → Actions → "Server OS Reprovision" → Run workflow
   - 입력값 설명
   - 승인 프로세스

2. 새 서버 추가 방법
   - inventory/systems/에 YAML 파일 생성
   - _example.yaml 참고
   - PR 생성 → 검증 통과 → 리뷰 → Merge
   - Actions → "Manual Cobbler Sync" → dry-run으로 확인 → apply로 반영

3. 서버 설정 변경 방법
   - YAML 수정 → PR → diff 확인 → Merge
   - Actions → "Manual Cobbler Sync" → dry-run → apply
   - 프로파일 변경은 Cobbler 설정만 바뀜 (실제 OS 재설치는 reprovision 워크플로우로)

4. Cobbler 동기화 워크플로우 사용법
   - dry-run 모드: 변경사항만 확인, Cobbler에 아무것도 반영 안 함
   - apply 모드: 실제 Cobbler에 반영 (GitHub Environment 승인 필요)
   - target 옵션: 특정 서버 하나만 동기화 (예: rack01-srv001)
   - 주의: apply 모드에서도 서버 삭제는 절대 하지 않음 (경고만 출력)

5. 트러블슈팅
   - Cobbler 연결 실패 시
   - IPMI 타임아웃 시
   - SSH 폴링 실패 시
   - PXE 부팅이 안 될 때
```

### 5-3. `docs/ARCHITECTURE.md`

```markdown
내용:
1. 아키텍처 다이어그램 (ASCII)
2. 데이터 흐름 설명
3. 보안 모델
4. 향후 계획 (Terraform 전환, MAAS 마이그레이션 옵션)
```

### 5-4. `README.md`

```markdown
# bare-metal-ops

사내 bare-metal 서버 OS 재배포 자동화 파이프라인

## 주요 기능
- GitHub Actions UI에서 원클릭 OS 재배포
- 서버 인벤토리 Git 관리 (YAML)
- PR 시 자동 검증 및 Cobbler diff 미리보기
- 수동 트리거로 Cobbler 동기화 (dry-run → apply 2단계)
- IPMI/BMC 전원 제어 자동화

## 빠른 시작
→ docs/SETUP.md 참조

## 사용법
→ docs/USAGE.md 참조

## 아키텍처
→ docs/ARCHITECTURE.md 참조

## 워크플로우 목록
| 워크플로우 | 트리거 | 역할 |
|---|---|---|
| `reprovision.yml` | 수동 | 서버 1대 OS 재설치 (IPMI 재부팅까지) |
| `validate-pr.yml` | PR 자동 | YAML 검증 + diff 미리보기 |
| `manual-sync.yml` | 수동 | Git → Cobbler 설정 동기화 (OS 재설치 없음) |
```

---

## 구현 순서 요약

Claude Code에서 아래 순서로 작업하세요:

1. 디렉토리 구조 전체 생성
2. `requirements.txt`, `.gitignore` 생성
3. `scripts/cobbler_client.py` 구현 (가장 핵심)
4. `scripts/ipmi_control.py` 구현
5. `scripts/wait_for_ssh.py` 구현
6. `.github/workflows/reprovision.yml` 작성
7. `inventory/schema.yaml` + 예시 시스템 YAML 작성
8. `profiles/_catalog.yaml` 작성
9. `scripts/validate_inventory.py` 구현
10. `.github/workflows/validate-pr.yml` 작성
11. `scripts/cobbler_diff.py` 구현
12. `scripts/cobbler_sync.py` 구현
13. `.github/workflows/manual-sync.yml` 작성
14. 테스트 파일 3개 작성
15. 문서 4개 작성 (SETUP, USAGE, ARCHITECTURE, README)

각 스크립트는 반드시:
- docstring 포함
- type hints 사용
- logging 모듈로 로깅
- argparse로 CLI 인터페이스
- 에러 시 명확한 메시지 + exit code 1
- 한글 주석/출력 메시지 사용

---

## 주의사항

- XML-RPC 호출 시 SSL 검증 비활성화 옵션 포함 (사내 self-signed cert 대응)
  - `ssl._create_unverified_context()` 사용하되 환경변수 `COBBLER_INSECURE=true` 일 때만
- Cobbler 비밀번호는 절대 로그에 출력하지 않음
- IPMI 비밀번호도 마찬가지
- 모든 외부 호출(xmlrpc, subprocess)에 timeout 설정
- GitHub Actions의 secrets는 워크플로우에서 env로만 전달, 절대 로그 출력 안 함