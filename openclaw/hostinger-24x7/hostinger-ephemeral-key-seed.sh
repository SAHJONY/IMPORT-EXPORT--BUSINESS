#!/usr/bin/env bash
set -euo pipefail

# Targeted access recovery for the authorized SAHJONY Hostinger VPS.
# Purpose: seed ONE already-generated ephemeral public key into the mounted original
# Kali root when provider-side public-key attachment does not propagate to sshd.
#
# This tool does NOT repair Docker, recreate OpenClaw, touch Meta, or alter WhatsApp.
# It owns and closes exactly one Hostinger Recovery session.

: "${HOSTINGER_API_TOKEN:?HOSTINGER_API_TOKEN required}"
KEY_PATH="${1:?usage: hostinger-ephemeral-key-seed.sh /path/to/private-key}"
API_BASE="${HOSTINGER_API_BASE:-https://developers.hostinger.com}"
VM_ID="${HOSTINGER_VM_ID:-767852}"
HOST="${HOSTINGER_HOST:-69.62.68.67}"
USER_NAME="${HOSTINGER_USER:-root}"

[[ -f "$KEY_PATH" ]] || { echo KEY_PATH_MISSING=1 >&2; exit 2; }
[[ -f "$KEY_PATH.pub" ]] || ssh-keygen -y -f "$KEY_PATH" > "$KEY_PATH.pub"
chmod 600 "$KEY_PATH"

api(){
  local method="$1" path="$2" data="${3:-}"
  local args=(-fsS -X "$method" -H "Authorization: Bearer $HOSTINGER_API_TOKEN" -H 'Accept: application/json')
  [[ -z "$data" ]] || args+=(-H 'Content-Type: application/json' --data "$data")
  curl "${args[@]}" "$API_BASE$path"
}

wait_action(){
  local id="$1" label="$2"
  for i in $(seq 1 120); do
    a="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/actions/$id")"
    s="$(jq -r '.state // empty' <<<"$a")"
    echo "$label probe=$i/120 state=${s:-unknown}"
    case "$s" in
      success) return 0 ;;
      failed|failure|error|cancelled|canceled) jq -c . <<<"$a" >&2 || true; return 1 ;;
    esac
    sleep 5
  done
  return 1
}

busy="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/actions?page=1" | jq '[.data[]? | select(.state=="sent" or .state=="started" or .state=="pending" or .state=="running" or .state=="queued")] | length')"
[[ "$busy" == 0 ]] || { echo HOSTINGER_ACTION_PLANE_BUSY="$busy" >&2; exit 3; }

echo HOSTINGER_ACTION_PLANE=IDLE
RECOVERY_PASSWORD="$(openssl rand -hex 18)Aa1!"
echo "::add-mask::$RECOVERY_PASSWORD" 2>/dev/null || true
payload="$(jq -n --arg p "$RECOVERY_PASSWORD" '{root_password:$p}')"
owned=false

cleanup(){
  rc=$?
  if [[ "$owned" == true ]]; then
    echo HOSTINGER_KEYSEED_CLEANUP_RECOVERY_STOP=1 >&2
    set +e
    body="$(api DELETE "/api/vps/v1/virtual-machines/$VM_ID/recovery" 2>/dev/null)"
    id="$(jq -r '.id // empty' <<<"${body:-{}}" 2>/dev/null)"
    [[ "$id" =~ ^[0-9]+$ ]] && wait_action "$id" keyseed-cleanup-stop >/dev/null 2>&1 || true
    set -e
  fi
  exit "$rc"
}
trap cleanup EXIT INT TERM

body="$(api POST "/api/vps/v1/virtual-machines/$VM_ID/recovery" "$payload")"
start_id="$(jq -r '.id // empty' <<<"$body")"
[[ "$start_id" =~ ^[0-9]+$ ]] || { echo HOSTINGER_KEYSEED_RECOVERY_START_ID_MISSING=1 >&2; exit 4; }
owned=true
wait_action "$start_id" keyseed-recovery-start || { echo HOSTINGER_KEYSEED_RECOVERY_START_FAILED=1 >&2; exit 5; }

export SSHPASS="$RECOVERY_PASSWORD"
recovery_ready=false
for i in $(seq 1 60); do
  if sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -o PreferredAuthentications=password -o PubkeyAuthentication=no "$USER_NAME@$HOST" 'printf SAHJONY_KEYSEED_RECOVERY_OK' 2>/dev/null | grep -q SAHJONY_KEYSEED_RECOVERY_OK; then
    recovery_ready=true
    echo "HOSTINGER_KEYSEED_RECOVERY_SSH=READY probe=$i"
    break
  fi
  sleep 10
done
[[ "$recovery_ready" == true ]] || { echo HOSTINGER_KEYSEED_RECOVERY_SSH=NOT_READY >&2; exit 6; }

PUB_B64="$(base64 -w0 "$KEY_PATH.pub")"
sshpass -e ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -o PreferredAuthentications=password -o PubkeyAuthentication=no "$USER_NAME@$HOST" "PUB_B64='$PUB_B64' bash -s" <<'REMOTE'
set -euo pipefail
root=''
for mp in /mnt/sdb1 /mnt /mnt/vps /mnt/root; do
  if [[ -f "$mp/etc/os-release" && -x "$mp/usr/sbin/sshd" && -d "$mp/root" ]]; then root="$mp"; break; fi
done
if [[ -z "$root" ]]; then
  while read -r mp; do
    [[ "$mp" == / ]] && continue
    if [[ -f "$mp/etc/os-release" && -x "$mp/usr/sbin/sshd" && -d "$mp/root" ]]; then root="$mp"; break; fi
  done < <(findmnt -rn -o TARGET | sort -u)
fi
[[ -n "$root" ]] || { echo ORIGINAL_KALI_ROOT_NOT_FOUND=1 >&2; exit 20; }
echo "ORIGINAL_KALI_ROOT=$root"
install -d -m 700 "$root/root/.ssh"
touch "$root/root/.ssh/authorized_keys"
chmod 600 "$root/root/.ssh/authorized_keys"
chown root:root "$root/root/.ssh" "$root/root/.ssh/authorized_keys" 2>/dev/null || true
pub="$(printf '%s' "$PUB_B64" | base64 -d)"
grep -qxF "$pub" "$root/root/.ssh/authorized_keys" || printf '%s\n' "$pub" >> "$root/root/.ssh/authorized_keys"
chroot "$root" /usr/sbin/sshd -t
sync
echo SAHJONY_EPHEMERAL_KEY_SEEDED=1
REMOTE

stop="$(api DELETE "/api/vps/v1/virtual-machines/$VM_ID/recovery")"
stop_id="$(jq -r '.id // empty' <<<"$stop")"
[[ "$stop_id" =~ ^[0-9]+$ ]] || { echo HOSTINGER_KEYSEED_RECOVERY_STOP_ID_MISSING=1 >&2; exit 7; }
wait_action "$stop_id" keyseed-recovery-stop || { echo HOSTINGER_KEYSEED_RECOVERY_STOP_FAILED=1 >&2; exit 8; }
owned=false

normal_ready=false
for i in $(seq 1 48); do
  if nc -z -w 4 "$HOST" 22 >/dev/null 2>&1 && ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -i "$KEY_PATH" "$USER_NAME@$HOST" 'printf SAHJONY_KEYSEED_NORMAL_OK' 2>/dev/null | grep -q SAHJONY_KEYSEED_NORMAL_OK; then
    normal_ready=true
    echo "HOSTINGER_KEYSEED_NORMAL_SSH=READY probe=$i"
    break
  fi
  sleep 5
done
[[ "$normal_ready" == true ]] || { echo HOSTINGER_KEYSEED_NORMAL_SSH=NOT_READY >&2; exit 9; }

echo SAHJONY_HOSTINGER_EPHEMERAL_KEYSEED=READY
trap - EXIT INT TERM
