#!/usr/bin/env bash
set -euo pipefail

# Run this script INSIDE Hostinger Recovery. It modifies only the mounted
# authorized SAHJONY Kali installation and never alters WhatsApp pairing state.
# Required inputs are local files on the Recovery environment.
EPHEMERAL_PUBKEY_FILE="${EPHEMERAL_PUBKEY_FILE:-/tmp/sahjony-recovery.pub}"
DURABLE_PUBKEY_FILE="${DURABLE_PUBKEY_FILE:-/tmp/sahjony-durable.pub}"
GUARDIAN_FILE="${GUARDIAN_FILE:-/tmp/whatsapp-hostinger-only-guardian.sh}"
TARGET_ROOT="${TARGET_ROOT:-}"

log(){ printf '[sahjony-recovery-seed] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || fail 'run as root inside Hostinger Recovery'
[[ -s "$EPHEMERAL_PUBKEY_FILE" ]] || fail "missing ephemeral public key: $EPHEMERAL_PUBKEY_FILE"
[[ -s "$GUARDIAN_FILE" ]] || fail "missing guardian: $GUARDIAN_FILE"

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
  for candidate in /mnt /mnt/sdb1 /mnt/vps /mnt/root; do
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
log "ORIGINAL_KALI_ROOT=$root"

# Preserve access without enabling password login.
install -d -m 700 "$root/root/.ssh"
touch "$root/root/.ssh/authorized_keys"
chmod 600 "$root/root/.ssh/authorized_keys"
for keyfile in "$EPHEMERAL_PUBKEY_FILE" "$DURABLE_PUBKEY_FILE"; do
  [[ -s "$keyfile" ]] || continue
  key="$(tr -d '\r\n' < "$keyfile")"
  [[ -n "$key" ]] || continue
  grep -qxF "$key" "$root/root/.ssh/authorized_keys" || printf '%s\n' "$key" >> "$root/root/.ssh/authorized_keys"
done

# Force a conservative, key-only SSH configuration on port 22.
install -d -m 755 "$root/etc/ssh/sshd_config.d" "$root/run/sshd"
cat > "$root/etc/ssh/sshd_config.d/99-sahjony-hostinger-rescue.conf" <<'EOF'
Port 22
AddressFamily any
ListenAddress 0.0.0.0
ListenAddress ::
PubkeyAuthentication yes
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
chmod 600 "$root/etc/ssh/sshd_config.d/99-sahjony-hostinger-rescue.conf"

[[ -x "$root/usr/sbin/sshd" ]] || fail 'sshd binary is missing from the original Kali installation'
chroot "$root" /usr/bin/ssh-keygen -A >/dev/null 2>&1 || true
chroot "$root" /usr/sbin/sshd -t || fail 'sshd configuration validation failed'

# Install the Hostinger/OpenClaw guardian now, before normal SSH is needed.
install -d -m 700 "$root/opt/sahjony-openclaw"
install -m 700 "$GUARDIAN_FILE" "$root/opt/sahjony-openclaw/whatsapp-hostinger-only-guardian.sh"

# Persistent first/each-boot rescue agent. It is deliberately idempotent and
# never creates/re-pairs/logs out a WhatsApp session.
cat > "$root/usr/local/sbin/sahjony-hostinger-boot-rescue" <<'BOOT'
#!/usr/bin/env bash
set -uo pipefail
STATE_DIR=/var/lib/sahjony-hostinger-boot-rescue
LOG=/var/log/sahjony-hostinger-boot-rescue.log
mkdir -p "$STATE_DIR" /run/sshd
chmod 700 "$STATE_DIR" 2>/dev/null || true
exec >>"$LOG" 2>&1
printf '[%s] boot rescue start\n' "$(date -u +%FT%TZ)"

ssh_unit=''
for unit in ssh.service sshd.service; do
  if systemctl cat "$unit" >/dev/null 2>&1; then ssh_unit="$unit"; break; fi
done
if [[ -n "$ssh_unit" ]]; then
  ssh-keygen -A >/dev/null 2>&1 || true
  if /usr/sbin/sshd -t >/dev/null 2>&1; then
    systemctl unmask "$ssh_unit" >/dev/null 2>&1 || true
    systemctl enable "$ssh_unit" >/dev/null 2>&1 || true
    systemctl restart "$ssh_unit" >/dev/null 2>&1 || systemctl start "$ssh_unit" >/dev/null 2>&1 || true
  fi
fi

# Only touch high-level firewalls when they are already installed/active.
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q '^Status: active'; then
  ufw allow 22/tcp >/dev/null 2>&1 || true
fi
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-service=ssh >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true
fi

systemctl unmask docker.service >/dev/null 2>&1 || true
systemctl enable docker.service >/dev/null 2>&1 || true
systemctl start docker.service >/dev/null 2>&1 || true

container=''
if command -v docker >/dev/null 2>&1; then
  container="$(docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null | awk -F'|' 'tolower($0) ~ /openclaw|claw/ {print $1; exit}')"
fi
if [[ -n "$container" ]]; then
  docker update --restart unless-stopped "$container" >/dev/null 2>&1 || true
  [[ "$(docker inspect "$container" --format '{{.State.Running}}' 2>/dev/null || true)" == true ]] || docker start "$container" >/dev/null 2>&1 || true
fi

GUARD=/opt/sahjony-openclaw/whatsapp-hostinger-only-guardian.sh
if [[ -x "$GUARD" ]]; then
  "$GUARD" install >/dev/null 2>&1 || true
  "$GUARD" heal >/dev/null 2>&1 || true
fi

ssh_active=false; docker_active=false; container_running=false; guardian_timer=false
[[ -n "$ssh_unit" ]] && systemctl is-active --quiet "$ssh_unit" && ssh_active=true || true
systemctl is-active --quiet docker.service && docker_active=true || true
[[ -n "$container" ]] && [[ "$(docker inspect "$container" --format '{{.State.Running}}' 2>/dev/null || true)" == true ]] && container_running=true || true
systemctl is-active --quiet sahjony-whatsapp-hostinger.timer && guardian_timer=true || true

printf '{"at":"%s","ssh_active":%s,"docker_active":%s,"openclaw_container_running":%s,"guardian_timer":%s}\n' \
  "$(date -u +%FT%TZ)" "$ssh_active" "$docker_active" "$container_running" "$guardian_timer" > "$STATE_DIR/status.json"
printf '[%s] boot rescue end ssh=%s docker=%s openclaw=%s guardian=%s\n' "$(date -u +%FT%TZ)" "$ssh_active" "$docker_active" "$container_running" "$guardian_timer"
BOOT
chmod 700 "$root/usr/local/sbin/sahjony-hostinger-boot-rescue"

cat > "$root/etc/systemd/system/sahjony-hostinger-boot-rescue.service" <<'UNIT'
[Unit]
Description=SAHJONY Hostinger boot rescue for SSH Docker OpenClaw WhatsApp
After=local-fs.target network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sahjony-hostinger-boot-rescue
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
UNIT

# Enable boot rescue and native services by filesystem symlink, avoiding a
# dependency on a running systemd instance inside Recovery/chroot.
install -d "$root/etc/systemd/system/multi-user.target.wants"
ln -sfn /etc/systemd/system/sahjony-hostinger-boot-rescue.service \
  "$root/etc/systemd/system/multi-user.target.wants/sahjony-hostinger-boot-rescue.service"

ssh_enabled=false
for unit in ssh.service sshd.service; do
  src=''
  for base in "$root/lib/systemd/system" "$root/usr/lib/systemd/system"; do
    [[ -f "$base/$unit" ]] && { src="/${base#"$root/"}/$unit"; break; }
  done
  if [[ -n "$src" ]]; then
    ln -sfn "$src" "$root/etc/systemd/system/multi-user.target.wants/$unit"
    log "SSH_UNIT_ENABLED=$unit"
    ssh_enabled=true
    break
  fi
done
[[ "$ssh_enabled" == true ]] || fail 'no ssh.service or sshd.service unit found'

for unit in docker.service containerd.service; do
  for base in "$root/lib/systemd/system" "$root/usr/lib/systemd/system"; do
    if [[ -f "$base/$unit" ]]; then
      ln -sfn "/${base#"$root/"}/$unit" "$root/etc/systemd/system/multi-user.target.wants/$unit"
      log "ENABLED=$unit"
      break
    fi
  done
done

sync
log 'RECOVERY_SEEDED_BOOT_RESCUE=READY'
log 'Normal boot can now repair SSH/Docker/OpenClaw without requiring pre-existing normal SSH access.'
