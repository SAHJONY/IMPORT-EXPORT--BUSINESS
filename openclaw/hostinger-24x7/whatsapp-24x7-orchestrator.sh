#!/usr/bin/env bash
set -uo pipefail

# SAHJONY LLC WhatsApp 24/7 local orchestrator.
# Authoritative runtime: Hostinger + Docker + OpenClaw + an authorized WhatsApp Linked Device session.
# Meta Cloud and Vercel are not required for local readiness.
#
# This tool never deletes/recreates OpenClaw state, never logs WhatsApp out,
# never forces pairing, and never attempts to bypass WhatsApp authorization or rate controls.

MODE="${1:-status}"
STATE_DIR="${SAHJONY_WHATSAPP_STATE_DIR:-/var/lib/sahjony-whatsapp-guardian}"
STATUS_FILE="$STATE_DIR/status.json"
LAST_GOOD="$STATE_DIR/last-good"
LOCK_FILE="${SAHJONY_WHATSAPP_ORCHESTRATOR_LOCK:-/run/lock/sahjony-whatsapp-orchestrator.lock}"
RESTART_STAMP="$STATE_DIR/last-orchestrator-restart"
RESTART_COOLDOWN_SEC="${SAHJONY_RESTART_COOLDOWN_SECONDS:-300}"
GUARDIAN="${SAHJONY_HOSTINGER_GUARDIAN:-/opt/sahjony-openclaw/whatsapp-hostinger-only-guardian.sh}"
PAIRING_CONTROLLER="${SAHJONY_PAIRING_CONTROLLER:-/usr/local/sbin/sahjony-whatsapp-pairing-controller}"
GATEWAY_ID="${SAHJONY_GATEWAY_ID:-hostinger-vps}"

mkdir -p "$STATE_DIR" "$(dirname "$LOCK_FILE")"
chmod 700 "$STATE_DIR" 2>/dev/null || true

log(){ printf '[whatsapp-orchestrator] %s\n' "$*" >&2; }
now_epoch(){ date +%s; }
now_iso(){ date -u +'%Y-%m-%dT%H:%M:%SZ'; }

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || { log 'another orchestrator instance is active'; exit 73; }
fi

json_bool(){ [[ "${1:-false}" == true ]] && printf true || printf false; }

write_status(){
  local state="$1" reason="$2" cid="${3:-}" running="${4:-false}" policy="${5:-unknown}" connected="${6:-false}" timer="${7:-false}" repair="${8:-none}"
  local tmp="$STATUS_FILE.tmp.$$"
  if command -v jq >/dev/null 2>&1; then
    jq -n \
      --arg ts "$(now_iso)" \
      --arg gateway "$GATEWAY_ID" \
      --arg state "$state" \
      --arg reason "$reason" \
      --arg cid "$cid" \
      --arg policy "$policy" \
      --arg repair "$repair" \
      --argjson running "$(json_bool "$running")" \
      --argjson connected "$(json_bool "$connected")" \
      --argjson timer "$(json_bool "$timer")" \
      '{timestamp:$ts,gateway_id:$gateway,authoritative_transport:"hostinger_openclaw",meta_cloud_required:false,vercel_required:false,state:$state,reason:$reason,container_id:$cid,container_running:$running,restart_policy:$policy,whatsapp_connected:$connected,guardian_timer:$timer,last_repair:$repair}' >"$tmp"
  else
    python3 - "$tmp" "$(now_iso)" "$GATEWAY_ID" "$state" "$reason" "$cid" "$running" "$policy" "$connected" "$timer" "$repair" <<'PY'
import json,sys
p,ts,gateway,state,reason,cid,running,policy,connected,timer,repair=sys.argv[1:]
data={
  'timestamp':ts,'gateway_id':gateway,'authoritative_transport':'hostinger_openclaw',
  'meta_cloud_required':False,'vercel_required':False,'state':state,'reason':reason,
  'container_id':cid,'container_running':running=='true','restart_policy':policy,
  'whatsapp_connected':connected=='true','guardian_timer':timer=='true','last_repair':repair,
}
open(p,'w').write(json.dumps(data,separators=(',',':'))+'\n')
PY
  fi
  chmod 600 "$tmp"
  mv "$tmp" "$STATUS_FILE"
  cat "$STATUS_FILE"
}

find_container(){
  docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null \
    | awk -F'|' 'tolower($0) ~ /openclaw|claw/ {print $1; exit}'
}

container_running(){
  [[ "$(docker inspect "$1" --format '{{.State.Running}}' 2>/dev/null || true)" == true ]]
}

restart_policy(){
  docker inspect "$1" --format '{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || printf unknown
}

probe_channel(){
  local cid="$1"
  docker exec "$cid" sh -lc '
    if command -v openclaw >/dev/null 2>&1; then
      openclaw channels status --channel whatsapp --probe 2>&1 || openclaw channels status --probe 2>&1
    elif [ -x "$HOME/.openclaw/bin/openclaw" ]; then
      "$HOME/.openclaw/bin/openclaw" channels status --channel whatsapp --probe 2>&1 || "$HOME/.openclaw/bin/openclaw" channels status --probe 2>&1
    elif [ -x /root/.openclaw/bin/openclaw ]; then
      /root/.openclaw/bin/openclaw channels status --channel whatsapp --probe 2>&1 || /root/.openclaw/bin/openclaw channels status --probe 2>&1
    else
      echo OPENCLAW_BINARY_NOT_FOUND
      exit 127
    fi
  ' 2>&1 || true
}

is_ready(){
  grep -Eiq 'whatsapp.*(connected|ready|active|healthy)|(connected|ready|active|healthy).*whatsapp|linked,[[:space:]]*running,[[:space:]]*connected'
}

needs_pairing(){
  grep -Eiq 'not[ _-]?linked|not[ _-]?logged|login required|pair(ing)? required|scan.*qr|qr.*(scan|code)|disconnected.*auth|session.*(missing|expired|revoked)|unauthenticated'
}

timer_active(){
  systemctl is-active --quiet sahjony-whatsapp-hostinger.timer 2>/dev/null || \
  systemctl is-active --quiet sahjony-whatsapp-guardian.timer 2>/dev/null
}

restart_allowed(){
  local last=0 now
  now="$(now_epoch)"
  [[ -s "$RESTART_STAMP" ]] && last="$(tr -cd '0-9' <"$RESTART_STAMP" 2>/dev/null || printf 0)"
  (( now - last >= RESTART_COOLDOWN_SEC ))
}

mark_good(){
  now_iso >"$LAST_GOOD"
  chmod 600 "$LAST_GOOD"
}

ensure_guardian_timer(){
  if timer_active; then return 0; fi
  if [[ -x "$GUARDIAN" ]]; then
    log 'guardian timer inactive; installing existing Hostinger-only guardian'
    "$GUARDIAN" install >/dev/null 2>&1 || true
  fi
}

pairing_cooldown_reason(){
  [[ -x "$PAIRING_CONTROLLER" ]] || return 0
  "$PAIRING_CONTROLLER" cooldown 2>/dev/null | awk -F= '/^PAIRING_BLOCKED_REASON=/{print $2; exit}' || true
}

main(){
  [[ "$(id -u)" -eq 0 ]] || { write_status PERMISSION_REQUIRED 'run_as_root_on_authorized_hostinger_vps' '' false unknown false false none; return 64; }

  if ! command -v docker >/dev/null 2>&1; then
    write_status DOCKER_UNAVAILABLE 'docker_binary_missing' '' false unknown false false none
    return 21
  fi

  local repair=none
  if ! docker info >/dev/null 2>&1; then
    if [[ "$MODE" == repair ]]; then
      log 'Docker is unavailable; attempting host-level Docker service start'
      systemctl enable --now docker >/dev/null 2>&1 || true
      sleep 3
      repair=start_docker
    fi
    if ! docker info >/dev/null 2>&1; then
      write_status DOCKER_DOWN 'docker_daemon_unreachable' '' false unknown false false "$repair"
      return 22
    fi
  fi

  local cid running=false policy timer=false probe='' connected=false
  cid="$(find_container || true)"
  if [[ -z "$cid" ]]; then
    write_status CONTAINER_MISSING 'existing_openclaw_container_not_found_refusing_recreate' '' false unknown false false "$repair"
    return 23
  fi

  policy="$(restart_policy "$cid")"
  if [[ "$MODE" == repair && "$policy" != always && "$policy" != unless-stopped ]]; then
    docker update --restart unless-stopped "$cid" >/dev/null 2>&1 || true
    policy="$(restart_policy "$cid")"
    repair="${repair:+$repair,}set_restart_policy"
  fi

  if ! container_running "$cid"; then
    if [[ "$MODE" == repair ]]; then
      log 'existing OpenClaw container is stopped; starting it without recreating state'
      docker start "$cid" >/dev/null 2>&1 || true
      sleep 8
      repair="${repair:+$repair,}start_container"
    fi
    if ! container_running "$cid"; then
      write_status CONTAINER_STOPPED 'existing_openclaw_container_not_running' "$cid" false "$policy" false false "$repair"
      return 24
    fi
  fi
  running=true

  probe="$(probe_channel "$cid")"
  if printf '%s\n' "$probe" | is_ready; then connected=true; fi

  if [[ "$connected" != true && "$MODE" == repair ]]; then
    if printf '%s\n' "$probe" | needs_pairing; then
      local block_reason
      block_reason="$(pairing_cooldown_reason)"
      write_status PAIRING_REQUIRED "${block_reason:-authorized_linked_device_session_required}" "$cid" true "$policy" false false "$repair"
      return 30
    fi

    if restart_allowed; then
      log 'WhatsApp channel degraded; restarting the existing OpenClaw container once'
      now_epoch >"$RESTART_STAMP"
      chmod 600 "$RESTART_STAMP"
      docker restart "$cid" >/dev/null 2>&1 || true
      sleep 8
      repair="${repair:+$repair,}restart_container_once"
      probe="$(probe_channel "$cid")"
      if printf '%s\n' "$probe" | is_ready; then connected=true; fi
    else
      repair="${repair:+$repair,}restart_suppressed_cooldown"
    fi
  fi

  if [[ "$connected" != true ]]; then
    if printf '%s\n' "$probe" | needs_pairing; then
      local block_reason
      block_reason="$(pairing_cooldown_reason)"
      write_status PAIRING_REQUIRED "${block_reason:-authorized_linked_device_session_required}" "$cid" true "$policy" false false "$repair"
      return 30
    fi
    write_status CHANNEL_DEGRADED 'openclaw_running_but_whatsapp_probe_not_ready' "$cid" true "$policy" false false "$repair"
    return 31
  fi

  if [[ "$MODE" == repair ]]; then ensure_guardian_timer; fi
  timer_active && timer=true || true
  policy="$(restart_policy "$cid")"

  if [[ "$policy" != always && "$policy" != unless-stopped ]]; then
    write_status DEGRADED_RESTART_POLICY 'docker_restart_policy_not_persistent' "$cid" true "$policy" true "$timer" "$repair"
    return 32
  fi

  if [[ "$MODE" == verify && "$timer" != true ]]; then
    write_status DEGRADED_GUARDIAN 'guardian_timer_not_active' "$cid" true "$policy" true false "$repair"
    return 33
  fi

  if [[ "$MODE" == repair && "$timer" != true ]]; then
    write_status DEGRADED_GUARDIAN 'guardian_timer_not_active_after_repair' "$cid" true "$policy" true false "$repair"
    return 33
  fi

  mark_good
  write_status READY 'hostinger_openclaw_whatsapp_connected' "$cid" true "$policy" true "$timer" "$repair"
  return 0
}

case "$MODE" in
  status|repair|verify) main ;;
  *) echo 'Usage: whatsapp-24x7-orchestrator.sh {status|repair|verify}' >&2; exit 64 ;;
esac
