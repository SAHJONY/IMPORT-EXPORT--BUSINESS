#!/usr/bin/env bash
set -euo pipefail

# SAHJONY Hostinger Incident Resolver
#
# Purpose: classify and resolve recurring Hostinger/Kali/SSH/Docker/OpenClaw
# incidents without depending on Hostinger Docker Manager or Meta Cloud.
#
# This tool does not bypass provider authentication or security controls. It
# bypasses unsupported/dead-end recovery paths by selecting the supported path:
# Hostinger action plane -> normal SSH when available -> owned Recovery only when
# needed -> local Docker -> retained OpenClaw -> WhatsApp guardian.

MODE="${1:-diagnose}"
API_BASE="${HOSTINGER_API_BASE:-https://developers.hostinger.com}"
VM_ID="${HOSTINGER_VM_ID:-}"
HOST="${HOSTINGER_HOST:-}"
USER_NAME="${HOSTINGER_USER:-root}"
TOKEN="${HOSTINGER_API_TOKEN:-}"
SSH_KEY_PATH="${SSH_KEY_PATH:-}"
CONTROLLER="${HOSTINGER_RECOVERY_CONTROLLER:-openclaw/hostinger-24x7/hostinger-recovery-controller.sh}"
PROVIDER_PREFLIGHT="${HOSTINGER_PROVIDER_PREFLIGHT:-openclaw/hostinger-24x7/hostinger-provider-ssh-preflight.sh}"
ACTION_IDLE_TIMEOUT="${HOSTINGER_ACTION_IDLE_TIMEOUT:-900}"
ACTION_STABLE_SAMPLES="${HOSTINGER_ACTION_STABLE_SAMPLES:-2}"
SOLVE_ATTEMPTS="${HOSTINGER_SOLVE_ATTEMPTS:-3}"
STATE_DIR="${SAHJONY_INCIDENT_STATE_DIR:-/tmp/sahjony-hostinger-incident-resolver}"
REPORT="$STATE_DIR/report.json"
CONTROLLER_LOG="$STATE_DIR/controller.log"
PREFLIGHT_LOG="$STATE_DIR/provider-preflight.log"

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR" || true

log(){ printf '[hostinger-incident-resolver] %s\n' "$*"; }
warn(){ printf '[hostinger-incident-resolver] WARN: %s\n' "$*" >&2; }
fail(){ printf '[hostinger-incident-resolver] FAIL: %s\n' "$*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

validate(){
  [[ "$MODE" =~ ^(diagnose|solve)$ ]] || fail 'mode must be diagnose or solve'
  [[ -n "$VM_ID" ]] || fail 'HOSTINGER_VM_ID is required'
  [[ -n "$HOST" ]] || fail 'HOSTINGER_HOST is required'
  [[ -n "$TOKEN" ]] || fail 'HOSTINGER_API_TOKEN is required'
  need curl; need jq; need nc; need ssh; need date
  [[ -f "$CONTROLLER" ]] || fail "controller missing: $CONTROLLER"
  [[ -f "$PROVIDER_PREFLIGHT" ]] || fail "provider preflight missing: $PROVIDER_PREFLIGHT"
  bash -n "$CONTROLLER" || fail 'controller syntax validation failed'
  bash -n "$PROVIDER_PREFLIGHT" || fail 'provider preflight syntax validation failed'
  [[ "$ACTION_IDLE_TIMEOUT" =~ ^[0-9]+$ ]] || fail 'HOSTINGER_ACTION_IDLE_TIMEOUT must be integer seconds'
  [[ "$ACTION_STABLE_SAMPLES" =~ ^[0-9]+$ ]] || fail 'HOSTINGER_ACTION_STABLE_SAMPLES must be integer'
  [[ "$SOLVE_ATTEMPTS" =~ ^[0-9]+$ ]] || fail 'HOSTINGER_SOLVE_ATTEMPTS must be integer'
}

api_call(){
  local method="$1" path="$2" data="${3:-}" attempt code body tmp
  for attempt in 1 2 3 4; do
    tmp="$(mktemp)"
    local -a args=(-sS -o "$tmp" -w '%{http_code}' -X "$method" -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json')
    if [[ -n "$data" ]]; then args+=(-H 'Content-Type: application/json' --data "$data"); fi
    code="$(curl "${args[@]}" "$API_BASE$path" || true)"
    body="$(cat "$tmp")"; rm -f "$tmp"
    if [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
      printf '%s' "$body"
      return 0
    fi
    case "$code" in
      408|409|425|429|500|502|503|504)
        warn "Hostinger API transient HTTP $code on $method $path (attempt $attempt/4)"
        sleep $((attempt * 3))
        ;;
      401|403)
        warn "Hostinger API authorization/access HTTP $code on $method $path; credentials/permissions must be fixed, not bypassed"
        printf '%s' "$body" > "$STATE_DIR/last-api-error.json"
        return 41
        ;;
      *)
        warn "Hostinger API HTTP ${code:-transport_error} on $method $path"
        printf '%s' "$body" > "$STATE_DIR/last-api-error.json"
        return 42
        ;;
    esac
  done
  printf '%s' "$body" > "$STATE_DIR/last-api-error.json"
  return 43
}

actions_json(){ api_call GET "/api/vps/v1/virtual-machines/$VM_ID/actions?page=1"; }

busy_actions(){
  local body="$1"
  jq -c '[.data[]? | select(.state=="sent" or .state=="started" or .state=="pending" or .state=="running" or .state=="queued") | {id,name,state,created_at,updated_at}]' <<<"$body"
}

wait_action_plane_idle(){
  local start now stable=0 body busy count
  start="$(date +%s)"
  while true; do
    body="$(actions_json)" || return $?
    busy="$(busy_actions "$body")"
    count="$(jq 'length' <<<"$busy")"
    if [[ "$count" == 0 ]]; then
      stable=$((stable+1))
      log "Hostinger action plane idle sample $stable/$ACTION_STABLE_SAMPLES"
      if (( stable >= ACTION_STABLE_SAMPLES )); then return 0; fi
    else
      stable=0
      log "Hostinger action plane busy with $count nonterminal action(s)"
      jq -c '.[]' <<<"$busy" || true
    fi
    now="$(date +%s)"
    (( now - start < ACTION_IDLE_TIMEOUT )) || { warn 'Hostinger action plane did not become stably idle before timeout'; return 44; }
    sleep 10
  done
}

tcp22(){ nc -z -w 4 "$HOST" 22 >/dev/null 2>&1; }

ssh_auth(){
  [[ -n "$SSH_KEY_PATH" && -f "$SSH_KEY_PATH" ]] || return 2
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -i "$SSH_KEY_PATH" "$USER_NAME@$HOST" 'printf SAHJONY_INCIDENT_SSH_OK' 2>/dev/null | grep -q SAHJONY_INCIDENT_SSH_OK
}

remote(){
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -i "$SSH_KEY_PATH" "$USER_NAME@$HOST" "$@"
}

docker_manager_capability(){
  # Diagnostic only. Kali is expected to report Docker Manager unsupported.
  # Any result here is non-blocking; local Docker over SSH remains authoritative.
  local tmp code body
  tmp="$(mktemp)"
  code="$(curl -sS -o "$tmp" -w '%{http_code}' -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' "$API_BASE/api/vps/v1/virtual-machines/$VM_ID/docker" || true)"
  body="$(cat "$tmp")"; rm -f "$tmp"
  if [[ "$code" == 200 ]]; then
    echo available
  elif grep -Eqi 'VPS:2044|does not support Docker Manager|unsupported' <<<"$body"; then
    echo unsupported_expected
  else
    echo unavailable_nonblocking
  fi
}

runtime_class(){
  if ! tcp22; then echo SSH_TRANSPORT_DOWN; return 0; fi
  if [[ -z "$SSH_KEY_PATH" || ! -f "$SSH_KEY_PATH" ]]; then echo SSH_KEY_UNAVAILABLE; return 0; fi
  if ! ssh_auth; then echo SSH_AUTH_FAILED; return 0; fi

  if ! remote 'command -v docker >/dev/null 2>&1'; then echo DOCKER_MISSING; return 0; fi
  if ! remote 'systemctl is-active --quiet docker.service'; then echo DOCKER_INACTIVE; return 0; fi

  local count
  count="$(remote 'docker ps -aq 2>/dev/null | while read -r id; do [ -n "$id" ] || continue; meta="$(docker inspect "$id" --format "{{.Name}}|{{.Config.Image}}|{{json .Config.Labels}}" 2>/dev/null || true)"; grep -Eqi "openclaw|open[-_ ]?claw|claw" <<<"$meta" && echo "$id"; done | wc -l' 2>/dev/null | tr -d '[:space:]' || echo unknown)"
  [[ "$count" =~ ^[0-9]+$ ]] || { echo OPENCLAW_CLASSIFICATION_FAILED; return 0; }
  if (( count == 0 )); then echo OPENCLAW_CONTAINER_MISSING; return 0; fi
  if (( count > 1 )); then echo OPENCLAW_CONTAINER_AMBIGUOUS; return 0; fi

  if remote 'cid="$(docker ps -aq 2>/dev/null | while read -r id; do meta="$(docker inspect "$id" --format "{{.Name}}|{{.Config.Image}}|{{json .Config.Labels}}" 2>/dev/null || true)"; grep -Eqi "openclaw|open[-_ ]?claw|claw" <<<"$meta" && echo "$id"; done | head -n1)"; test -n "$cid"; test "$(docker inspect "$cid" --format "{{.State.Running}}")" = true; docker exec "$cid" sh -lc "openclaw channels status --probe" >/tmp/sahjony-openclaw-probe 2>&1; grep -Eqi "whatsapp.*(connected|ready|healthy)|connected.*whatsapp|status.*(connected|ready|healthy)" /tmp/sahjony-openclaw-probe'; then
    echo READY
  else
    echo OPENCLAW_OR_WHATSAPP_UNHEALTHY
  fi
}

write_report(){
  local class="$1" dm="$2" busy_json="$3" tcp=false auth=false
  tcp22 && tcp=true || true
  ssh_auth && auth=true || true
  jq -n \
    --arg vm_id "$VM_ID" --arg host "$HOST" --arg incident_class "$class" \
    --arg docker_manager "$dm" --argjson tcp22 "$tcp" --argjson ssh_authenticated "$auth" \
    --argjson busy_actions "$busy_json" \
    '{vm_id:$vm_id,host:$host,incident_class:$incident_class,tcp22:$tcp22,ssh_authenticated:$ssh_authenticated,docker_manager:$docker_manager,docker_manager_required:false,meta_cloud_required:false,busy_actions:$busy_actions,authoritative_path:"Hostinger -> Kali -> native SSH -> local Docker -> retained OpenClaw -> WhatsApp Linked Device"}' > "$REPORT"
  cat "$REPORT"
}

diagnose(){
  local actions='[]' body class dm
  if body="$(actions_json 2>/dev/null)"; then actions="$(busy_actions "$body")"; fi
  class="$(runtime_class)"
  dm="$(docker_manager_capability)"
  write_report "$class" "$dm" "$actions"
  [[ "$class" == READY ]] && echo SAHJONY_HOSTINGER_INCIDENT=READY || echo "SAHJONY_HOSTINGER_INCIDENT=$class"
}

provider_preflight_with_retry(){
  : > "$PREFLIGHT_LOG"
  for attempt in $(seq 1 "$SOLVE_ATTEMPTS"); do
    wait_action_plane_idle || return $?
    set +e
    "$PROVIDER_PREFLIGHT" > >(tee -a "$PREFLIGHT_LOG") 2> >(tee -a "$PREFLIGHT_LOG" >&2)
    rc=$?
    set -e
    if (( rc == 0 )); then return 0; fi
    if grep -Eqi 'action plane busy|HTTP (408|409|425|429|500|502|503|504)|requested URL returned error: (408|409|425|429|500|502|503|504)' "$PREFLIGHT_LOG"; then
      warn "provider preflight hit a transient control-plane condition (attempt $attempt/$SOLVE_ATTEMPTS)"
      sleep $((attempt * 5))
      continue
    fi
    return "$rc"
  done
  return 45
}

controller_full_with_retry(){
  : > "$CONTROLLER_LOG"
  for attempt in $(seq 1 "$SOLVE_ATTEMPTS"); do
    wait_action_plane_idle || return $?
    set +e
    SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT=RECOVER_RETAINED_OPENCLAW \
      "$CONTROLLER" full > >(tee -a "$CONTROLLER_LOG") 2> >(tee -a "$CONTROLLER_LOG" >&2)
    rc=$?
    set -e
    if (( rc == 0 )); then return 0; fi

    if grep -Eqi 'action plane busy|HTTP (408|409|425|429|500|502|503|504)|requested URL returned error: (408|409|425|429|500|502|503|504)' "$CONTROLLER_LOG"; then
      warn "controller hit a transient Hostinger action/API condition (attempt $attempt/$SOLVE_ATTEMPTS); draining and retrying"
      sleep $((attempt * 5))
      : > "$CONTROLLER_LOG"
      continue
    fi

    if grep -Eqi '401|403|authorization|forbidden|permission' "$CONTROLLER_LOG"; then
      warn 'controller encountered an authorization/permission failure; this cannot be bypassed safely'
      return 46
    fi

    return "$rc"
  done
  return 47
}

solve(){
  local before after
  before="$(runtime_class)"
  log "initial incident class: $before"
  if [[ "$before" == READY ]]; then
    diagnose
    echo SAHJONY_HOSTINGER_INCIDENT_RESOLVER=NOOP_ALREADY_READY
    return 0
  fi

  # Exhaust the safer provider-side stable-key path first. This may attach an
  # already-authorized management key but never disables firewall/security.
  provider_preflight_with_retry || warn 'provider-side SSH preflight did not restore normal SSH; proceeding to canonical owned Recovery path'

  # The controller is the only mutation engine. It uses normal SSH if possible,
  # enters one owned Recovery session only if needed, restores local Docker only
  # when retained evidence exists, and reconstructs OpenClaw only from one safe
  # retained candidate because the explicit reconstruction gate is set here.
  controller_full_with_retry || {
    diagnose || true
    fail 'canonical controller could not converge the incident to READY; forensic logs were preserved'
  }

  after="$(runtime_class)"
  log "post-solve incident class: $after"
  diagnose
  [[ "$after" == READY ]] || fail "solver completed but final class is $after"
  echo SAHJONY_HOSTINGER_INCIDENT_RESOLVER=READY
}

validate
case "$MODE" in
  diagnose) diagnose ;;
  solve) solve ;;
esac
