#!/usr/bin/env bash
set -euo pipefail

# SAHJONY WhatsApp 24/7 Guardian — Hostinger/OpenClaw only.
# Hostinger-local runtime is authoritative; public health is secondary evidence.
# Repairs only reversible runtime state and never bypasses WhatsApp pairing/2FA/auth.
# When the local linked session is healthy, publish the signed Hostinger heartbeat
# expected by the application. The bridge secret is discovered locally and is never
# printed or persisted by this script.

LOCK=/run/lock/sahjony-whatsapp-guardian.lock
STATE_DIR=/var/lib/sahjony-whatsapp-guardian
LOG=/var/log/sahjony-whatsapp-guardian.log
RESTART_STAMP="$STATE_DIR/last-restart"
RESTART_COOLDOWN="${SAHJONY_RESTART_COOLDOWN_SECONDS:-300}"
APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
APP_URL="${APP_URL%/}"
GATEWAY_ID="${SAHJONY_GATEWAY_ID:-hostinger-vps}"
ACCOUNT_ID="${SAHJONY_WHATSAPP_ACCOUNT_ID:-default}"
BUSINESS_NAME="${SAHJONY_WHATSAPP_BUSINESS_NAME:-SAHJONY LLC}"
BUSINESS_NUMBER="${SAHJONY_WHATSAPP_BUSINESS_NUMBER:-+12816628581}"
MODEL="${SAHJONY_REASONING_MODEL:-gpt-5.6-sol}"
OPENCLAW_ROOT="${SAHJONY_OPENCLAW_ROOT:-/opt/sahjony-openclaw}"
mkdir -p "$STATE_DIR" "$(dirname "$LOCK")"
exec 9>"$LOCK"
flock -n 9 || exit 0
exec >>"$LOG" 2>&1
printf '\n[%s] guardian start\n' "$(date -Is)"

fail(){ echo "GUARDIAN_FAIL=$*"; exit 1; }
command -v docker >/dev/null 2>&1 || fail docker_missing
command -v curl >/dev/null 2>&1 || fail curl_missing
command -v python3 >/dev/null 2>&1 || fail python3_missing
systemctl is-active --quiet docker || { systemctl enable --now docker || fail docker_start_failed; }

mapfile -t IDS < <(docker ps -aq | while read -r id; do
  meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}' 2>/dev/null || true)"
  grep -Eqi 'openclaw|claw' <<<"$meta" && echo "$id"
done)
((${#IDS[@]})) || fail openclaw_container_missing

run_openclaw(){
  local id="$1"; shift
  if docker exec "$id" sh -lc 'command -v openclaw >/dev/null 2>&1'; then
    docker exec "$id" openclaw "$@"
    return
  fi
  if docker exec "$id" sh -lc '[ -x "$HOME/.openclaw/bin/openclaw" ]'; then
    docker exec "$id" sh -lc 'exec "$HOME/.openclaw/bin/openclaw" "$@"' sh "$@"
    return
  fi
  if docker exec "$id" sh -lc '[ -x /root/.openclaw/bin/openclaw ]'; then
    docker exec "$id" /root/.openclaw/bin/openclaw "$@"
    return
  fi
  return 127
}

probe_ready(){
  local id="$1" probe
  probe="$(run_openclaw "$id" channels status --probe 2>&1 || true)"
  printf '%s\n' "$probe"
  grep -Eqi 'whatsapp.*(connected|ready|active|healthy|ok)|(connected|ready|active|healthy).*whatsapp|linked,[[:space:]]*running,[[:space:]]*connected' <<<"$probe"
}

healthy=false
ACTIVE_ID=''
for id in "${IDS[@]}"; do
  docker update --restart unless-stopped "$id" >/dev/null || true
  status="$(docker inspect "$id" --format '{{.State.Status}}' 2>/dev/null || true)"
  [[ "$status" == running ]] || docker start "$id" >/dev/null || true
  name="$(docker inspect "$id" --format '{{.Name}}' 2>/dev/null | sed 's#^/##')"
  echo "OPENCLAW_CONTAINER=$name status=$(docker inspect "$id" --format '{{.State.Status}}') restart=$(docker inspect "$id" --format '{{.HostConfig.RestartPolicy.Name}}')"
  if probe_ready "$id"; then healthy=true; ACTIVE_ID="$id"; break; fi
done

if [[ "$healthy" != true ]]; then
  echo OPENCLAW_WHATSAPP_PROBE_FAILED=1
  now="$(date +%s)"; last=0
  [[ -f "$RESTART_STAMP" ]] && last="$(cat "$RESTART_STAMP" 2>/dev/null || echo 0)"
  if (( now - last >= RESTART_COOLDOWN )); then
    echo "OPENCLAW_RESTART_ALLOWED cooldown=${RESTART_COOLDOWN}s"
    printf '%s\n' "$now" > "$RESTART_STAMP"
    for id in "${IDS[@]}"; do docker restart "$id" >/dev/null || true; done
    sleep 20
    for id in "${IDS[@]}"; do
      if probe_ready "$id"; then healthy=true; ACTIVE_ID="$id"; break; fi
    done
  else
    echo "OPENCLAW_RESTART_SUPPRESSED cooldown=${RESTART_COOLDOWN}s age=$((now-last))s"
  fi
fi

if [[ "$healthy" == true ]]; then
  date -Is > "$STATE_DIR/last-good"
  echo SAHJONY_HOSTINGER_LOCAL_RUNTIME=READY
else
  echo SAHJONY_HOSTINGER_LOCAL_RUNTIME=DEGRADED
  exit 2
fi

container_env_value(){
  local key="$1"
  docker inspect "$ACTIVE_ID" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | awk -v k="$key" 'index($0,k"=")==1{sub("^" k "=",""); print; exit}'
}

container_file_env_value(){
  local key="$1"
  docker exec "$ACTIVE_ID" sh -lc '
    key="$1"
    for file in "$HOME/.openclaw/.env" "/root/.openclaw/.env" "/home/node/.openclaw/.env"; do
      [ -r "$file" ] || continue
      value=$(awk -F= -v k="$key" '\''$1==k{sub(/^[^=]*=/,""); gsub(/^["'\''\'']|["'\''\'']$/,""); print; exit}'\'' "$file")
      [ -n "$value" ] && { printf "%s" "$value"; exit 0; }
    done
    exit 1
  ' sh "$key" 2>/dev/null || true
}

host_env_value(){
  local key="$1" file="$OPENCLAW_ROOT/.env"
  [[ -r "$file" ]] || return 1
  awk -F= -v k="$key" '$1==k{sub(/^[^=]*=/,""); gsub(/^["'"'"']|["'"'"']$/,""); print; exit}' "$file"
}

BRIDGE_SECRET="${OPENCLAW_APP_BRIDGE_SECRET:-${SAHJONY_APP_BRIDGE_SECRET:-}}"
if [[ -z "$BRIDGE_SECRET" ]]; then
  for key in OPENCLAW_APP_BRIDGE_SECRET SAHJONY_APP_BRIDGE_SECRET; do
    BRIDGE_SECRET="$(container_env_value "$key")"
    [[ -n "$BRIDGE_SECRET" ]] && break
    BRIDGE_SECRET="$(container_file_env_value "$key")"
    [[ -n "$BRIDGE_SECRET" ]] && break
    BRIDGE_SECRET="$(host_env_value "$key" 2>/dev/null || true)"
    [[ -n "$BRIDGE_SECRET" ]] && break
  done
fi
[[ ${#BRIDGE_SECRET} -ge 24 ]] || fail bridge_secret_unavailable

for key in SAHJONY_WHATSAPP_BUSINESS_NUMBER WHATSAPP_BUSINESS_NUMBER; do
  discovered="$(container_env_value "$key")"
  [[ -n "$discovered" ]] || discovered="$(container_file_env_value "$key")"
  [[ -n "$discovered" ]] || discovered="$(host_env_value "$key" 2>/dev/null || true)"
  if [[ -n "$discovered" ]]; then BUSINESS_NUMBER="$discovered"; break; fi
done

GATEWAY_VERSION="$(run_openclaw "$ACTIVE_ID" --version 2>/dev/null | tr -d '\r' | head -n1 | head -c 80 || true)"
PAYLOAD="$(python3 - "$GATEWAY_ID" "$ACCOUNT_ID" "$BUSINESS_NUMBER" "$BUSINESS_NAME" "$MODEL" "$GATEWAY_VERSION" <<'PY'
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
secret=os.environ["BRIDGE_SECRET"].encode()
msg=(os.environ["TIMESTAMP"]+"."+os.environ["PAYLOAD"]).encode()
print("sha256="+hmac.new(secret,msg,hashlib.sha256).hexdigest())
PY
)"
unset BRIDGE_SECRET

response="$STATE_DIR/heartbeat-response.tmp"
code="$(curl -sS -o "$response" -w '%{http_code}' -X POST "$APP_URL/whatsapp/openclaw/heartbeat" \
  -H 'Accept: application/json' -H 'Content-Type: application/json' \
  -H "X-SAHJONY-Timestamp: $TIMESTAMP" -H "X-SAHJONY-Signature: $SIGNATURE" \
  --data-binary "$PAYLOAD" || true)"
unset SIGNATURE
if [[ "$code" != 200 ]]; then
  echo "HOSTINGER_HEARTBEAT_HTTP=$code"
  rm -f "$response"
  exit 3
fi
mv "$response" "$STATE_DIR/heartbeat-response.json"
echo SAHJONY_HOSTINGER_HEARTBEAT=PUBLISHED

# Secondary observation: verify the application now recognizes this Hostinger runtime.
if curl -fsS --max-time 15 "$APP_URL/whatsapp/health" > "$STATE_DIR/public-health.json.tmp" 2>/dev/null; then
  mv "$STATE_DIR/public-health.json.tmp" "$STATE_DIR/public-health.json"
  if python3 - "$STATE_DIR/public-health.json" <<'PY'
import json, sys
h=json.load(open(sys.argv[1]))
node=h.get("hostinger_openclaw") or {}
ok=(h.get("hostinger_independent_runtime") is True and node.get("connected") is True and node.get("gateway_id")=="hostinger-vps")
raise SystemExit(0 if ok else 1)
PY
  then
    echo SAHJONY_HOSTINGER_PUBLIC_GATE=READY
  else
    echo SAHJONY_HOSTINGER_PUBLIC_GATE=STALE
  fi
fi
