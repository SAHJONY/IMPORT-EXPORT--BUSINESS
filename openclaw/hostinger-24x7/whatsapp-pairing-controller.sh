#!/usr/bin/env bash
set -euo pipefail

# SAHJONY LLC WhatsApp pairing controller
# Purpose: make device linking safe and deterministic without bypassing WhatsApp controls.
# This tool never deletes session data, never forces re-pairing, and never loops QR creation.

STATE_DIR="${STATE_DIR:-/var/lib/sahjony-whatsapp-pairing}"
LOCK_FILE="${LOCK_FILE:-/run/lock/sahjony-whatsapp-pairing.lock}"
CONTAINER="${OPENCLAW_CONTAINER:-sahjony-openclaw-gateway}"
ACCOUNT_ID="${WHATSAPP_ACCOUNT_ID:-default}"
MIN_ATTEMPT_INTERVAL_SEC="${MIN_ATTEMPT_INTERVAL_SEC:-1800}"
FAILED_ATTEMPT_BACKOFF_SEC="${FAILED_ATTEMPT_BACKOFF_SEC:-3600}"
CLIENT_LOCK_BACKOFF_SEC="${CLIENT_LOCK_BACKOFF_SEC:-21600}"
LOGIN_TIMEOUT_MS="${LOGIN_TIMEOUT_MS:-180000}"
GUARDIAN="${GUARDIAN:-/usr/local/sbin/sahjony-whatsapp-guardian}"

mkdir -p "$STATE_DIR" "$(dirname "$LOCK_FILE")"
chmod 700 "$STATE_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "PAIRING_CONTROLLER_BUSY=1" >&2; exit 73; }

now_epoch(){ date +%s; }
read_num(){ local f="$1"; [[ -s "$f" ]] && tr -cd '0-9' <"$f" || printf '0'; }
write_num(){ printf '%s\n' "$2" >"$1"; chmod 600 "$1"; }
set_reason(){ printf '%s\n' "$1" >"$STATE_DIR/blocked_reason"; chmod 600 "$STATE_DIR/blocked_reason"; }

redact(){ sed -E 's/(token|secret|key|password|authorization)[=:][^[:space:]]+/\1=[REDACTED]/Ig'; }

container_exists(){ docker inspect "$CONTAINER" >/dev/null 2>&1; }
container_running(){ [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" == "true" ]]; }

probe_text(){
  docker exec "$CONTAINER" openclaw channels status --channel whatsapp --probe 2>&1 || true
}

is_connected(){
  local p
  p="$(probe_text)"
  printf '%s\n' "$p" | grep -Eiq 'whatsapp.*(connected|ready|active|healthy)|(connected|ready|active|healthy).*whatsapp'
}

preflight(){
  command -v docker >/dev/null || { echo "PAIRING_PREFLIGHT_DOCKER_MISSING=1" >&2; return 21; }
  container_exists || { echo "PAIRING_PREFLIGHT_CONTAINER_MISSING=$CONTAINER" >&2; return 22; }
  container_running || { echo "PAIRING_PREFLIGHT_CONTAINER_STOPPED=$CONTAINER" >&2; return 23; }

  if command -v timedatectl >/dev/null 2>&1; then
    local sync
    sync="$(timedatectl show -p NTPSynchronized --value 2>/dev/null || true)"
    [[ "$sync" == "yes" ]] || echo "PAIRING_PREFLIGHT_NTP_WARNING=${sync:-unknown}" >&2
  fi

  if command -v getent >/dev/null 2>&1; then
    getent hosts web.whatsapp.com >/dev/null 2>&1 || echo "PAIRING_PREFLIGHT_DNS_WARNING=web.whatsapp.com" >&2
  fi

  echo "PAIRING_PREFLIGHT=PASS" >&2
}

cooldown_status(){
  local now blocked last reason
  now="$(now_epoch)"
  blocked="$(read_num "$STATE_DIR/blocked_until_epoch")"
  last="$(read_num "$STATE_DIR/last_attempt_epoch")"
  reason="$(cat "$STATE_DIR/blocked_reason" 2>/dev/null || true)"
  echo "PAIRING_NOW_EPOCH=$now"
  echo "PAIRING_BLOCKED_UNTIL_EPOCH=$blocked"
  echo "PAIRING_LAST_ATTEMPT_EPOCH=$last"
  echo "PAIRING_BLOCKED_REASON=${reason:-none}"
  if (( blocked > now )); then
    echo "PAIRING_COOLDOWN_ACTIVE=true"
    echo "PAIRING_COOLDOWN_REMAINING_SEC=$((blocked-now))"
    return 75
  fi
  echo "PAIRING_COOLDOWN_ACTIVE=false"
  return 0
}

mark_client_lock(){
  local sec="${1:-$CLIENT_LOCK_BACKOFF_SEC}" now until
  [[ "$sec" =~ ^[0-9]+$ ]] || { echo "INVALID_BACKOFF_SECONDS=$sec" >&2; exit 64; }
  now="$(now_epoch)"; until=$((now+sec))
  write_num "$STATE_DIR/blocked_until_epoch" "$until"
  set_reason "whatsapp_client_device_link_lock"
  echo "PAIRING_CLIENT_LOCK_RECORDED=true"
  echo "PAIRING_BLOCKED_UNTIL_EPOCH=$until"
  echo "PAIRING_BACKOFF_SEC=$sec"
}

clear_expired_lock(){
  local now blocked
  now="$(now_epoch)"; blocked="$(read_num "$STATE_DIR/blocked_until_epoch")"
  if (( blocked > 0 && blocked <= now )); then
    rm -f "$STATE_DIR/blocked_until_epoch" "$STATE_DIR/blocked_reason"
  fi
}

start_pairing(){
  preflight
  if is_connected; then
    echo '{"connected":true,"message":"WhatsApp already connected; pairing not started."}'
    return 0
  fi

  clear_expired_lock
  local now blocked last
  now="$(now_epoch)"
  blocked="$(read_num "$STATE_DIR/blocked_until_epoch")"
  last="$(read_num "$STATE_DIR/last_attempt_epoch")"

  if (( blocked > now )); then
    echo "PAIRING_REFUSED_COOLDOWN_REMAINING_SEC=$((blocked-now))" >&2
    return 75
  fi
  if (( last > 0 && now-last < MIN_ATTEMPT_INTERVAL_SEC )); then
    echo "PAIRING_REFUSED_MIN_INTERVAL_REMAINING_SEC=$((MIN_ATTEMPT_INTERVAL_SEC-(now-last)))" >&2
    return 75
  fi

  write_num "$STATE_DIR/last_attempt_epoch" "$now"

  local tmp rc
  tmp="$(mktemp)"
  set +e
  docker exec "$CONTAINER" openclaw gateway call web.login.start \
    --params "{\"accountId\":\"$ACCOUNT_ID\",\"timeoutMs\":$LOGIN_TIMEOUT_MS}" \
    --timeout $((LOGIN_TIMEOUT_MS+10000)) --json >"$tmp" 2>"$tmp.err"
  rc=$?
  set -e

  if (( rc != 0 )); then
    cat "$tmp.err" | redact >&2 || true
    local until=$((now+FAILED_ATTEMPT_BACKOFF_SEC))
    write_num "$STATE_DIR/blocked_until_epoch" "$until"
    set_reason "openclaw_login_start_failed"
    rm -f "$tmp" "$tmp.err"
    echo "PAIRING_LOGIN_START_FAILED_RC=$rc" >&2
    echo "PAIRING_BACKOFF_UNTIL_EPOCH=$until" >&2
    return "$rc"
  fi

  python3 - "$tmp" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])
raw=p.read_text(errors='replace').strip()
try:
    d=json.loads(raw)
except Exception:
    print('PAIRING_LOGIN_START_INVALID_JSON=1', file=sys.stderr)
    sys.exit(31)
if d.get('connected') is True:
    print(json.dumps({'connected': True, 'message': 'WhatsApp already connected.'}, separators=(',',':')))
    sys.exit(0)
qr=d.get('qrDataUrl') or ''
if not qr.startswith('data:image/png;base64,'):
    msg=str(d.get('message') or '')
    print('PAIRING_QR_MISSING=1', file=sys.stderr)
    print(msg[:500], file=sys.stderr)
    sys.exit(32)
print(json.dumps({'connected': False, 'qrDataUrl': qr, 'message': str(d.get('message') or '')}, separators=(',',':')))
PY
  rc=$?
  rm -f "$tmp" "$tmp.err"
  return "$rc"
}

wait_pairing(){
  preflight
  if is_connected; then
    rm -f "$STATE_DIR/blocked_until_epoch" "$STATE_DIR/blocked_reason"
    echo '{"connected":true,"message":"WhatsApp connected."}'
    return 0
  fi

  local tmp rc now until
  tmp="$(mktemp)"
  set +e
  docker exec "$CONTAINER" openclaw gateway call web.login.wait \
    --params "{\"accountId\":\"$ACCOUNT_ID\",\"timeoutMs\":$LOGIN_TIMEOUT_MS}" \
    --timeout $((LOGIN_TIMEOUT_MS+10000)) --json >"$tmp" 2>"$tmp.err"
  rc=$?
  set -e

  if (( rc != 0 )); then
    cat "$tmp.err" | redact >&2 || true
  fi

  local connected=false
  if [[ -s "$tmp" ]]; then
    connected="$(python3 - "$tmp" <<'PY'
import json, sys
try:
    d=json.load(open(sys.argv[1]))
    print('true' if d.get('connected') is True else 'false')
except Exception:
    print('false')
PY
)"
  fi

  if [[ "$connected" == "true" ]] || is_connected; then
    rm -f "$STATE_DIR/blocked_until_epoch" "$STATE_DIR/blocked_reason"
    echo '{"connected":true,"message":"WhatsApp connected."}'
    rm -f "$tmp" "$tmp.err"
    return 0
  fi

  now="$(now_epoch)"; until=$((now+FAILED_ATTEMPT_BACKOFF_SEC))
  write_num "$STATE_DIR/blocked_until_epoch" "$until"
  set_reason "pairing_attempt_not_completed"
  echo "PAIRING_NOT_COMPLETED=true" >&2
  echo "PAIRING_BACKOFF_UNTIL_EPOCH=$until" >&2
  rm -f "$tmp" "$tmp.err"
  echo '{"connected":false,"message":"Pairing was not completed; backoff armed."}'
  return 41
}

finalize(){
  preflight
  if ! is_connected; then
    echo "PAIRING_FINALIZE_REFUSED_NOT_CONNECTED=1" >&2
    return 41
  fi
  if [[ -x "$GUARDIAN" ]]; then
    "$GUARDIAN" install >/dev/null
    "$GUARDIAN" audit
  else
    echo "PAIRING_GUARDIAN_NOT_INSTALLED=$GUARDIAN" >&2
    return 42
  fi
  rm -f "$STATE_DIR/blocked_until_epoch" "$STATE_DIR/blocked_reason"
  echo "SAHJONY_HOSTINGER_WHATSAPP_PAIRING=READY"
}

audit(){
  preflight
  cooldown_status || true
  local p
  p="$(probe_text)"
  printf '%s\n' "$p" | redact
  if is_connected; then
    echo "PAIRING_CHANNEL_CONNECTED=true"
    return 0
  fi
  echo "PAIRING_CHANNEL_CONNECTED=false"
  return 41
}

usage(){
  cat <<'EOF'
Usage: whatsapp-pairing-controller.sh COMMAND [args]
  audit                       Audit runtime, channel, and cooldown state.
  start                       Start exactly one non-forced WhatsApp login and emit JSON/QR data.
  wait                        Wait for the single active login; arms backoff if incomplete.
  mark-client-lock [seconds]  Record a client-side "Can't link new devices right now" lock.
  cooldown                    Print cooldown state.
  finalize                    Verify connected state and arm the 24x7 guardian.

This controller intentionally does NOT bypass WhatsApp verification, rate limits, device-link locks,
2FA, or provider policy. It never deletes durable session state and never uses force re-pairing.
EOF
}

cmd="${1:-}"
case "$cmd" in
  audit) audit ;;
  start) start_pairing ;;
  wait) wait_pairing ;;
  mark-client-lock) mark_client_lock "${2:-$CLIENT_LOCK_BACKOFF_SEC}" ;;
  cooldown) cooldown_status ;;
  finalize) finalize ;;
  *) usage; exit 64 ;;
esac
