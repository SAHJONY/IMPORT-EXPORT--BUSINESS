#!/usr/bin/env bash
set -euo pipefail

# SAHJONY Hostinger Resilient Access Broker
#
# Restores authenticated management access to the authorized Kali VPS without
# relying on Hostinger's account-level public-key attachment becoming a guest-OS
# authorized key. The supported fallback is one owned Hostinger Recovery session
# via the canonical recovery controller, which injects the management key into
# the mounted Kali filesystem and repairs the native ssh.service.
#
# This bypasses a fragile orchestration path, not provider authentication.

MODE="${1:-diagnose}"
API_BASE="${HOSTINGER_API_BASE:-https://developers.hostinger.com}"
VM_ID="${HOSTINGER_VM_ID:-}"
HOST="${HOSTINGER_HOST:-}"
USER_NAME="${HOSTINGER_USER:-root}"
TOKEN="${HOSTINGER_API_TOKEN:-}"
SSH_KEY_PATH="${SSH_KEY_PATH:-}"
CONTROLLER="${HOSTINGER_RECOVERY_CONTROLLER:-openclaw/hostinger-24x7/hostinger-recovery-controller.sh}"
STATE_DIR="${SAHJONY_ACCESS_BROKER_STATE_DIR:-/tmp/sahjony-hostinger-access-broker}"
IDLE_TIMEOUT="${HOSTINGER_ACTION_IDLE_TIMEOUT:-900}"
STABLE_SAMPLES="${HOSTINGER_ACTION_STABLE_SAMPLES:-2}"
GENERATED_KEY=false

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR" || true

log(){ printf '[hostinger-access-broker] %s\n' "$*"; }
fail(){ printf '[hostinger-access-broker] FAIL: %s\n' "$*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

validate(){
  [[ "$MODE" =~ ^(diagnose|solve)$ ]] || fail 'mode must be diagnose or solve'
  [[ -n "$VM_ID" ]] || fail 'HOSTINGER_VM_ID is required'
  [[ -n "$HOST" ]] || fail 'HOSTINGER_HOST is required'
  [[ -n "$TOKEN" ]] || fail 'HOSTINGER_API_TOKEN is required'
  [[ "$IDLE_TIMEOUT" =~ ^[0-9]+$ ]] || fail 'HOSTINGER_ACTION_IDLE_TIMEOUT must be integer seconds'
  [[ "$STABLE_SAMPLES" =~ ^[0-9]+$ ]] || fail 'HOSTINGER_ACTION_STABLE_SAMPLES must be integer'
  need curl; need jq; need ssh; need ssh-keygen; need nc; need date
  [[ -f "$CONTROLLER" ]] || fail "canonical recovery controller missing: $CONTROLLER"
  bash -n "$CONTROLLER" || fail 'canonical recovery controller syntax validation failed'
}

api_get(){
  curl -fsS -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json' "$API_BASE$1"
}

actions_json(){ api_get "/api/vps/v1/virtual-machines/$VM_ID/actions?page=1"; }

busy_actions(){
  jq -c '[.data[]? | select(.state=="sent" or .state=="started" or .state=="pending" or .state=="running" or .state=="queued") | {id,name,state,created_at,updated_at}]'
}

wait_idle(){
  local start now stable=0 body busy count
  start="$(date +%s)"
  while true; do
    body="$(actions_json)"
    busy="$(busy_actions <<<"$body")"
    count="$(jq 'length' <<<"$busy")"
    if [[ "$count" == 0 ]]; then
      stable=$((stable+1))
      log "Hostinger action plane idle sample $stable/$STABLE_SAMPLES"
      (( stable >= STABLE_SAMPLES )) && return 0
    else
      stable=0
      log "Hostinger action plane busy with $count nonterminal action(s)"
      jq -c '.[]' <<<"$busy" || true
    fi
    now="$(date +%s)"
    (( now - start < IDLE_TIMEOUT )) || fail 'Hostinger action plane did not become stably idle before timeout'
    sleep 10
  done
}

tcp22(){ nc -z -w 4 "$HOST" 22 >/dev/null 2>&1; }

ssh_auth(){
  [[ -n "$SSH_KEY_PATH" && -f "$SSH_KEY_PATH" ]] || return 2
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 \
    -i "$SSH_KEY_PATH" "$USER_NAME@$HOST" 'printf SAHJONY_ACCESS_BROKER_SSH=READY' 2>/dev/null | \
    grep -q SAHJONY_ACCESS_BROKER_SSH=READY
}

prepare_key(){
  if [[ -n "$SSH_KEY_PATH" && -f "$SSH_KEY_PATH" ]]; then
    chmod 600 "$SSH_KEY_PATH" || true
    if [[ ! -s "$SSH_KEY_PATH.pub" ]]; then
      ssh-keygen -y -f "$SSH_KEY_PATH" > "$SSH_KEY_PATH.pub"
    fi
  else
    SSH_KEY_PATH="$STATE_DIR/access-broker-key"
    rm -f "$SSH_KEY_PATH" "$SSH_KEY_PATH.pub"
    ssh-keygen -q -t ed25519 -N '' -f "$SSH_KEY_PATH" -C "sahjony-access-broker-$(date +%s)"
    GENERATED_KEY=true
  fi
  export SSH_KEY_PATH
}

report(){
  local access_class="$1" tcp=false auth=false busy='[]'
  tcp22 && tcp=true || true
  ssh_auth && auth=true || true
  if body="$(actions_json 2>/dev/null)"; then busy="$(busy_actions <<<"$body")"; fi
  jq -n \
    --arg vm_id "$VM_ID" --arg host "$HOST" --arg access_class "$access_class" \
    --arg strategy 'direct_ssh_then_owned_recovery_key_seed' \
    --arg key_path "${SSH_KEY_PATH:-}" \
    --argjson tcp22 "$tcp" --argjson ssh_authenticated "$auth" \
    --argjson generated_key "$GENERATED_KEY" --argjson busy_actions "$busy" \
    '{vm_id:$vm_id,host:$host,access_class:$access_class,strategy:$strategy,tcp22:$tcp22,ssh_authenticated:$ssh_authenticated,generated_ephemeral_key:$generated_key,local_key_path:$key_path,provider_public_key_attach_required:false,hostinger_recovery_authorization_required_for_fallback:true,docker_manager_required:false,meta_cloud_required:false,busy_actions:$busy}' | tee "$STATE_DIR/report.json"
}

diagnose(){
  local class
  if ssh_auth; then class=READY
  elif tcp22; then class=SSH_AUTH_FAILED
  elif [[ -z "$SSH_KEY_PATH" || ! -f "$SSH_KEY_PATH" ]]; then class=SSH_KEY_UNAVAILABLE
  else class=SSH_TRANSPORT_DOWN
  fi
  report "$class"
  [[ "$class" == READY ]] && echo SAHJONY_HOSTINGER_ACCESS_BROKER=READY || echo "SAHJONY_HOSTINGER_ACCESS_BROKER=$class"
}

solve(){
  prepare_key
  if ssh_auth; then
    log 'Normal Kali SSH already authenticates; no provider mutation is required'
    report READY
    echo SAHJONY_HOSTINGER_ACCESS_BROKER=READY
    return 0
  fi

  log 'Direct guest SSH is unavailable; skipping account-level public-key attach as a readiness dependency'
  wait_idle

  # The canonical controller owns Recovery. It will use the key prepared above,
  # inject its public half into the mounted original Kali root, repair only the
  # native ssh.service, exit only its own Recovery session, and permit at most
  # one bounded VPS restart if normal boot still does not expose SSH.
  "$CONTROLLER" repair-ssh

  if ! ssh_auth; then
    report SSH_RECOVERY_DID_NOT_CONVERGE
    fail 'canonical Recovery completed but authenticated normal Kali SSH is still unavailable'
  fi

  report READY
  echo SAHJONY_HOSTINGER_ACCESS_BROKER=READY
}

validate
case "$MODE" in
  diagnose) diagnose ;;
  solve) solve ;;
esac
