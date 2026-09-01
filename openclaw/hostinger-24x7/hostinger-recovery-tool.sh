#!/usr/bin/env bash
set -euo pipefail

HOSTINGER_API_BASE="${HOSTINGER_API_BASE:-https://developers.hostinger.com}"
VM_ID="${VM_ID:-${HOSTINGER_VM_ID:-767852}}"
HOST="${HOST:-${HOSTINGER_HOST:-69.62.68.67}}"
USER_NAME="${USER_NAME:-${HOSTINGER_USER:-root}}"

require_token() {
  [[ -n "${HOSTINGER_API_TOKEN:-${API_TOKEN:-}}" ]] || {
    echo HOSTINGER_API_TOKEN_MISSING=1 >&2
    exit 2
  }
  API_TOKEN="${HOSTINGER_API_TOKEN:-${API_TOKEN:-}}"
}

api() {
  require_token
  local method="$1" path="$2" data="${3:-}"
  local args=(-fsS -X "$method" -H "Authorization: Bearer $API_TOKEN" -H 'Accept: application/json')
  [[ -z "$data" ]] || args+=(-H 'Content-Type: application/json' --data "$data")
  curl "${args[@]}" "$HOSTINGER_API_BASE$path"
}

generate_password() {
  local random candidate
  random="$(openssl rand -hex 20)"
  candidate="R${random}a9!Z#"
  [[ ${#candidate} -ge 16 ]]
  [[ "$candidate" =~ [A-Z] ]]
  [[ "$candidate" =~ [a-z] ]]
  [[ "$candidate" =~ [0-9] ]]
  [[ "$candidate" =~ [^[:alnum:]] ]]
  printf '%s\n' "$candidate"
}

classify_ssh() {
  local key="${1:-}"
  if ! nc -z -w 5 "$HOST" 22 >/dev/null 2>&1; then
    echo CLASS=SSH_NETWORK_DOWN
    return 20
  fi
  echo TCP22=OPEN
  if [[ -z "$key" || ! -s "$key" ]]; then
    echo CLASS=SSH_PORT_OPEN_NO_KEY
    return 21
  fi
  : >/tmp/sahjony-ssh-classify.err
  if ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=7 -i "$key" "$USER_NAME@$HOST" 'printf SSH_READY' 2>/tmp/sahjony-ssh-classify.err | grep -q SSH_READY; then
    echo CLASS=SSH_READY
    return 0
  fi
  if grep -qi 'Permission denied' /tmp/sahjony-ssh-classify.err; then
    echo CLASS=SSH_AUTH_REJECTED
    return 22
  fi
  sed -n '1,8p' /tmp/sahjony-ssh-classify.err >&2 || true
  echo CLASS=SSH_UNKNOWN_FAILURE
  return 23
}

preflight() {
  require_token
  local vm actions state ip busy
  vm="$(api GET "/api/vps/v1/virtual-machines/$VM_ID")"
  state="$(jq -r '.state // empty' <<<"$vm")"
  ip="$(jq -r '[.. | objects | .address? // empty | select(type=="string") | select(test("^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$"))] | first // empty' <<<"$vm")"
  [[ -z "$ip" || "$ip" == "$HOST" ]] || {
    echo HOSTINGER_VM_IDENTITY_MISMATCH="$ip" >&2
    return 30
  }
  actions="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/actions?page=1")"
  busy="$(jq '[.data[]? | select(.state=="sent" or .state=="started" or .state=="pending" or .state=="running" or .state=="queued")] | length' <<<"$actions")"
  echo HOSTINGER_VM_STATE="${state:-unknown}"
  echo HOSTINGER_ACTION_PLANE_ACTIVE="$busy"
  [[ "$busy" == 0 ]] || {
    echo CLASS=ACTION_PLANE_BUSY
    return 31
  }
  echo CLASS=ACTION_PLANE_IDLE
}

wait_action() {
  local id="$1" max="${2:-120}" sleep_s="${3:-5}"
  [[ "$id" =~ ^[1-9][0-9]*$ ]] || {
    echo INVALID_ACTION_ID="$id" >&2
    return 40
  }
  local i a state
  for i in $(seq 1 "$max"); do
    a="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/actions/$id")"
    state="$(jq -r '.state // empty' <<<"$a")"
    echo "ACTION_PROBE=$i/$max ID=$id STATE=${state:-unknown}"
    case "$state" in
      success) return 0 ;;
      failed|failure|error|cancelled|canceled)
        jq -c '{id,name,state,created_at,updated_at}' <<<"$a" >&2 || true
        return 41
        ;;
    esac
    sleep "$sleep_s"
  done
  echo ACTION_TIMEOUT="$id" >&2
  return 42
}

start_recovery() {
  preflight >/tmp/hostinger-preflight.out || {
    cat /tmp/hostinger-preflight.out
    return $?
  }
  cat /tmp/hostinger-preflight.out
  local password="${1:-}"
  [[ -n "$password" ]] || password="$(generate_password)"
  [[ "$password" =~ [A-Z] && "$password" =~ [a-z] && "$password" =~ [0-9] && "$password" =~ [^[:alnum:]] ]] || {
    echo RECOVERY_PASSWORD_POLICY_INVALID=1 >&2
    return 50
  }
  local payload tmp code body id
  payload="$(jq -n --arg p "$password" '{root_password:$p}')"
  tmp="$(mktemp)"
  code="$(curl -sS -o "$tmp" -w '%{http_code}' -X POST -H "Authorization: Bearer ${HOSTINGER_API_TOKEN:-${API_TOKEN:-}}" -H 'Content-Type: application/json' -H 'Accept: application/json' --data "$payload" "$HOSTINGER_API_BASE/api/vps/v1/virtual-machines/$VM_ID/recovery")"
  body="$(cat "$tmp")"; rm -f "$tmp"
  if [[ "$code" != 200 && "$code" != 201 && "$code" != 202 ]]; then
    echo HOSTINGER_RECOVERY_START_HTTP="$code" >&2
    jq -c . <<<"$body" >&2 2>/dev/null || printf '%s\n' "$body" >&2
    return 51
  fi
  id="$(jq -r '.id // empty' <<<"$body")"
  [[ "$id" =~ ^[1-9][0-9]*$ ]] || {
    echo HOSTINGER_RECOVERY_ACTION_ID_INVALID="$id" >&2
    jq -c . <<<"$body" >&2 || true
    return 52
  }
  echo RECOVERY_PASSWORD="$password"
  echo RECOVERY_ACTION_ID="$id"
}

stop_recovery() {
  preflight >/tmp/hostinger-stop-preflight.out || true
  local body id state
  body="$(api DELETE "/api/vps/v1/virtual-machines/$VM_ID/recovery")"
  id="$(jq -r '.id // empty' <<<"$body")"
  state="$(jq -r '.state // empty' <<<"$body")"
  if [[ "$state" == success || "$id" == 0 ]]; then
    echo RECOVERY_STOP=ACCEPTED
    return 0
  fi
  [[ "$id" =~ ^[1-9][0-9]*$ ]] || {
    echo RECOVERY_STOP_RESPONSE_INVALID=1 >&2
    jq -c . <<<"$body" >&2 || true
    return 60
  }
  echo RECOVERY_STOP_ACTION_ID="$id"
  wait_action "$id"
}

attached_keys() {
  api GET "/api/vps/v1/virtual-machines/$VM_ID/public-keys?page=1" | jq '[.data[]? | {id,name,key_type:(.key|split(" ")[0]),comment:(.key|split(" ")[2] // "")}]'
}

usage() {
  cat <<'EOF'
Usage: hostinger-recovery-tool.sh <command> [args]

Commands:
  password                   Generate a Hostinger Recovery-compliant password.
  preflight                  Verify VM identity and idle Hostinger action plane.
  classify-ssh [keyfile]     Classify SSH network/authentication state.
  attached-keys              Show Hostinger control-plane keys attached to the VM.
  start-recovery [password]  Start Recovery and print RECOVERY_PASSWORD/ACTION_ID.
  wait-action <id>           Poll a Hostinger action to terminal state.
  stop-recovery              Exit Recovery and wait if a pollable action is returned.
EOF
}

cmd="${1:-}"
case "$cmd" in
  password) generate_password ;;
  preflight) preflight ;;
  classify-ssh) classify_ssh "${2:-}" ;;
  attached-keys) attached_keys ;;
  start-recovery) start_recovery "${2:-}" ;;
  wait-action) wait_action "${2:?action id required}" ;;
  stop-recovery) stop_recovery ;;
  *) usage; exit 64 ;;
esac
