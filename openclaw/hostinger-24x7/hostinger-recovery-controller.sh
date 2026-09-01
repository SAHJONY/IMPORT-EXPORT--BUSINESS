#!/usr/bin/env bash
set -euo pipefail

# SAHJONY Hostinger Recovery Controller
# Purpose: recover Kali SSH + existing Docker/OpenClaw safely without depending on
# Hostinger Docker Manager (unsupported on Kali) or Meta Cloud.
#
# Modes:
#   diagnose      read-only checks only
#   repair-ssh    use Hostinger Recovery only when normal SSH is unavailable
#   heal-runtime  require normal SSH; preserve existing OpenClaw container
#   full          repair SSH if required, then heal Docker/OpenClaw
#
# Required env:
#   HOSTINGER_API_TOKEN
#   HOSTINGER_VM_ID
#   HOSTINGER_HOST
# Optional:
#   HOSTINGER_USER=root
#   SSH_KEY_PATH=/path/to/private/key
#   GUARDIAN_LOCAL_PATH=openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh

MODE="${1:-diagnose}"
API_BASE="${HOSTINGER_API_BASE:-https://developers.hostinger.com}"
VM_ID="${HOSTINGER_VM_ID:-}"
HOST="${HOSTINGER_HOST:-}"
USER_NAME="${HOSTINGER_USER:-root}"
TOKEN="${HOSTINGER_API_TOKEN:-}"
SSH_KEY_PATH="${SSH_KEY_PATH:-}"
GUARDIAN_LOCAL_PATH="${GUARDIAN_LOCAL_PATH:-openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh}"
STATE_DIR="${SAHJONY_CONTROLLER_STATE_DIR:-/tmp/sahjony-hostinger-controller}"
RECOVERY_OWNED=false
RECOVERY_ACTION_ID=""
RECOVERY_PASSWORD=""

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR" || true

log(){ printf '[hostinger-controller] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

validate(){
  [[ "$MODE" =~ ^(diagnose|repair-ssh|heal-runtime|full)$ ]] || fail 'mode must be diagnose, repair-ssh, heal-runtime, or full'
  [[ -n "$VM_ID" ]] || fail 'HOSTINGER_VM_ID is required'
  [[ -n "$HOST" ]] || fail 'HOSTINGER_HOST is required'
  [[ -n "$TOKEN" ]] || fail 'HOSTINGER_API_TOKEN is required'
  need curl; need jq; need ssh; need nc
}

api(){
  local method="$1" path="$2" data="${3:-}"
  local args=(-fsS -X "$method" -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json')
  if [[ -n "$data" ]]; then args+=(-H 'Content-Type: application/json' --data "$data"); fi
  curl "${args[@]}" "$API_BASE$path"
}

actions_json(){ api GET "/api/vps/v1/virtual-machines/$VM_ID/actions?page=1"; }

busy_action_count(){
  actions_json | jq '[.data[]? | select(.state=="sent" or .state=="started" or .state=="pending" or .state=="running" or .state=="queued")] | length'
}

require_idle_action_plane(){
  local busy
  busy="$(busy_action_count)"
  [[ "$busy" == 0 ]] || fail "Hostinger action plane busy ($busy nonterminal action(s)); refusing concurrent mutation"
  log 'Hostinger action plane: idle'
}

tcp22(){ nc -z -w 4 "$HOST" 22 >/dev/null 2>&1; }

ssh_opts(){
  printf '%s\n' '-o' 'BatchMode=yes' '-o' 'StrictHostKeyChecking=no' '-o' 'UserKnownHostsFile=/dev/null' '-o' 'ConnectTimeout=8'
}

normal_ssh(){
  [[ -n "$SSH_KEY_PATH" && -f "$SSH_KEY_PATH" ]] || return 1
  local -a opts=(); mapfile -t opts < <(ssh_opts)
  ssh "${opts[@]}" -i "$SSH_KEY_PATH" "$USER_NAME@$HOST" 'printf SAHJONY_NORMAL_SSH_OK' 2>/dev/null | grep -q SAHJONY_NORMAL_SSH_OK
}

print_status(){
  local tcp=false auth=false busy
  tcp22 && tcp=true || true
  normal_ssh && auth=true || true
  busy="$(busy_action_count 2>/dev/null || echo unknown)"
  jq -n --arg host "$HOST" --arg vm "$VM_ID" --arg busy "$busy" --argjson tcp "$tcp" --argjson auth "$auth" \
    '{host:$host,vm_id:$vm,hostinger_busy_actions:$busy,tcp22:$tcp,normal_ssh_authenticated:$auth,docker_manager_required:false,meta_cloud_required:false}'
}

wait_action(){
  local id="$1" label="$2"
  for i in $(seq 1 120); do
    local a s
    a="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/actions/$id")"
    s="$(jq -r '.state // empty' <<<"$a")"
    log "$label probe=$i/120 state=${s:-unknown}"
    case "$s" in success) return 0;; failed|failure|error|cancelled|canceled) jq -c . <<<"$a" >&2; return 1;; esac
    sleep 5
  done
  return 1
}

make_ephemeral_key(){
  if [[ -n "$SSH_KEY_PATH" && -f "$SSH_KEY_PATH" ]]; then return 0; fi
  SSH_KEY_PATH="$STATE_DIR/hostinger-controller-key"
  rm -f "$SSH_KEY_PATH" "$SSH_KEY_PATH.pub"
  ssh-keygen -q -t ed25519 -N '' -f "$SSH_KEY_PATH" -C "sahjony-controller-$(date +%s)"
}

enter_recovery(){
  require_idle_action_plane
  RECOVERY_PASSWORD="$(openssl rand -hex 18)Aa1!"
  log 'Entering Hostinger Recovery using one owned session'
  local payload body id
  payload="$(jq -n --arg p "$RECOVERY_PASSWORD" '{root_password:$p}')"
  body="$(api POST "/api/vps/v1/virtual-machines/$VM_ID/recovery" "$payload")"
  id="$(jq -r '.id // empty' <<<"$body")"
  [[ "$id" =~ ^[0-9]+$ ]] || fail 'Recovery start action id missing'
  RECOVERY_ACTION_ID="$id"; RECOVERY_OWNED=true
  wait_action "$id" recovery-start || fail 'Recovery start failed'
}

recovery_ssh(){
  need sshpass
  SSHPASS="$RECOVERY_PASSWORD" sshpass -e ssh \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 \
    -o PreferredAuthentications=password -o PubkeyAuthentication=no \
    "$USER_NAME@$HOST" "$@"
}

wait_recovery_ssh(){
  for i in $(seq 1 60); do
    if recovery_ssh 'printf RECOVERY_OK' 2>/dev/null | grep -q RECOVERY_OK; then log "Recovery SSH authenticated at probe $i"; return 0; fi
    sleep 10
  done
  return 1
}

repair_original_kali_ssh(){
  make_ephemeral_key
  wait_recovery_ssh || fail 'Recovery SSH authentication failed'
  local pub_b64
  pub_b64="$(base64 -w0 "$SSH_KEY_PATH.pub")"
  recovery_ssh "PUB_B64='$pub_b64' bash -s" <<'REMOTE'
set -euo pipefail
root=''
for mp in /mnt/sdb1 /mnt; do
  if [ -f "$mp/etc/os-release" ] && [ -x "$mp/usr/sbin/sshd" ]; then root="$mp"; break; fi
done
[ -n "$root" ] || { echo ORIGINAL_KALI_ROOT_NOT_FOUND=1 >&2; exit 20; }
echo "ORIGINAL_KALI_ROOT=$root"

install -d -m 700 "$root/root/.ssh"
touch "$root/root/.ssh/authorized_keys"
chmod 600 "$root/root/.ssh/authorized_keys"
pub="$(printf '%s' "$PUB_B64" | base64 -d)"
grep -qxF "$pub" "$root/root/.ssh/authorized_keys" || printf '%s\n' "$pub" >> "$root/root/.ssh/authorized_keys"

# Known regression guard: never run a second sshd on TCP/22.
rm -f "$root/etc/systemd/system/sahjony-sshd.service"
find "$root/etc/systemd/system" -type l -name 'sahjony-sshd.service' -delete 2>/dev/null || true

install -d "$root/etc/ssh/sshd_config.d" "$root/run/sshd"
cat > "$root/etc/ssh/sshd_config.d/00-sahjony-management.conf" <<'EOF'
Port 22
AddressFamily any
ListenAddress 0.0.0.0
PubkeyAuthentication yes
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
chmod 600 "$root/etc/ssh/sshd_config.d/00-sahjony-management.conf"
rm -f "$root/etc/ssh/sshd_not_to_be_run"
chroot "$root" /usr/bin/ssh-keygen -A
chroot "$root" /usr/sbin/sshd -t
mkdir -p "$root/etc/systemd/system/multi-user.target.wants"
ln -sfn /lib/systemd/system/ssh.service "$root/etc/systemd/system/multi-user.target.wants/ssh.service"
if [ -x "$root/usr/sbin/ufw" ]; then chroot "$root" /usr/sbin/ufw allow 22/tcp >/dev/null 2>&1 || true; fi
sync
echo SAHJONY_NATIVE_SSH_REPAIRED=1
REMOTE
}

exit_recovery(){
  [[ "$RECOVERY_OWNED" == true ]] || return 0
  local body id
  body="$(api DELETE "/api/vps/v1/virtual-machines/$VM_ID/recovery")"
  id="$(jq -r '.id // empty' <<<"$body")"
  [[ "$id" =~ ^[0-9]+$ ]] || fail 'Recovery stop action id missing'
  wait_action "$id" recovery-stop || fail 'Recovery stop failed'
  RECOVERY_OWNED=false
}

wait_normal_ssh(){
  for i in $(seq 1 48); do
    if tcp22 && normal_ssh; then log "normal Kali SSH authenticated at probe $i"; return 0; fi
    sleep 5
  done
  return 1
}

one_bounded_restart(){
  require_idle_action_plane
  local body id
  body="$(api POST "/api/vps/v1/virtual-machines/$VM_ID/restart")"
  id="$(jq -r '.id // empty' <<<"$body")"
  [[ "$id" =~ ^[0-9]+$ ]] || fail 'restart action id missing'
  wait_action "$id" restart || fail 'bounded VPS restart failed'
}

repair_ssh_if_needed(){
  if normal_ssh; then log 'normal SSH already healthy; Recovery not required'; return 0; fi
  enter_recovery
  repair_original_kali_ssh
  exit_recovery
  if ! wait_normal_ssh; then
    log 'normal SSH still unavailable; issuing one bounded VPS restart'
    one_bounded_restart
    wait_normal_ssh || fail 'normal SSH unavailable after targeted repair + one restart'
  fi
}

remote(){
  local -a opts=(); mapfile -t opts < <(ssh_opts)
  ssh "${opts[@]}" -i "$SSH_KEY_PATH" "$USER_NAME@$HOST" "$@"
}

heal_runtime(){
  normal_ssh || fail 'normal SSH authentication is required before runtime healing'
  remote 'bash -s' <<'REMOTE'
set -euo pipefail
command -v docker >/dev/null 2>&1 || { echo DOCKER_NOT_INSTALLED=1 >&2; exit 50; }
systemctl enable --now docker >/dev/null
mapfile -t ids < <(docker ps -aq | while read -r id; do
  meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}' 2>/dev/null || true)"
  grep -Eqi 'openclaw|claw' <<<"$meta" && echo "$id" || true
done)
((${#ids[@]})) || { echo OPENCLAW_CONTAINER_NOT_FOUND=1 >&2; exit 51; }
if ((${#ids[@]} > 1)); then
  echo "OPENCLAW_CONTAINER_AMBIGUITY=${#ids[@]}" >&2
  docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}' >&2
  exit 52
fi
cid="${ids[0]}"
docker update --restart unless-stopped "$cid" >/dev/null
[ "$(docker inspect "$cid" --format '{{.State.Running}}')" = true ] || docker start "$cid" >/dev/null
echo "OPENCLAW_CONTAINER=$cid"
echo "OPENCLAW_RESTART_POLICY=$(docker inspect "$cid" --format '{{.HostConfig.RestartPolicy.Name}}')"
REMOTE

  [[ -f "$GUARDIAN_LOCAL_PATH" ]] || fail "guardian script not found: $GUARDIAN_LOCAL_PATH"
  local -a opts=(); mapfile -t opts < <(ssh_opts)
  scp "${opts[@]}" -i "$SSH_KEY_PATH" "$GUARDIAN_LOCAL_PATH" "$USER_NAME@$HOST:/tmp/sahjony-whatsapp-guardian"
  remote 'install -m 700 /tmp/sahjony-whatsapp-guardian /usr/local/sbin/sahjony-whatsapp-guardian && /usr/local/sbin/sahjony-whatsapp-guardian install'
  remote 'systemctl is-active --quiet docker; systemctl is-active --quiet sahjony-whatsapp-hostinger.timer; /usr/local/sbin/sahjony-whatsapp-guardian audit; echo SAHJONY_HOSTINGER_OPENCLAW_LOCAL_GATES=READY'
}

cleanup(){
  local rc=$?
  if [[ "$RECOVERY_OWNED" == true ]]; then
    log 'cleanup: attempting to exit owned Recovery session'
    set +e; exit_recovery; set -e
  fi
  exit "$rc"
}
trap cleanup EXIT INT TERM

validate
case "$MODE" in
  diagnose)
    print_status
    ;;
  repair-ssh)
    repair_ssh_if_needed
    print_status
    ;;
  heal-runtime)
    heal_runtime
    ;;
  full)
    repair_ssh_if_needed
    heal_runtime
    print_status
    ;;
esac
