#!/usr/bin/env bash
set -euo pipefail

APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
BUSINESS_NUMBER="${SAHJONY_BUSINESS_NUMBER:-+12816628581}"
BUSINESS_NAME="${SAHJONY_BUSINESS_NAME:-SAHJONY LLC}"
REPO_URL="${SAHJONY_REPO_URL:-https://github.com/SAHJONY/IMPORT-EXPORT--BUSINESS.git}"
ROOT="${SAHJONY_OPENCLAW_ROOT:-/opt/sahjony-openclaw}"
REPO_DIR="$ROOT/repo"
RUNTIME_ENV="$ROOT/runtime.env"
PORT="${OPENCLAW_PORT:-18789}"

[[ "$(id -u)" -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
command -v openclaw >/dev/null 2>&1 || { echo "Native OpenClaw CLI not found" >&2; exit 3; }
command -v git >/dev/null 2>&1 || { echo "git missing" >&2; exit 4; }
command -v openssl >/dev/null 2>&1 || { echo "openssl missing" >&2; exit 4; }

OPENCLAW_BIN="$(command -v openclaw)"
mkdir -p "$ROOT"
chmod 700 "$ROOT"
if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" fetch origin main
  git -C "$REPO_DIR" reset --hard origin/main
else
  rm -rf "$REPO_DIR"
  git clone --depth 1 --branch main "$REPO_URL" "$REPO_DIR"
fi

secret="${SAHJONY_APP_BRIDGE_SECRET:-}"
if [[ -f "$RUNTIME_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$RUNTIME_ENV" || true
  secret="${SAHJONY_APP_BRIDGE_SECRET:-$secret}"
fi
if [[ ! "$secret" =~ ^[0-9a-fA-F]{64}$ ]]; then
  secret="$(openssl rand -hex 32)"
fi
umask 077
cat > "$RUNTIME_ENV" <<EOF
SAHJONY_APP_URL=$APP_URL
SAHJONY_APP_BRIDGE_SECRET=$secret
SAHJONY_BUSINESS_NUMBER=$BUSINESS_NUMBER
SAHJONY_BUSINESS_NAME=$BUSINESS_NAME
EOF
chmod 600 "$RUNTIME_ENV"
export SAHJONY_APP_BRIDGE_SECRET="$secret"

if [[ -n "${VERCEL_TOKEN:-}" ]] && command -v npx >/dev/null 2>&1; then
  printf '%s' "$secret" | npx --yes vercel@59.10.0 env add OPENCLAW_APP_BRIDGE_SECRET production --sensitive --force --yes \
    --token "$VERCEL_TOKEN" --scope "${VERCEL_SCOPE:-juan-gonzalezs-projects-94b6dfe9}" --cwd "$REPO_DIR" >/dev/null || true
  echo "Vercel bridge secret sync attempted (value hidden)."
fi

openclaw plugins install "$REPO_DIR/openclaw/sahjony-app-bridge" --force --acknowledge-install-policy-warning || true
openclaw plugins enable sahjony-app-bridge || true
openclaw config set commands.ownerAllowFrom "[\"whatsapp:${BUSINESS_NUMBER}\"]" --strict-json || true
openclaw config set plugins.entries.sahjony-app-bridge.enabled true --strict-json || true
openclaw config set plugins.entries.sahjony-app-bridge.config \
  "{\"appUrl\":\"${APP_URL}\",\"accountId\":\"default\",\"businessNumber\":\"${BUSINESS_NUMBER}\",\"businessName\":\"${BUSINESS_NAME}\",\"pollIntervalMs\":30000}" \
  --strict-json --merge || true
openclaw config validate

cat > /etc/systemd/system/openclaw-gateway.service <<EOF
[Unit]
Description=OpenClaw Gateway - SAHJONY 24x7
After=network-online.target
Wants=network-online.target
StartLimitBurst=5
StartLimitIntervalSec=60

[Service]
Type=simple
User=root
Environment=HOME=/root
Environment=OPENCLAW_SERVICE_REPAIR_POLICY=external
ExecStart=$OPENCLAW_BIN gateway --port $PORT
Restart=always
RestartSec=5
RestartPreventExitStatus=78
TimeoutStopSec=30
TimeoutStartSec=30
SuccessExitStatus=0 143
OOMPolicy=continue
KillMode=control-group

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now openclaw-gateway.service
sleep 8
systemctl --no-pager --full status openclaw-gateway.service | sed -n '1,18p' || true
curl -fsS --max-time 10 "http://127.0.0.1:${PORT}/" >/dev/null 2>&1 || true

echo "SAHJONY_HOSTINGER_NATIVE_OPENCLAW_24X7_READY=1"
