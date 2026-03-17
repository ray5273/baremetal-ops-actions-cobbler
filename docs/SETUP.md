# Self-hosted Runner 설정 가이드

## 1. Self-hosted Runner 설치

Ubuntu 22.04+ 서버에 GitHub Actions runner를 설치합니다.

```bash
# Runner 사용자 생성
sudo useradd -m -s /bin/bash github-runner
sudo su - github-runner

# GitHub Actions runner 다운로드 (최신 버전 확인: https://github.com/actions/runner/releases)
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64-2.311.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.311.0/actions-runner-linux-x64-2.311.0.tar.gz
tar xzf ./actions-runner-linux-x64-2.311.0.tar.gz

# Runner 등록 (labels 설정 중요)
./config.sh \
  --url https://github.com/<org>/<repo> \
  --token <REGISTRATION_TOKEN> \
  --labels "self-hosted,linux,cobbler-mgmt" \
  --name "cobbler-mgmt-runner" \
  --work "_work"

# systemd 서비스 등록
sudo ./svc.sh install github-runner
sudo ./svc.sh start
```

## 2. 필수 패키지 설치

```bash
# Python 3.11+
sudo apt update
sudo apt install -y python3.11 python3-pip

# ipmitool
sudo apt install -y ipmitool

# Python 의존성
pip3 install -r requirements.txt
```

## 3. GitHub 설정

### Repository Secrets 등록

Settings > Secrets and variables > Actions에서 다음 시크릿을 등록합니다:

| Secret | 설명 | 예시 |
|--------|------|------|
| `COBBLER_API_URL` | Cobbler XML-RPC API URL | `https://cobbler.internal/cobbler_api` |
| `COBBLER_USER` | Cobbler 사용자명 | `admin` |
| `COBBLER_PASS` | Cobbler 비밀번호 | `****` |
| `IPMI_USER` | IPMI 사용자명 | `admin` |
| `IPMI_PASS` | IPMI 비밀번호 | `****` |

### Environment 설정

Settings > Environments에서 `bare-metal-prod` 환경을 생성합니다:

- **Required reviewers**: 최소 1명 설정 (OS 재배포 승인 필요)
- **Wait timer**: 필요 시 대기 시간 설정

## 4. 네트워크 요구사항

| 출발 | 도착 | 프로토콜/포트 | 용도 |
|------|------|---------------|------|
| Runner | GitHub.com | HTTPS 443 (outbound) | Actions 통신 |
| Runner | Cobbler 서버 | HTTPS/HTTP (내부) | XML-RPC API |
| Runner | BMC 서브넷 | IPMI 623/UDP | 전원 제어 |
| Runner | 서버 SSH | 22/TCP | 설치 완료 확인 |

## 5. 보안 체크리스트

- [ ] Runner는 비root 사용자(`github-runner`)로 실행
- [ ] Runner가 속한 서브넷에 방화벽 규칙 적용
- [ ] Repository는 private 설정
- [ ] Fork PR에서 self-hosted runner 사용 비활성화
  - Settings > Actions > Fork pull request workflows
- [ ] Self-signed 인증서 사용 시 `COBBLER_INSECURE=true` 환경변수 설정
- [ ] IPMI/Cobbler 비밀번호는 GitHub Secrets로만 관리
