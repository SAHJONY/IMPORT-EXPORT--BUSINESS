#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/SAHJONY/IMPORT-EXPORT--BUSINESS.git"
INSTALL_ROOT="/opt/sahjony-openclaw"
REPO_DIR="$INSTALL_ROOT/repo"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive

need_pkg(){
  command -v "$1" >/dev/null 2>&1 || return 0
  return 1
}

if ! command -v git >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1 || ! command -v openssl >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y git curl openssl ca-certificates
fi

if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y docker.io
fi

systemctl enable --now docker >/dev/null 2>&1 || true
mkdir -p "$INSTALL_ROOT"
chmod 700 "$INSTALL_ROOT"

if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" fetch origin main
  git -C "$REPO_DIR" reset --hard origin/main
else
  rm -rf "$REPO_DIR"
  git clone --depth 1 --branch main "$REPO_URL" "$REPO_DIR"
fi

chmod +x "$REPO_DIR/openclaw/hostinger-24x7/"*.sh

echo "=== Detecting existing OpenClaw ==="
docker ps -a --format 'name={{.Names}} image={{.Image}} status={{.Status}}' | grep -i openclaw || true

echo "=== Running SAHJONY non-destructive recovery/bootstrap ==="
REPO_DIR="$REPO_DIR" "$REPO_DIR/openclaw/hostinger-24x7/authorization-recovery-agent.sh" || rc=$?
rc="${rc:-0}"

case "$rc" in
  0) echo "SAHJONY_HOSTINGER_RECOVERY=OK" ;;
  10) echo "SAHJONY_HOSTINGER_RECOVERY=CONNECTOR_DETECTED" ;;
  11) echo "SAHJONY_HOSTINGER_RECOVERY=SSH_IDENTITY_DETECTED" ;;
  12) echo "SAHJONY_HOSTINGER_RECOVERY=AUTHORIZATION_REQUIRED" ;;
  20) echo "SAHJONY_HOSTINGER_RECOVERY=BOOTSTRAP_PATH_MISMATCH" ;;
  *) echo "SAHJONY_HOSTINGER_RECOVERY=FAILED code=$rc" ;;
esac

# Always show a safe diagnostic summary.
echo "=== Docker ==="
docker ps --format 'name={{.Names}} image={{.Image}} status={{.Status}} ports={{.Ports}}' || true

echo "=== systemd timers ==="
systemctl list-timers --all --no-pager | grep -E 'sahjony-openclaw-(watchdog|backup)' || true

echo "=== SAHJONY health ==="
curl -fsS --max-time 15 https://www.sahjony.com/whatsapp/health || true
echo

exit "$rc"
