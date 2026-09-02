#!/usr/bin/env bash
set -euo pipefail

APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
LOCAL_GATEWAY_ID="default"
LOCAL_ACCOUNT_ID="default"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
ENV_FILE="$STATE_DIR/.env"
CONFIG_FILE="${OPENCLAW_CONFIG_PATH:-$STATE_DIR/openclaw.json}"
LOG_DIR="$HOME/Library/Logs/openclaw"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: this repair is only for the macOS desktop OpenClaw runtime." >&2
  exit 1
fi

if [[ -x "$STATE_DIR/bin/openclaw" ]]; then
  OPENCLAW_BIN="$STATE_DIR/bin/openclaw"
elif command -v openclaw >/dev/null 2>&1; then
  OPENCLAW_BIN="$(command -v openclaw)"
else
  echo "ERROR: OpenClaw binary not found. Run install-macos.sh first." >&2
  exit 2
fi

mkdir -p "$STATE_DIR" "$LOG_DIR"
chmod 700 "$STATE_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE is missing. The bridge secret cannot be recovered safely from this repair." >&2
  echo "Run: bash openclaw/sahjony-app-bridge/install-macos.sh" >&2
  exit 3
fi

if ! grep -Eq '^SAHJONY_APP_BRIDGE_SECRET=.{24,}$' "$ENV_FILE"; then
  echo "ERROR: SAHJONY_APP_BRIDGE_SECRET is missing/invalid in $ENV_FILE; refusing to rotate it automatically." >&2
  exit 4
fi

BACKUP="$ENV_FILE.backup.local-repair.$(date +%Y%m%d%H%M%S)"
cp "$ENV_FILE" "$BACKUP"
TMP_ENV="$(mktemp "${TMPDIR:-/tmp}/sahjony-openclaw-local-repair.XXXXXX")"
trap 'rm -f "$TMP_ENV"' EXIT
awk '!/^SAHJONY_GATEWAY_ID=|^SAHJONY_WHATSAPP_ACCOUNT_ID=|^OPENCLAW_STATE_DIR=|^OPENCLAW_CONFIG_PATH=/' "$ENV_FILE" > "$TMP_ENV"
{
  cat "$TMP_ENV"
  printf 'SAHJONY_GATEWAY_ID=%s\n' "$LOCAL_GATEWAY_ID"
  printf 'SAHJONY_WHATSAPP_ACCOUNT_ID=%s\n' "$LOCAL_ACCOUNT_ID"
  printf 'OPENCLAW_STATE_DIR=%s\n' "$STATE_DIR"
  printf 'OPENCLAW_CONFIG_PATH=%s\n' "$CONFIG_FILE"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "LOCAL_IDENTITY_REPAIRED=1"
echo "LOCAL_GATEWAY_ID=$LOCAL_GATEWAY_ID"
echo "LOCAL_ACCOUNT_ID=$LOCAL_ACCOUNT_ID"
echo "ENV_BACKUP=$BACKUP"

export OPENCLAW_STATE_DIR="$STATE_DIR"
export OPENCLAW_CONFIG_PATH="$CONFIG_FILE"
export OPENCLAW_BIN="$OPENCLAW_BIN"
export SAHJONY_GATEWAY_ID="$LOCAL_GATEWAY_ID"
export SAHJONY_WHATSAPP_ACCOUNT_ID="$LOCAL_ACCOUNT_ID"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Refresh the reviewed bridge package from the current repository checkout.
"$OPENCLAW_BIN" plugins install "$SCRIPT_DIR" \
  --force \
  --acknowledge-install-policy-warning
"$OPENCLAW_BIN" plugins enable sahjony-app-bridge

"$OPENCLAW_BIN" config set plugins.entries.sahjony-app-bridge.enabled true --strict-json
"$OPENCLAW_BIN" config set plugins.entries.sahjony-app-bridge.config \
  "{\"appUrl\":\"$APP_URL\",\"accountId\":\"$LOCAL_ACCOUNT_ID\",\"gatewayId\":\"$LOCAL_GATEWAY_ID\"}" \
  --strict-json \
  --merge
"$OPENCLAW_BIN" config validate

"$OPENCLAW_BIN" gateway install --force
"$OPENCLAW_BIN" gateway restart

GATEWAY_RPC_READY=0
for _ in {1..12}; do
  if "$OPENCLAW_BIN" gateway status --deep --require-rpc >/dev/null 2>&1; then
    GATEWAY_RPC_READY=1
    break
  fi
  sleep 5
done

echo "GATEWAY_RPC_READY=$GATEWAY_RPC_READY"
if [[ "$GATEWAY_RPC_READY" -ne 1 ]]; then
  echo "ERROR: local OpenClaw gateway did not become RPC-ready." >&2
  exit 5
fi

# Install/refresh the independent health reporter; it does not mutate WhatsApp auth.
bash "$SCRIPT_DIR/install-health-sidecar-macos.sh"

CHANNEL_OUTPUT="$($OPENCLAW_BIN channels status --probe 2>&1 || true)"
printf '%s\n' "$CHANNEL_OUTPUT"

LOCAL_CHANNEL_CONNECTED=0
if printf '%s' "$CHANNEL_OUTPUT" | grep -Eiq 'WhatsApp[^[:cntrl:]]*connected|linked,[[:space:]]*running,[[:space:]]*connected'; then
  LOCAL_CHANNEL_CONNECTED=1
fi
echo "LOCAL_CHANNEL_CONNECTED=$LOCAL_CHANNEL_CONNECTED"

HEALTH_RESPONSE="$(curl --fail --silent --show-error "$APP_URL/whatsapp/health" || true)"
if [[ -z "$HEALTH_RESPONSE" ]]; then
  echo "ERROR: production health endpoint did not respond." >&2
  exit 6
fi

if python3 - "$HEALTH_RESPONSE" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
local = d.get("openclaw_default") or {}
hostinger = d.get("hostinger_openclaw") or {}
print("PRODUCTION_STATUS=" + str(d.get("status")))
print("LOCAL_HEARTBEAT_FRESH=" + str(bool(local.get("heartbeat_fresh"))).lower())
print("LOCAL_CONNECTED=" + str(bool(local.get("connected"))).lower())
print("LOCAL_LAST_SEEN=" + str(local.get("last_seen_at")))
print("HOSTINGER_HEARTBEAT_FRESH=" + str(bool(hostinger.get("heartbeat_fresh"))).lower())
print("HOSTINGER_CONNECTED=" + str(bool(hostinger.get("connected"))).lower())
print("HOSTINGER_MODEL=" + str(hostinger.get("model")))
if local.get("gateway_id") != "default" or local.get("heartbeat_fresh") is not True:
    raise SystemExit(20)
PY
then
  STATUS=0
else
  STATUS=$?
fi

if [[ "$STATUS" -ne 0 ]]; then
  echo "ERROR: the local Mac heartbeat is still not fresh under gateway_id=default." >&2
  echo "Check logs: $LOG_DIR/sahjony-whatsapp-health.log" >&2
  echo "Check errors: $LOG_DIR/sahjony-whatsapp-health.err.log" >&2
  exit "$STATUS"
fi

echo "MAC_LOCAL_CONNECTION_REPAIR=SUCCESS"
echo "NOTE=Hostinger remains the sole production WhatsApp authority; the Mac is diagnostic/fallback only."
