#!/usr/bin/env bash
set -Eeuo pipefail

# SAHJONY WhatsApp number activator for the existing OpenClaw Linked Device.
# Invariants:
# - never links, unlinks, logs out, scans a QR, or mutates WhatsApp credentials
# - never uses Meta Cloud
# - preserves the existing OpenClaw container and volumes
# - performs at most one bounded host-level Docker restart when the linked channel is not connected
# - never prints the application bridge secret

APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
APP_URL="${APP_URL%/}"
GATEWAY_ID="${SAHJONY_GATEWAY_ID:-hostinger-vps}"
ACCOUNT_ID="${SAHJONY_WHATSAPP_ACCOUNT_ID:-default}"
BUSINESS_NAME="${SAHJONY_WHATSAPP_BUSINESS_NAME:-SAHJONY LLC}"
EXPECTED_NUMBER="${SAHJONY_WHATSAPP_BUSINESS_NUMBER:-+12816628581}"
MODEL="${SAHJONY_REASONING_MODEL:-gpt-5.6-sol}"
OPENCLAW_ROOT="${SAHJONY_OPENCLAW_ROOT:-/opt/sahjony-openclaw}"
STATE_DIR="${SAHJONY_WHATSAPP_ACTIVATION_STATE_DIR:-/var/lib/sahjony-whatsapp-guardian}"
LAST_GOOD="${STATE_DIR}/number-activation-last-good.json"
LOCK_FILE="${STATE_DIR}/number-activation.lock"

mkdir -p "$STATE_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  printf '%s\n' '{"ok":false,"error":"activation_already_running"}'
  exit 75
fi

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

fail() {
  local reason="$1"
  printf '{"ok":false,"gateway_id":"%s","error":"%s"}\n' "$GATEWAY_ID" "$reason"
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker_not_installed"
command -v curl >/dev/null 2>&1 || fail "curl_not_installed"
command -v python3 >/dev/null 2>&1 || fail "python3_not_installed"

if ! docker info >/dev/null 2>&1; then
  log "Docker daemon is not ready; attempting service start only."
  if command -v systemctl >/dev/null 2>&1; then
    systemctl start docker >/dev/null 2>&1 || true
  else
    service docker start >/dev/null 2>&1 || true
  fi
fi
docker info >/dev/null 2>&1 || fail "docker_daemon_unavailable"

find_container() {
  if [[ -n "${OPENCLAW_CONTAINER:-}" ]] && docker inspect "$OPENCLAW_CONTAINER" >/dev/null 2>&1; then
    printf '%s' "$OPENCLAW_CONTAINER"
    return 0
  fi

  local candidate
  candidate="$(docker ps --format '{{.Names}} {{.Image}}' | awk 'BEGIN{IGNORECASE=1} /openclaw/{print $1; exit}')"
  if [[ -z "$candidate" ]]; then
    candidate="$(docker ps -a --format '{{.Names}} {{.Image}}' | awk 'BEGIN{IGNORECASE=1} /openclaw/{print $1; exit}')"
  fi
  [[ -n "$candidate" ]] || return 1
  printf '%s' "$candidate"
}

CONTAINER="$(find_container)" || fail "openclaw_container_not_found"
log "Using existing OpenClaw container: $CONTAINER"

docker update --restart unless-stopped "$CONTAINER" >/dev/null 2>&1 || true
if [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" != "true" ]]; then
  docker start "$CONTAINER" >/dev/null || fail "openclaw_container_failed_to_start"
fi

container_env_value() {
  local key="$1"
  docker inspect "$CONTAINER" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | awk -v k="$key" 'index($0,k"=")==1{sub("^" k "=",""); print; exit}'
}

container_file_env_value() {
  local key="$1"
  docker exec "$CONTAINER" sh -lc '
    key="$1"
    for file in "$HOME/.openclaw/.env" "/root/.openclaw/.env" "/home/node/.openclaw/.env"; do
      [ -r "$file" ] || continue
      value=$(awk -F= -v k="$key" '\''$1==k{sub(/^[^=]*=/,""); gsub(/^['\''"'\'']|['\''"'\'']$/,""); print; exit}'\'' "$file")
      [ -n "$value" ] && { printf "%s" "$value"; exit 0; }
    done
    exit 1
  ' sh "$key" 2>/dev/null || true
}

host_env_value() {
  local key="$1" file="$OPENCLAW_ROOT/.env"
  [[ -r "$file" ]] || return 1
  awk -F= -v k="$key" '$1==k{sub(/^[^=]*=/,""); gsub(/^["'"'"']|["'"'"']$/,""); print; exit}' "$file"
}

BRIDGE_SECRET="${SAHJONY_APP_BRIDGE_SECRET:-}"
[[ -n "$BRIDGE_SECRET" ]] || BRIDGE_SECRET="$(container_env_value SAHJONY_APP_BRIDGE_SECRET)"
[[ -n "$BRIDGE_SECRET" ]] || BRIDGE_SECRET="$(container_file_env_value SAHJONY_APP_BRIDGE_SECRET)"
[[ -n "$BRIDGE_SECRET" ]] || BRIDGE_SECRET="$(host_env_value SAHJONY_APP_BRIDGE_SECRET 2>/dev/null || true)"
[[ ${#BRIDGE_SECRET} -ge 24 ]] || fail "bridge_secret_unavailable"

if [[ -z "${SAHJONY_WHATSAPP_BUSINESS_NUMBER:-}" ]]; then
  discovered_number="$(container_env_value SAHJONY_WHATSAPP_BUSINESS_NUMBER)"
  [[ -n "$discovered_number" ]] || discovered_number="$(container_file_env_value SAHJONY_WHATSAPP_BUSINESS_NUMBER)"
  [[ -n "$discovered_number" ]] || discovered_number="$(host_env_value SAHJONY_WHATSAPP_BUSINESS_NUMBER 2>/dev/null || true)"
  [[ -n "$discovered_number" ]] && EXPECTED_NUMBER="$discovered_number"
fi

compose_cli_available() {
  [[ -s "$OPENCLAW_ROOT/docker-compose.yml" ]] || return 1
  (cd "$OPENCLAW_ROOT" && docker compose config --services 2>/dev/null | grep -qx 'openclaw-cli')
}

run_openclaw_cli() {
  if docker exec "$CONTAINER" sh -lc 'command -v openclaw >/dev/null 2>&1'; then
    docker exec "$CONTAINER" openclaw "$@"
    return
  fi
  if docker exec "$CONTAINER" sh -lc '[ -x "$HOME/.openclaw/bin/openclaw" ]'; then
    docker exec "$CONTAINER" sh -lc 'exec "$HOME/.openclaw/bin/openclaw" "$@"' sh "$@"
    return
  fi
  if docker exec "$CONTAINER" sh -lc '[ -x /root/.openclaw/bin/openclaw ]'; then
    docker exec "$CONTAINER" /root/.openclaw/bin/openclaw "$@"
    return
  fi
  if compose_cli_available; then
    (cd "$OPENCLAW_ROOT" && docker compose run -T --rm --no-deps openclaw-cli "$@")
    return
  fi
  return 127
}

probe_channel() {
  run_openclaw_cli channels status --probe 2>&1
}

is_connected() {
  python3 - "$1" <<'PY'
import re, sys
text = sys.argv[1]
ok = bool(
    re.search(r"WhatsApp[^\n]*\b(connected|ready|active|healthy)\b", text, re.I)
    or re.search(r"\blinked,\s*running,\s*connected\b", text, re.I)
)
raise SystemExit(0 if ok else 1)
PY
}

PROBE_OUTPUT="$(probe_channel || true)"
if ! is_connected "$PROBE_OUTPUT"; then
  log "Existing WhatsApp session is not currently reporting connected; performing one bounded container restart."
  docker restart -t 20 "$CONTAINER" >/dev/null || fail "bounded_container_restart_failed"
  sleep 8
  PROBE_OUTPUT="$(probe_channel || true)"
fi
is_connected "$PROBE_OUTPUT" || fail "linked_whatsapp_session_not_connected_no_relink_attempted"

GATEWAY_VERSION="$(run_openclaw_cli --version 2>/dev/null | tr -d '\r' | head -n1 | head -c 80 || true)"

PAYLOAD="$(python3 - "$GATEWAY_ID" "$ACCOUNT_ID" "$EXPECTED_NUMBER" "$BUSINESS_NAME" "$MODEL" "$GATEWAY_VERSION" <<'PY'
import json, sys
print(json.dumps({
    "gateway_id": sys.argv[1],
    "account_id": sys.argv[2],
    "channel_connected": True,
    "business_number": sys.argv[3],
    "business_name": sys.argv[4],
    "model": sys.argv[5],
    "gateway_version": sys.argv[6] or None,
}, separators=(",", ":"), ensure_ascii=False))
PY
)"

TIMESTAMP="$(date +%s)"
SIGNATURE="$(BRIDGE_SECRET="$BRIDGE_SECRET" TIMESTAMP="$TIMESTAMP" PAYLOAD="$PAYLOAD" python3 - <<'PY'
import hashlib, hmac, os
secret = os.environ["BRIDGE_SECRET"].encode()
msg = (os.environ["TIMESTAMP"] + "." + os.environ["PAYLOAD"]).encode()
print("sha256=" + hmac.new(secret, msg, hashlib.sha256).hexdigest())
PY
)"
unset BRIDGE_SECRET

RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$RESPONSE_FILE"' EXIT
HTTP_CODE="$(curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' \
  -X POST "$APP_URL/whatsapp/openclaw/heartbeat" \
  -H 'Accept: application/json' \
  -H 'Content-Type: application/json' \
  -H "X-SAHJONY-Timestamp: $TIMESTAMP" \
  -H "X-SAHJONY-Signature: $SIGNATURE" \
  --data-binary "$PAYLOAD" || true)"
unset SIGNATURE
[[ "$HTTP_CODE" == "200" ]] || fail "heartbeat_http_${HTTP_CODE}"

HEALTH="$(curl -fsS "$APP_URL/whatsapp/health")" || fail "production_health_unreachable"
VERIFY="$(HEALTH_JSON="$HEALTH" EXPECTED_NUMBER="$EXPECTED_NUMBER" python3 - <<'PY'
import json, os
try:
    h=json.loads(os.environ["HEALTH_JSON"])
except Exception:
    print(json.dumps({"ok":False,"error":"invalid_health_json"}))
    raise SystemExit(2)
node=h.get("hostinger_openclaw") or {}
expected=''.join(c for c in os.environ.get("EXPECTED_NUMBER","") if c.isdigit())
actual=''.join(c for c in str(node.get("business_number") or "") if c.isdigit())
checks={
    "status_ok": h.get("status") == "ok",
    "hostinger_independent_runtime": h.get("hostinger_independent_runtime") is True,
    "send_ready": h.get("send_ready") is True,
    "webhook_ready": h.get("webhook_ready") is True,
    "hostinger_connected": node.get("connected") is True,
    "number_matches": bool(expected and actual and expected == actual),
    "gateway_matches": node.get("gateway_id") == "hostinger-vps",
}
ok=all(checks.values())
print(json.dumps({"ok":ok,"checks":checks,"gateway_id":node.get("gateway_id"),"business_number":node.get("business_number"),"last_seen_at":node.get("last_seen_at")}, separators=(",",":")))
raise SystemExit(0 if ok else 1)
PY
)" || fail "production_activation_verification_failed"

printf '%s\n' "$VERIFY" | tee "$LAST_GOOD"
log "WhatsApp number activation verified for the existing linked session."
