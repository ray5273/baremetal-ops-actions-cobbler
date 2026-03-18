#!/usr/bin/env bash
# Cobbler CI 초기화 스크립트
# Docker 컨테이너 내에서 실행: docker exec cobbler bash < scripts/ci/setup-cobbler.sh
set -euo pipefail

echo "=== Cobbler CI 초기화 시작 ==="

# cobblerd가 완전히 준비될 때까지 대기
echo "cobblerd 준비 대기 중..."
for i in $(seq 1 30); do
  if cobbler distro list &>/dev/null; then
    echo "cobblerd 준비 완료"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: cobblerd 시작 시간 초과"
    exit 1
  fi
  sleep 2
done

# 인증: authn_testing 모듈 사용 (모든 credential 수락, CI 전용)
echo "인증 모듈 설정 중..."
if [ -f /etc/cobbler/modules.conf ]; then
  sed -i 's/^module = authn_.*/module = authn_testing/' /etc/cobbler/modules.conf
  # cobblerd 재시작
  if command -v systemctl &>/dev/null; then
    systemctl restart cobblerd 2>/dev/null || true
  elif command -v supervisorctl &>/dev/null; then
    supervisorctl restart cobblerd 2>/dev/null || true
  fi
  # cobblerd가 재시작 완료될 때까지 대기
  echo "cobblerd 재시작 대기 중..."
  for i in $(seq 1 30); do
    if cobbler distro list &>/dev/null; then
      echo "cobblerd 재시작 완료"
      break
    fi
    if [ "$i" -eq 30 ]; then
      echo "ERROR: cobblerd 재시작 시간 초과"
      exit 1
    fi
    sleep 2
  done
fi

# 더미 distro + profile 생성
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
