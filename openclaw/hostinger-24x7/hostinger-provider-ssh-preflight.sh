#!/usr/bin/env bash
set -euo pipefail

# Provider-side SSH preflight for the authorized Hostinger VPS.
#
# This script intentionally runs before Recovery mode. It uses Hostinger's
# official public-key attachment API to make the workflow's durable management
# key available to the VPS, then performs read-only network/firewall inspection.
# It never disables or rewrites Hostinger firewall rules.

API_BASE="${HOSTINGER_API_BASE:-https://developers.hostinger.com}"
VM_ID="${HOSTINGER_VM_ID:-}"
HOST="${HOSTINGER_HOST:-}"
USER_NAME="${HOSTINGER_USER:-root}"
TOKEN="${HOSTINGER_API_TOKEN:-}"
SSH_KEY_PATH="${SSH_KEY_PATH:-}"
KEY_NAME="${HOSTINGER_MANAGEMENT_KEY_NAME:-SAHJONY Hostinger Management Key}"

log(){ printf '[hostinger-provider-preflight] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

need curl
need jq
need ssh
need ssh-keygen
need nc
[[ -n "$VM_ID" ]] || fail 'HOSTINGER_VM_ID is required'
[[ -n "$HOST" ]] || fail 'HOSTINGER_HOST is required'
[[ -n "$TOKEN" ]] || fail 'HOSTINGER_API_TOKEN is required'

api(){
  local method="$1" path="$2" data="${3:-}"
  local args=(-fsS -X "$method" -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json')
  if [[ -n "$data" ]]; then args+=(-H 'Content-Type: application/json' --data "$data"); fi
  curl "${args[@]}" "$API_BASE$path"
}

wait_action(){
  local id="$1" label="$2"
  for i in $(seq 1 120); do
    local body state
    body="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/actions/$id")"
    state="$(jq -r '.state // empty' <<<"$body")"
    log "$label probe=$i/120 state=${state:-unknown}"
    case "$state" in
      success) return 0 ;;
      failed|failure|error|cancelled|canceled)
        jq -c '{id,name,state,created_at,updated_at}' <<<"$body" >&2 || true
        return 1
        ;;
    esac
    sleep 5
  done
  return 1
}

busy="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/actions?page=1" | jq '[.data[]? | select(.state=="sent" or .state=="started" or .state=="pending" or .state=="running" or .state=="queued")] | length')"
[[ "$busy" == 0 ]] || fail "Hostinger action plane busy ($busy nonterminal action(s)); refusing provider mutation"
log 'Hostinger action plane: idle'

# Read-only network/firewall diagnostics. Do not expose sensitive payloads.
vm_json="$(api GET "/api/vps/v1/virtual-machines/$VM_ID" 2>/dev/null || true)"
if [[ -n "$vm_json" ]]; then
  jq -c '{id,status,state,hostname,firewall_id:(.firewall_id // .firewall.id // null),firewall_name:(.firewall.name // null)}' <<<"$vm_json" 2>/dev/null || true
fi

fw_json="$(api GET '/api/vps/v1/firewall?page=1' 2>/dev/null || true)"
if [[ -n "$fw_json" ]]; then
  jq -c '[.data[]? | {id,name,is_synced,ssh_accept_rule:([.rules[]? | select((.action|ascii_downcase)=="accept" and ((.protocol|ascii_downcase)=="tcp" or (.protocol|ascii_downcase)=="any") and (.port=="22" or .port=="any" or (.port|test("^[0-9]+:[0-9]+$"))))] | length > 0)}]' <<<"$fw_json" 2>/dev/null || true
fi

if nc -z -w 4 "$HOST" 22 >/dev/null 2>&1; then
  log 'TCP/22 is reachable before provider key reconciliation'
else
  log 'TCP/22 is not reachable before provider key reconciliation'
fi

if [[ -z "$SSH_KEY_PATH" || ! -f "$SSH_KEY_PATH" ]]; then
  log 'No stable HOSTINGER_SSH_PRIVATE_KEY is available; provider key attach skipped'
  echo HOSTINGER_PROVIDER_KEY_PREFLIGHT=SKIPPED_NO_STABLE_KEY
  exit 0
fi

chmod 600 "$SSH_KEY_PATH" || true
pub_path="$SSH_KEY_PATH.pub"
ssh-keygen -y -f "$SSH_KEY_PATH" > "$pub_path"
chmod 600 "$pub_path" || true
pub="$(cat "$pub_path")"
key_core="$(awk '{print $1" "$2}' <<<"$pub")"
[[ -n "$key_core" ]] || fail 'could not derive public key core'

# If this exact key is already attached to the VPS, do not mutate anything.
attached_json="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/public-keys?page=1")"
attached_id=''
while IFS=$'\t' read -r id key; do
  [[ -n "${id:-}" && -n "${key:-}" ]] || continue
  core="$(awk '{print $1" "$2}' <<<"$key")"
  if [[ "$core" == "$key_core" ]]; then attached_id="$id"; break; fi
done < <(jq -r '.data[]? | [.id,.key] | @tsv' <<<"$attached_json")

if [[ -n "$attached_id" ]]; then
  log "Stable management key already attached (id=$attached_id)"
  echo HOSTINGER_PROVIDER_KEY_ATTACHED=ALREADY_PRESENT
else
  account_id=''
  page=1
  while (( page <= 20 )); do
    page_json="$(api GET "/api/vps/v1/public-keys?page=$page")"
    while IFS=$'\t' read -r id key; do
      [[ -n "${id:-}" && -n "${key:-}" ]] || continue
      core="$(awk '{print $1" "$2}' <<<"$key")"
      if [[ "$core" == "$key_core" ]]; then account_id="$id"; break; fi
    done < <(jq -r '.data[]? | [.id,.key] | @tsv' <<<"$page_json")
    [[ -n "$account_id" ]] && break
    current="$(jq -r '.meta.current_page // 1' <<<"$page_json")"
    total="$(jq -r '.meta.total // 0' <<<"$page_json")"
    per="$(jq -r '.meta.per_page // 15' <<<"$page_json")"
    (( current * per >= total )) && break
    page=$((page+1))
  done

  if [[ -z "$account_id" ]]; then
    payload="$(jq -n --arg name "$KEY_NAME" --arg key "$pub" '{name:$name,key:$key}')"
    created="$(api POST '/api/vps/v1/public-keys' "$payload")"
    account_id="$(jq -r '.id // empty' <<<"$created")"
    [[ "$account_id" =~ ^[0-9]+$ ]] || fail 'Hostinger public-key creation returned no id'
    log "Registered stable management key in Hostinger account (id=$account_id)"
  else
    log "Stable management key already exists in Hostinger account (id=$account_id)"
  fi

  attach_payload="$(jq -n --argjson id "$account_id" '{ids:[$id]}')"
  attach="$(api POST "/api/vps/v1/public-keys/attach/$VM_ID" "$attach_payload")"
  action_id="$(jq -r '.id // empty' <<<"$attach")"
  [[ "$action_id" =~ ^[0-9]+$ ]] || fail 'Hostinger public-key attach returned no action id'
  wait_action "$action_id" public-key-attach || fail 'Hostinger public-key attach action failed'
  echo HOSTINGER_PROVIDER_KEY_ATTACHED=SUCCESS
fi

# Verify provider-side state, then test normal SSH. No restart is issued here.
verify="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/public-keys?page=1")"
verified=false
while IFS=$'\t' read -r id key; do
  [[ -n "${id:-}" && -n "${key:-}" ]] || continue
  core="$(awk '{print $1" "$2}' <<<"$key")"
  if [[ "$core" == "$key_core" ]]; then verified=true; break; fi
done < <(jq -r '.data[]? | [.id,.key] | @tsv' <<<"$verify")
[[ "$verified" == true ]] || fail 'Hostinger did not report the stable management key as attached'

for i in $(seq 1 12); do
  if nc -z -w 4 "$HOST" 22 >/dev/null 2>&1; then
    if ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -i "$SSH_KEY_PATH" "$USER_NAME@$HOST" 'printf SAHJONY_PROVIDER_KEY_SSH_OK' 2>/dev/null | grep -q SAHJONY_PROVIDER_KEY_SSH_OK; then
      log "Normal SSH authenticated with stable provider-attached key at probe $i"
      echo HOSTINGER_PROVIDER_KEY_SSH=READY
      exit 0
    fi
    log "TCP/22 reachable but stable key authentication not ready (probe $i/12)"
  else
    log "TCP/22 still closed/unreachable (probe $i/12)"
  fi
  sleep 5
done

echo HOSTINGER_PROVIDER_KEY_SSH=NOT_READY
# Not fatal: the canonical controller may still use Recovery mode. This script's
# purpose is to exhaust the safer provider-side key path first and leave a clear
# diagnostic trail.
exit 0
