#!/usr/bin/env bash
# Cobbler CI 초기화 스크립트
# Docker 컨테이너 내에서 실행: docker exec cobbler bash /tmp/setup-cobbler.sh
set -euo pipefail

echo "=== Cobbler CI 초기화 시작 ==="

# 진단 정보 출력
echo "--- 진단 정보 ---"
supervisorctl status || true
echo "cobblerd 프로세스 확인:"
ps aux | grep cobblerd || true
echo "포트 확인:"
ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null || true
echo "--- 진단 종료 ---"

# cobblerd가 완전히 준비될 때까지 대기 (XMLRPC 포트 25151)
echo "cobblerd 준비 대기 중..."
for i in $(seq 1 60); do
  if timeout 5 cobbler distro list &>/dev/null; then
    echo "cobblerd 준비 완료"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "ERROR: cobblerd 시작 시간 초과"
    echo "--- 실패 진단 ---"
    supervisorctl status || true
    cat /var/log/cobblerd-stdout.log 2>/dev/null | tail -30 || true
    cat /var/log/cobblerd-stderr.log 2>/dev/null | tail -30 || true
    echo "--- 진단 종료 ---"
    exit 1
  fi
  sleep 2
done

# 더미 distro + profile 생성
# (authentication.configfile 모듈 + users.digest 사용)
PROFILES=("rhel9-x86_64" "rhel8-x86_64" "ubuntu2204-x86_64" "ubuntu2404-x86_64" "rocky9-x86_64")

for PROFILE in "${PROFILES[@]}"; do
  echo "프로파일 생성 중: ${PROFILE}"

  DISTRO_DIR="/var/www/cobbler/distro_mirror/${PROFILE}"
  mkdir -p "${DISTRO_DIR}"

  # 더미 kernel/initrd 파일 생성
  dd if=/dev/zero of="${DISTRO_DIR}/vmlinuz" bs=1 count=1 2>/dev/null
  dd if=/dev/zero of="${DISTRO_DIR}/initrd.img" bs=1 count=1 2>/dev/null

  # distro 생성 (이미 존재하면 skip)
  if ! cobbler distro report --name "${PROFILE}" &>/dev/null; then
    cobbler distro add \
      --name "${PROFILE}" \
      --kernel "${DISTRO_DIR}/vmlinuz" \
      --initrd "${DISTRO_DIR}/initrd.img" \
      --arch x86_64
    echo "  distro 생성 완료: ${PROFILE}"
  else
    echo "  distro 이미 존재: ${PROFILE}"
  fi

  # profile 생성 (이미 존재하면 skip)
  if ! cobbler profile report --name "${PROFILE}" &>/dev/null; then
    cobbler profile add \
      --name "${PROFILE}" \
      --distro "${PROFILE}"
    echo "  profile 생성 완료: ${PROFILE}"
  else
    echo "  profile 이미 존재: ${PROFILE}"
  fi
done

# sync 실행
echo "cobbler sync 실행 중..."
cobbler sync || echo "WARNING: cobbler sync failed (non-fatal in CI)"

echo "=== Cobbler CI 초기화 완료 ==="
echo "생성된 프로파일:"
cobbler profile list
