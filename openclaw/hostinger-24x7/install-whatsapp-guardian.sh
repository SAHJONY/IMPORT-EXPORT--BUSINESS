#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR=/var/lib/sahjony-whatsapp-guardian
LOG=/var/log/sahjony-whatsapp-guardian.log
APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
APP_URL="${APP_URL%/}"
GATEWAY_ID="${SAHJONY_GATEWAY_ID:-hostinger-vps}"

fail() {
  echo "GUARDIAN_INSTALL_FAIL=$*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail docker_missing
command -v curl >/dev/null 2>&1 || fail curl_missing
command -v python3 >/dev/null 2>&1 || fail python3_missing

find_openclaw_container() {
  docker ps -aq | while read -r id; do
    meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}' 2>/dev/null || true)"
    if grep -Eqi 'openclaw|claw' <<<"$meta"; then
      printf '%s\n' "$id"
      return 0
    fi
  done
}

run_openclaw() {
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

cid="$(find_openclaw_container)"
[[ -n "$cid" ]] || fail openclaw_container_missing

# The app deliberately recognizes only the explicit Hostinger authority.  Older
# OpenClaw state can retain gatewayId=default even though current bridge source
# defaults to hostinger-vps, so repair the persisted plugin configuration in-place.
# This is reversible configuration; it does not unlink or re-pair WhatsApp.
run_openclaw "$cid" config set plugins.entries.sahjony-app-bridge.config \
  "{\"gatewayId\":\"${GATEWAY_ID}\"}" --strict-json --merge \
  || fail bridge_gateway_id_config_failed
run_openclaw "$cid" config validate || fail openclaw_config_invalid

echo "SAHJONY_OPENCLAW_BRIDGE_GATEWAY_ID=${GATEWAY_ID}"

docker update --restart unless-stopped "$cid" >/dev/null || fail restart_policy_failed
# Apply plugin configuration to the same durable container/session.
docker restart "$cid" >/dev/null || fail openclaw_container_restart_failed
sleep 12

probe="$(run_openclaw "$cid" channels status --probe 2>&1 || true)"
printf '%s\n' "$probe"
grep -Eqi 'whatsapp.*(connected|ready|active|healthy|ok)|(connected|ready|active|healthy).*whatsapp|linked,[[:space:]]*running,[[:space:]]*connected' <<<"$probe" \
  || fail whatsapp_not_connected_after_bridge_config

install -m 0755 "$ROOT/whatsapp-guardian.sh" /usr/local/sbin/sahjony-whatsapp-guardian
cat >/etc/systemd/system/sahjony-whatsapp-guardian.service <<'EOF'
[Unit]
Description=SAHJONY WhatsApp 24/7 self-healing guardian
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sahjony-whatsapp-guardian
TimeoutStartSec=120
EOF
cat >/etc/systemd/system/sahjony-whatsapp-guardian.timer <<'EOF'
[Unit]
Description=Run SAHJONY WhatsApp guardian every minute

[Timer]
OnBootSec=45s
OnUnitActiveSec=60s
AccuracySec=10s
Persistent=true

[Install]
WantedBy=timers.target
EOF

mkdir -p "$STATE_DIR"
# Prevent an old successful probe from satisfying a new recovery attempt.
rm -f "$STATE_DIR/last-good" "$STATE_DIR/public-health.json" "$STATE_DIR/public-health.json.tmp"

systemctl daemon-reload
systemctl enable --now sahjony-whatsapp-guardian.timer >/dev/null
# Initial run is authoritative: do not mask a secret/signature/heartbeat failure.
systemctl start sahjony-whatsapp-guardian.service || {
  echo SAHJONY_WHATSAPP_GUARDIAN_INITIAL_RUN_FAILED=1 >&2
  tail -n 80 "$LOG" 2>/dev/null || true
  exit 2
}

test -s "$STATE_DIR/last-good" || fail last_good_not_created
if ! tail -n 120 "$LOG" 2>/dev/null | grep -q 'SAHJONY_HOSTINGER_HEARTBEAT=PUBLISHED'; then
  fail signed_hostinger_heartbeat_not_published
fi

# Require the application to recognize this exact Hostinger runtime, not the
# historical logical/default gateway.  Persistence can lag the POST briefly.
public_ready=false
for attempt in $(seq 1 18); do
  health="$(curl -fsS --max-time 15 "$APP_URL/whatsapp/health" 2>/dev/null || true)"
  if [[ -n "$health" ]] && HEALTH_JSON="$health" EXPECTED_GATEWAY="$GATEWAY_ID" python3 - <<'PY'
import json, os
try:
    h=json.loads(os.environ['HEALTH_JSON'])
except Exception:
    raise SystemExit(1)
node=h.get('hostinger_openclaw') or {}
ok=(
    h.get('hostinger_independent_runtime') is True
    and node.get('connected') is True
    and node.get('heartbeat_fresh') is True
    and node.get('gateway_id') == os.environ['EXPECTED_GATEWAY']
)
raise SystemExit(0 if ok else 1)
PY
  then
    public_ready=true
    printf '%s\n' "$health" > "$STATE_DIR/public-health.json"
    break
  fi
  sleep 5
done

[[ "$public_ready" == true ]] || {
  echo SAHJONY_HOSTINGER_PUBLIC_GATE_NOT_AUTHORITATIVE=1 >&2
  curl -fsS --max-time 15 "$APP_URL/whatsapp/health" 2>/dev/null \
    | python3 -c 'import json,sys; h=json.load(sys.stdin); print(json.dumps({"hostinger_independent_runtime":h.get("hostinger_independent_runtime"),"hostinger_openclaw":h.get("hostinger_openclaw"),"openclaw_default":h.get("openclaw_default")},separators=(",",":")))' \
    || true
  exit 3
}

systemctl is-active --quiet sahjony-whatsapp-guardian.timer || fail guardian_timer_inactive
echo SAHJONY_HOSTINGER_PUBLIC_GATE=READY
echo SAHJONY_WHATSAPP_GUARDIAN_INSTALLED=1
