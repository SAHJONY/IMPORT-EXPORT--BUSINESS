#!/usr/bin/env bash
set -euo pipefail

# SAHJONY Recovery Seed
# Run inside Hostinger Recovery. It seeds the mounted Kali OS so the NEXT normal
# boot can repair native ssh.service, retained Docker/OpenClaw and the WhatsApp
# guardian without requiring normal SSH to already work.
#
# Safety invariants:
# - one distro-native SSH daemon only; never starts a competing sshd
# - never creates a fresh OpenClaw container
# - never logs out, re-pairs, or replaces the authorized WhatsApp session
# - only restores retained Docker/OpenClaw state

EPHEMERAL_PUBKEY_FILE="${EPHEMERAL_PUBKEY_FILE:-/tmp/sahjony-recovery.pub}"
DURABLE_PUBKEY_FILE="${DURABLE_PUBKEY_FILE:-/tmp/sahjony-durable.pub}"
SELF_HEAL_FILE="${SELF_HEAL_FILE:-/tmp/ssh-self-heal.sh}"
RUNTIME_BOOTSTRAP_FILE="${RUNTIME_BOOTSTRAP_FILE:-/tmp/hostinger-runtime-bootstrap.sh}"
GUARDIAN_FILE="${GUARDIAN_FILE:-/tmp/whatsapp-hostinger-only-guardian.sh}"
TARGET_ROOT="${TARGET_ROOT:-}"

log(){ printf '[sahjony-recovery-seed] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || fail 'run as root inside Hostinger Recovery'
for f in "$EPHEMERAL_PUBKEY_FILE" "$SELF_HEAL_FILE" "$RUNTIME_BOOTSTRAP_FILE" "$GUARDIAN_FILE"; do
  [[ -s "$f" ]] || fail "required seed input missing: $f"
done
bash -n "$SELF_HEAL_FILE"
bash -n "$RUNTIME_BOOTSTRAP_FILE"
bash -n "$GUARDIAN_FILE"

mount_candidates(){
  mkdir -p /mnt/sahjony-discovery
  local n=0 dev fs mp type t
  while read -r dev fs mp type; do
    case "$type:$fs" in
      part:ext2|part:ext3|part:ext4|part:xfs|part:btrfs|lvm:ext2|lvm:ext3|lvm:ext4|lvm:xfs|lvm:btrfs) ;;
      *) continue ;;
    esac
    [[ -n "${mp:-}" ]] && continue
    n=$((n+1)); t="/mnt/sahjony-discovery/$n"; mkdir -p "$t"
    case "$fs" in
      xfs) mount -o nouuid "$dev" "$t" 2>/dev/null || true ;;
      *) mount "$dev" "$t" 2>/dev/null || true ;;
    esac
  done < <(lsblk -prno NAME,FSTYPE,MOUNTPOINT,TYPE 2>/dev/null || true)
}

discover_root(){
  local candidate
  if [[ -n "$TARGET_ROOT" && -f "$TARGET_ROOT/etc/os-release" ]]; then printf '%s' "$TARGET_ROOT"; return 0; fi
  for candidate in /mnt/sdb1 /mnt/vps /mnt/root /mnt; do
    if [[ -f "$candidate/etc/os-release" && -d "$candidate/etc/ssh" && -d "$candidate/root" ]]; then printf '%s' "$candidate"; return 0; fi
  done
  mount_candidates
  while read -r candidate; do
    [[ "$candidate" == / ]] && continue
    if [[ -f "$candidate/etc/os-release" && -d "$candidate/etc/ssh" && -d "$candidate/root" ]]; then printf '%s' "$candidate"; return 0; fi
  done < <(findmnt -rn -o TARGET | sort -u)
  return 1
}

root="$(discover_root || true)"
[[ -n "$root" ]] || fail 'original Kali root filesystem not found'
[[ "$root" != / ]] || fail 'refusing to treat Recovery root as target OS'
log "ORIGINAL_KALI_ROOT=$root"

# Install the run key and, when supplied, the durable management key.
install -d -m 0700 "$root/root/.ssh"
touch "$root/root/.ssh/authorized_keys"
chmod 0600 "$root/root/.ssh/authorized_keys"
for keyfile in "$EPHEMERAL_PUBKEY_FILE" "$DURABLE_PUBKEY_FILE"; do
  [[ -s "$keyfile" ]] || continue
  key="$(tr -d '\r\n' < "$keyfile")"
  [[ -n "$key" ]] || continue
  grep -qxF "$key" "$root/root/.ssh/authorized_keys" || printf '%s\n' "$key" >> "$root/root/.ssh/authorized_keys"
done

# Remove the older seed-specific config if present. The canonical SSH policy is
# now owned exclusively by ssh-self-heal.sh.
rm -f "$root/etc/ssh/sshd_config.d/99-sahjony-hostinger-rescue.conf"

# Install canonical repair engines into the target OS before normal boot.
install -d -m 0755 "$root/usr/local/sbin"
install -m 0755 "$SELF_HEAL_FILE" "$root/usr/local/sbin/sahjony-ssh-self-heal"
install -m 0755 "$RUNTIME_BOOTSTRAP_FILE" "$root/usr/local/sbin/sahjony-runtime-bootstrap"
install -m 0755 "$GUARDIAN_FILE" "$root/usr/local/sbin/sahjony-whatsapp-hostinger"

# Repair/enable only the distro-native ssh.service against the mounted root.
ROOT_PREFIX="$root" "$SELF_HEAL_FILE" repair

# Seed one idempotent normal-boot orchestrator. Runtime failures do not suppress
# SSH repair; all subsystem outcomes are recorded independently.
cat > "$root/usr/local/sbin/sahjony-hostinger-boot-rescue" <<'BOOT'
#!/usr/bin/env bash
set -uo pipefail
STATE_DIR=/var/lib/sahjony-hostinger-boot-rescue
LOG=/var/log/sahjony-hostinger-boot-rescue.log
install -d -m 0700 "$STATE_DIR"
exec >>"$LOG" 2>&1
printf '[%s] boot-rescue start\n' "$(date -u +%FT%TZ)"

ssh_ok=false
runtime_ok=false
guardian_ok=false
whatsapp_probe=false

if /usr/local/sbin/sahjony-ssh-self-heal repair; then ssh_ok=true; fi
if /usr/local/sbin/sahjony-runtime-bootstrap heal; then runtime_ok=true; fi
if /usr/local/sbin/sahjony-whatsapp-hostinger install && /usr/local/sbin/sahjony-whatsapp-hostinger heal; then guardian_ok=true; fi

# Direct local OpenClaw probe is authoritative when available. Never pair/logout.
if command -v openclaw >/dev/null 2>&1; then
  openclaw channels status --probe >/tmp/sahjony-openclaw-probe.out 2>&1 && whatsapp_probe=true || true
elif command -v docker >/dev/null 2>&1; then
  cid="$(docker ps -q --filter 'name=openclaw' 2>/dev/null | head -n1)"
  if [[ -z "$cid" ]]; then
    cid="$(docker ps --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null | awk -F'|' 'tolower($0) ~ /openclaw|claw/ {print $1; exit}')"
  fi
  if [[ -n "$cid" ]]; then
    docker exec "$cid" openclaw channels status --probe >/tmp/sahjony-openclaw-probe.out 2>&1 && whatsapp_probe=true || true
  fi
fi

cat > "$STATE_DIR/status.json" <<EOF
{"at":"$(date -u +%FT%TZ)","native_ssh":$ssh_ok,"retained_runtime":$runtime_ok,"guardian":$guardian_ok,"openclaw_probe":$whatsapp_probe}
EOF

printf '[%s] boot-rescue end ssh=%s runtime=%s guardian=%s probe=%s\n' \
  "$(date -u +%FT%TZ)" "$ssh_ok" "$runtime_ok" "$guardian_ok" "$whatsapp_probe"

# Management recovery is a hard boot-rescue gate. Runtime/WhatsApp remain
# independently observable and can be healed by their timers after boot.
[[ "$ssh_ok" == true ]]
BOOT
chmod 0755 "$root/usr/local/sbin/sahjony-hostinger-boot-rescue"

cat > "$root/etc/systemd/system/sahjony-hostinger-boot-rescue.service" <<'UNIT'
[Unit]
Description=SAHJONY Hostinger native boot rescue for SSH Docker OpenClaw WhatsApp
After=local-fs.target network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sahjony-hostinger-boot-rescue
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
UNIT

install -d -m 0755 "$root/etc/systemd/system/multi-user.target.wants"
ln -sfn /etc/systemd/system/sahjony-hostinger-boot-rescue.service \
  "$root/etc/systemd/system/multi-user.target.wants/sahjony-hostinger-boot-rescue.service"

# Docker gets enabled offline only when the package/unit already exists. We do
# not invent a new runtime in Recovery; hostinger-runtime-bootstrap decides live
# whether retained state justifies package restoration.
for candidate in /lib/systemd/system/docker.service /usr/lib/systemd/system/docker.service; do
  if [[ -f "$root$candidate" ]]; then
    ln -sfn "$candidate" "$root/etc/systemd/system/multi-user.target.wants/docker.service"
    break
  fi
done

# Final offline validation of the canonical SSH configuration.
chroot "$root" /usr/bin/ssh-keygen -A >/dev/null 2>&1 || true
chroot "$root" /usr/sbin/sshd -t
sync

log 'RECOVERY_SEEDED_BOOT_RESCUE=READY'
log 'NATIVE_SSH_SINGLE_DAEMON=1'
log 'RETAINED_OPENCLAW_ONLY=1'
log 'WHATSAPP_REPAIR_OR_LOGOUT_AUTOMATION=0'
