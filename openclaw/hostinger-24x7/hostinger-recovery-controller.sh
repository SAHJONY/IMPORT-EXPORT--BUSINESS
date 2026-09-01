#!/usr/bin/env bash
set -euo pipefail

# SAHJONY Hostinger Recovery Controller
# Canonical recovery surface for the authorized Kali VPS.
#
# Principles:
# - one Hostinger mutation owner at a time;
# - native ssh.service only (never a competing sshd);
# - /run/sshd is repaired persistently, not only in an offline /run tree;
# - local Docker only (Hostinger Docker Manager is unsupported on Kali);
# - preserve existing OpenClaw/WhatsApp state;
# - reconstruct a missing OpenClaw runtime only from one unambiguous retained
#   compose definition backed by non-empty host bind state.

MODE="${1:-diagnose}"
API_BASE="${HOSTINGER_API_BASE:-https://developers.hostinger.com}"
VM_ID="${HOSTINGER_VM_ID:-}"
HOST="${HOSTINGER_HOST:-}"
USER_NAME="${HOSTINGER_USER:-root}"
TOKEN="${HOSTINGER_API_TOKEN:-}"
SSH_KEY_PATH="${SSH_KEY_PATH:-}"
SELF_HEAL_LOCAL_PATH="${SELF_HEAL_LOCAL_PATH:-openclaw/hostinger-24x7/ssh-self-heal.sh}"
RUNTIME_BOOTSTRAP_LOCAL_PATH="${RUNTIME_BOOTSTRAP_LOCAL_PATH:-openclaw/hostinger-24x7/hostinger-runtime-bootstrap.sh}"
RUNTIME_RECOVERY_LOCAL_PATH="${RUNTIME_RECOVERY_LOCAL_PATH:-openclaw/hostinger-24x7/openclaw-runtime-recovery.sh}"
GUARDIAN_LOCAL_PATH="${GUARDIAN_LOCAL_PATH:-openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh}"
STATE_DIR="${SAHJONY_CONTROLLER_STATE_DIR:-/tmp/sahjony-hostinger-controller}"
ALLOW_RECONSTRUCT="${SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT:-}"
RECOVERY_OWNED=false
RECOVERY_PASSWORD=""
GENERATED_KEY=false

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR" || true

log(){ printf '[hostinger-controller] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

validate(){
  [[ "$MODE" =~ ^(diagnose|repair-ssh|inspect-runtime|heal-runtime|reconstruct-runtime|full)$ ]] || \
    fail 'mode must be diagnose, repair-ssh, inspect-runtime, heal-runtime, reconstruct-runtime, or full'
  [[ -n "$VM_ID" ]] || fail 'HOSTINGER_VM_ID is required'
  [[ -n "$HOST" ]] || fail 'HOSTINGER_HOST is required'
  [[ -n "$TOKEN" ]] || fail 'HOSTINGER_API_TOKEN is required'
  need curl; need jq; need ssh; need scp; need nc; need base64; need openssl; need ssh-keygen

  for f in "$SELF_HEAL_LOCAL_PATH" "$RUNTIME_BOOTSTRAP_LOCAL_PATH" "$RUNTIME_RECOVERY_LOCAL_PATH" "$GUARDIAN_LOCAL_PATH"; do
    [[ -f "$f" ]] || fail "required recovery tool missing: $f"
    bash -n "$f" || fail "syntax validation failed: $f"
  done
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

remote(){
  local -a opts=(); mapfile -t opts < <(ssh_opts)
  ssh "${opts[@]}" -i "$SSH_KEY_PATH" "$USER_NAME@$HOST" "$@"
}

copy_remote(){
  local src="$1" dst="$2"; shift 2 || true
  local -a opts=(); mapfile -t opts < <(ssh_opts)
  scp "${opts[@]}" -i "$SSH_KEY_PATH" "$src" "$USER_NAME@$HOST:$dst"
}

prepare_management_key(){
  if [[ -n "$SSH_KEY_PATH" && -f "$SSH_KEY_PATH" ]]; then
    chmod 600 "$SSH_KEY_PATH" || true
    if [[ ! -s "$SSH_KEY_PATH.pub" ]]; then
      ssh-keygen -y -f "$SSH_KEY_PATH" > "$SSH_KEY_PATH.pub" || fail 'could not derive public key from configured SSH key'
    fi
    return 0
  fi
  SSH_KEY_PATH="$STATE_DIR/hostinger-controller-key"
  rm -f "$SSH_KEY_PATH" "$SSH_KEY_PATH.pub"
  ssh-keygen -q -t ed25519 -N '' -f "$SSH_KEY_PATH" -C "sahjony-controller-$(date +%s)"
  GENERATED_KEY=true
}

print_status(){
  local tcp=false auth=false busy self_heal=false docker=false openclaw_count=0
  tcp22 && tcp=true || true
  normal_ssh && auth=true || true
  busy="$(busy_action_count 2>/dev/null || echo unknown)"
  if [[ "$auth" == true ]]; then
    remote 'systemctl is-active --quiet sahjony-ssh-runtime-guard.timer' >/dev/null 2>&1 && self_heal=true || true
    remote 'systemctl is-active --quiet docker.service' >/dev/null 2>&1 && docker=true || true
    openclaw_count="$(remote 'if command -v docker >/dev/null 2>&1; then docker ps -a --format "{{.Names}}|{{.Image}}" 2>/dev/null | grep -Eic "openclaw|open[-_ ]?claw|claw" || true; else echo 0; fi' 2>/dev/null | tail -n1 || echo 0)"
    [[ "$openclaw_count" =~ ^[0-9]+$ ]] || openclaw_count=0
  fi
  jq -n \
    --arg host "$HOST" --arg vm "$VM_ID" --arg busy "$busy" \
    --argjson tcp "$tcp" --argjson auth "$auth" --argjson self_heal "$self_heal" \
    --argjson docker "$docker" --argjson openclaw_count "$openclaw_count" \
    '{host:$host,vm_id:$vm,hostinger_busy_actions:$busy,tcp22:$tcp,normal_ssh_authenticated:$auth,ssh_self_heal_timer:$self_heal,docker_active:$docker,openclaw_container_count:$openclaw_count,docker_manager_required:false,meta_cloud_required:false}'
}

wait_action(){
  local id="$1" label="$2"
  for i in $(seq 1 120); do
    local a s
    a="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/actions/$id")"
    s="$(jq -r '.state // empty' <<<"$a")"
    log "$label probe=$i/120 state=${s:-unknown}"
    case "$s" in
      success) return 0 ;;
      failed|failure|error|cancelled|canceled) jq -c . <<<"$a" >&2; return 1 ;;
    esac
    sleep 5
  done
  return 1
}

enter_recovery(){
  require_idle_action_plane
  RECOVERY_PASSWORD="$(openssl rand -hex 18)Aa1!"
  log 'Entering one owned Hostinger Recovery session'
  local payload body id
  payload="$(jq -n --arg p "$RECOVERY_PASSWORD" '{root_password:$p}')"
  body="$(api POST "/api/vps/v1/virtual-machines/$VM_ID/recovery" "$payload")"
  id="$(jq -r '.id // empty' <<<"$body")"
  [[ "$id" =~ ^[0-9]+$ ]] || fail 'Recovery start action id missing'
  RECOVERY_OWNED=true
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
    if recovery_ssh 'printf RECOVERY_OK' 2>/dev/null | grep -q RECOVERY_OK; then
      log "Recovery SSH authenticated at probe $i"
      return 0
    fi
    sleep 10
  done
  return 1
}

repair_original_kali_ssh(){
  prepare_management_key
  wait_recovery_ssh || fail 'Recovery SSH authentication failed'
  local pub_b64 self_heal_b64
  pub_b64="$(base64 -w0 "$SSH_KEY_PATH.pub")"
  self_heal_b64="$(base64 -w0 "$SELF_HEAL_LOCAL_PATH")"

  recovery_ssh "PUB_B64='$pub_b64' SELF_HEAL_B64='$self_heal_b64' bash -s" <<'REMOTE'
set -euo pipefail
root=''
for mp in /mnt/sdb1 /mnt /mnt/vps /mnt/root; do
  if [[ -f "$mp/etc/os-release" && -x "$mp/usr/sbin/sshd" ]]; then root="$mp"; break; fi
done
if [[ -z "$root" ]]; then
  mkdir -p /mnt/sahjony-controller-discovery
  n=0
  while read -r dev fs type mp; do
    [[ "$type" == part || "$type" == lvm ]] || continue
    [[ "$fs" =~ ^(ext2|ext3|ext4|xfs|btrfs)$ ]] || continue
    [[ -z "${mp:-}" ]] || continue
    n=$((n+1)); target="/mnt/sahjony-controller-discovery/$n"; mkdir -p "$target"
    if [[ "$fs" == xfs ]]; then mount -o nouuid "$dev" "$target" 2>/dev/null || continue; else mount "$dev" "$target" 2>/dev/null || continue; fi
    if [[ -f "$target/etc/os-release" && -x "$target/usr/sbin/sshd" ]]; then root="$target"; break; fi
  done < <(lsblk -prno NAME,FSTYPE,TYPE,MOUNTPOINT 2>/dev/null || true)
fi
[[ -n "$root" ]] || { echo ORIGINAL_KALI_ROOT_NOT_FOUND=1 >&2; exit 20; }
echo "ORIGINAL_KALI_ROOT=$root"

install -d -m 700 "$root/root/.ssh"
touch "$root/root/.ssh/authorized_keys"
chmod 600 "$root/root/.ssh/authorized_keys"
pub="$(printf '%s' "$PUB_B64" | base64 -d)"
grep -qxF "$pub" "$root/root/.ssh/authorized_keys" || printf '%s\n' "$pub" >> "$root/root/.ssh/authorized_keys"

printf '%s' "$SELF_HEAL_B64" | base64 -d > /tmp/sahjony-ssh-self-heal
chmod 700 /tmp/sahjony-ssh-self-heal
install -d -m 755 "$root/usr/local/sbin"
install -m 755 /tmp/sahjony-ssh-self-heal "$root/usr/local/sbin/sahjony-ssh-self-heal"
ROOT_PREFIX="$root" /tmp/sahjony-ssh-self-heal

# Keep an already-enabled firewall compatible with SSH; never disable it.
if [[ -x "$root/usr/sbin/ufw" ]]; then
  chroot "$root" /usr/sbin/ufw allow 22/tcp >/dev/null 2>&1 || true
fi

chroot "$root" /usr/sbin/sshd -t
test ! -e "$root/etc/systemd/system/sahjony-sshd.service"
test -f "$root/etc/tmpfiles.d/sahjony-sshd.conf"
test -f "$root/etc/systemd/system/ssh.service.d/20-sahjony-self-heal.conf"
test -f "$root/etc/systemd/system/sahjony-ssh-runtime-guard.timer"
test -L "$root/etc/systemd/system/multi-user.target.wants/ssh.service"
test -L "$root/etc/systemd/system/timers.target.wants/sahjony-ssh-runtime-guard.timer"
sync
echo SAHJONY_OFFLINE_NATIVE_SSH_SELF_HEAL_INSTALLED=1
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
    if tcp22 && normal_ssh; then
      log "normal Kali SSH authenticated at probe $i"
      return 0
    fi
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

activate_live_ssh_self_heal(){
  normal_ssh || fail 'normal SSH is required to activate live SSH self-heal'
  copy_remote "$SELF_HEAL_LOCAL_PATH" /tmp/sahjony-ssh-self-heal
  remote 'set -euo pipefail; install -m 755 /tmp/sahjony-ssh-self-heal /usr/local/sbin/sahjony-ssh-self-heal; /usr/local/sbin/sahjony-ssh-self-heal; systemctl is-active --quiet ssh.service; systemctl is-enabled --quiet ssh.service; systemctl is-active --quiet sahjony-ssh-runtime-guard.timer; systemctl is-enabled --quiet sahjony-ssh-runtime-guard.timer; test -d /run/sshd; test ! -e /etc/systemd/system/sahjony-sshd.service; /usr/sbin/sshd -t; ss -lnt "( sport = :22 )" | grep -q :22; echo SAHJONY_NATIVE_SSH_SELF_HEAL=READY'
}

repair_ssh_if_needed(){
  prepare_management_key
  if normal_ssh; then
    log 'normal SSH already authenticates; enforcing durable native SSH self-heal without Recovery'
    activate_live_ssh_self_heal
    return 0
  fi

  enter_recovery
  repair_original_kali_ssh
  exit_recovery

  if ! wait_normal_ssh; then
    log 'normal SSH still unavailable; issuing one bounded VPS restart'
    one_bounded_restart
    wait_normal_ssh || fail 'normal SSH unavailable after targeted self-heal + one restart'
  fi
  activate_live_ssh_self_heal
}

install_runtime_tools(){
  normal_ssh || fail 'normal SSH is required before installing runtime recovery tools'
  copy_remote "$RUNTIME_BOOTSTRAP_LOCAL_PATH" /tmp/sahjony-runtime-bootstrap
  copy_remote "$RUNTIME_RECOVERY_LOCAL_PATH" /tmp/sahjony-openclaw-runtime-recovery
  copy_remote "$GUARDIAN_LOCAL_PATH" /tmp/sahjony-whatsapp-guardian
  remote 'set -euo pipefail; install -m 700 /tmp/sahjony-runtime-bootstrap /usr/local/sbin/sahjony-runtime-bootstrap; install -m 700 /tmp/sahjony-openclaw-runtime-recovery /usr/local/sbin/sahjony-openclaw-runtime-recovery; install -m 700 /tmp/sahjony-whatsapp-guardian /usr/local/sbin/sahjony-whatsapp-guardian; bash -n /usr/local/sbin/sahjony-runtime-bootstrap; bash -n /usr/local/sbin/sahjony-openclaw-runtime-recovery; bash -n /usr/local/sbin/sahjony-whatsapp-guardian; echo SAHJONY_RUNTIME_TOOLS_INSTALLED=1'
}

ensure_local_docker(){
  normal_ssh || fail 'normal SSH authentication is required before Docker recovery'
  if remote 'command -v docker >/dev/null 2>&1 && systemctl is-active --quiet docker.service' >/dev/null 2>&1; then
    return 0
  fi

  # The bootstrap is conservative: it installs docker.io only when retained
  # runtime/OpenClaw evidence exists. Exit 24 after Docker restoration is an
  # expected classification when container metadata is absent.
  set +e
  remote '/usr/local/sbin/sahjony-runtime-bootstrap heal'
  local rc=$?
  set -e
  if (( rc != 0 )); then log "runtime bootstrap returned rc=$rc; checking whether Docker itself was safely restored"; fi
  remote 'command -v docker >/dev/null 2>&1 && systemctl is-active --quiet docker.service' || \
    fail 'Docker engine could not be safely restored from retained-runtime evidence'
}

openclaw_container_count(){
  remote 'if command -v docker >/dev/null 2>&1; then docker ps -a --format "{{.Names}}|{{.Image}}" 2>/dev/null | grep -Eic "openclaw|open[-_ ]?claw|claw" || true; else echo 0; fi' | tail -n1
}

heal_existing_openclaw(){
  ensure_local_docker
  local count
  count="$(openclaw_container_count)"
  [[ "$count" =~ ^[0-9]+$ ]] || fail 'could not classify OpenClaw container count'
  (( count == 1 )) || {
    (( count == 0 )) && fail 'no retained OpenClaw container exists in Docker metadata; run inspect-runtime or reconstruct-runtime'
    fail "OpenClaw container ambiguity: $count candidates"
  }

  remote 'set -euo pipefail; cid="$(docker ps -aq | while read -r id; do meta="$(docker inspect "$id" --format "{{.Name}}|{{.Config.Image}}" 2>/dev/null || true)"; grep -Eqi "openclaw|open[-_ ]?claw|claw" <<<"$meta" && echo "$id" || true; done | head -n1)"; test -n "$cid"; docker update --restart unless-stopped "$cid" >/dev/null; test "$(docker inspect "$cid" --format "{{.State.Running}}")" = true || docker start "$cid" >/dev/null; /usr/local/sbin/sahjony-whatsapp-guardian install; systemctl is-active --quiet sahjony-whatsapp-hostinger.timer; docker exec "$cid" sh -lc "openclaw channels status --probe"; echo "OPENCLAW_CONTAINER=$cid"; echo SAHJONY_HOSTINGER_OPENCLAW_LOCAL_GATES=READY'
}

inspect_runtime(){
  prepare_management_key
  normal_ssh || fail 'normal SSH authentication is required for runtime inspection'
  activate_live_ssh_self_heal
  install_runtime_tools
  remote '/usr/local/sbin/sahjony-openclaw-runtime-recovery audit'
  set +e
  remote '/usr/local/sbin/sahjony-openclaw-runtime-recovery plan'
  local rc=$?
  set -e
  case "$rc" in
    0) log 'runtime plan found a usable existing container or one safe reconstruction candidate' ;;
    24|25) log "runtime plan requires further forensic resolution (rc=$rc); no reconstruction performed" ;;
    *) fail "runtime planning failed unexpectedly (rc=$rc)" ;;
  esac
}

reconstruct_runtime(){
  [[ "$ALLOW_RECONSTRUCT" == RECOVER_RETAINED_OPENCLAW ]] || \
    fail 'reconstruct-runtime requires SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT=RECOVER_RETAINED_OPENCLAW'
  prepare_management_key
  normal_ssh || fail 'normal SSH authentication is required before runtime reconstruction'
  activate_live_ssh_self_heal
  install_runtime_tools
  ensure_local_docker
  remote 'SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT=RECOVER_RETAINED_OPENCLAW /usr/local/sbin/sahjony-openclaw-runtime-recovery reconstruct'
  heal_existing_openclaw
}

full_recovery(){
  repair_ssh_if_needed
  install_runtime_tools
  ensure_local_docker
  local count
  count="$(openclaw_container_count)"
  [[ "$count" =~ ^[0-9]+$ ]] || fail 'could not classify OpenClaw container count'
  if (( count == 1 )); then
    heal_existing_openclaw
    return 0
  fi
  if (( count > 1 )); then
    fail "OpenClaw container ambiguity: $count candidates"
  fi

  log 'Docker is healthy but container metadata has no OpenClaw container; running evidence-based retained-runtime plan'
  set +e
  remote '/usr/local/sbin/sahjony-openclaw-runtime-recovery plan'
  local rc=$?
  set -e
  if [[ "$ALLOW_RECONSTRUCT" == RECOVER_RETAINED_OPENCLAW && "$rc" == 0 ]]; then
    reconstruct_runtime
    return 0
  fi
  case "$rc" in
    0)
      echo SAHJONY_OPENCLAW_RECONSTRUCTION_CANDIDATE_READY=1
      echo SAHJONY_OPENCLAW_RECONSTRUCTION_NOT_EXECUTED_WITHOUT_EXPLICIT_GATE=1
      ;;
    24|25)
      echo SAHJONY_OPENCLAW_RUNTIME_FORENSICS_REQUIRED=1
      ;;
    *) fail "runtime planning failed unexpectedly (rc=$rc)" ;;
  esac
}

remove_ephemeral_key_normal(){
  [[ "$GENERATED_KEY" == true && -f "$SSH_KEY_PATH.pub" ]] || return 0
  normal_ssh || return 0
  local pub_b64
  pub_b64="$(base64 -w0 "$SSH_KEY_PATH.pub")"
  remote "PUB_B64='$pub_b64' bash -s" <<'REMOTE'
set -euo pipefail
pub="$(printf '%s' "$PUB_B64" | base64 -d)"
file=/root/.ssh/authorized_keys
[[ -f "$file" ]] || exit 0
tmp="$(mktemp)"
grep -vxF "$pub" "$file" > "$tmp" || true
cat "$tmp" > "$file"
rm -f "$tmp"
chmod 600 "$file"
echo SAHJONY_EPHEMERAL_KEY_REMOVED=1
REMOTE
}

remove_ephemeral_key_offline(){
  [[ "$GENERATED_KEY" == true && -f "$SSH_KEY_PATH.pub" && "$RECOVERY_OWNED" == true ]] || return 0
  local pub_b64
  pub_b64="$(base64 -w0 "$SSH_KEY_PATH.pub")"
  recovery_ssh "PUB_B64='$pub_b64' bash -s" <<'REMOTE' || true
set -euo pipefail
root=''
for mp in /mnt/sdb1 /mnt /mnt/vps /mnt/root; do [[ -f "$mp/etc/os-release" ]] && root="$mp" && break; done
[[ -n "$root" ]] || exit 0
file="$root/root/.ssh/authorized_keys"
[[ -f "$file" ]] || exit 0
pub="$(printf '%s' "$PUB_B64" | base64 -d)"
tmp="$(mktemp)"
grep -vxF "$pub" "$file" > "$tmp" || true
cat "$tmp" > "$file"
rm -f "$tmp"
chmod 600 "$file"
REMOTE
}

cleanup(){
  local rc=$?
  set +e
  if [[ "$rc" -eq 0 ]]; then
    remove_ephemeral_key_normal
  elif [[ "$RECOVERY_OWNED" == true ]]; then
    remove_ephemeral_key_offline
  fi
  if [[ "$RECOVERY_OWNED" == true ]]; then
    log 'cleanup: attempting to exit owned Recovery session'
    exit_recovery
  fi
  if [[ "$GENERATED_KEY" == true ]]; then rm -f "$SSH_KEY_PATH" "$SSH_KEY_PATH.pub"; fi
  set -e
  exit "$rc"
}
trap cleanup EXIT INT TERM

validate
case "$MODE" in
  diagnose)
    prepare_management_key
    print_status
    ;;
  repair-ssh)
    repair_ssh_if_needed
    print_status
    ;;
  inspect-runtime)
    inspect_runtime
    print_status
    ;;
  heal-runtime)
    prepare_management_key
    normal_ssh || fail 'normal SSH authentication is required before runtime healing'
    activate_live_ssh_self_heal
    install_runtime_tools
    heal_existing_openclaw
    print_status
    ;;
  reconstruct-runtime)
    reconstruct_runtime
    print_status
    ;;
  full)
    full_recovery
    print_status
    ;;
esac
