#!/usr/bin/env bash
set -euo pipefail

: "${HOSTINGER_API_TOKEN:?HOSTINGER_API_TOKEN is required}"
VM_ID="${VM_ID:-767852}"
HOST="${HOST:-69.62.68.67}"
API="${HOSTINGER_API_BASE:-https://developers.hostinger.com}"

hdr=(-H "Authorization: Bearer $HOSTINGER_API_TOKEN" -H 'Accept: application/json')

vm="$(curl -fsS "${hdr[@]}" "$API/api/vps/v1/virtual-machines/$VM_ID")"
state="$(jq -r '.state // "unknown"' <<<"$vm")"
echo "HOSTINGER_VM_STATE=$state"

actions="$(curl -fsS "${hdr[@]}" "$API/api/vps/v1/virtual-machines/$VM_ID/actions?page=1")"
active="$(jq '[.data[]? | select(.state=="sent" or .state=="started" or .state=="pending" or .state=="running" or .state=="queued")] | length' <<<"$actions")"
echo "HOSTINGER_ACTIVE_ACTIONS=$active"
if (( active > 0 )); then
  jq -c '[.data[]? | select(.state=="sent" or .state=="started" or .state=="pending" or .state=="running" or .state=="queued") | {id,name,state,created_at,updated_at}]' <<<"$actions"
  echo "HOSTINGER_MUTATION_GATE=WAIT"
  exit 20
fi

if nc -z -w 5 "$HOST" 22 >/dev/null 2>&1; then
  echo HOSTINGER_TCP22=OPEN
else
  echo HOSTINGER_TCP22=CLOSED
fi

echo "HOSTINGER_MUTATION_GATE=READY"
