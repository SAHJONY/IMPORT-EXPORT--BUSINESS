#!/usr/bin/env bash
set -euo pipefail

PUB_FILE="${1:-}"
[[ -n "$PUB_FILE" && -s "$PUB_FILE" ]] || { echo RECOVERY_KEY_FILE_MISSING=1 >&2; exit 2; }

root=''
for mp in /mnt/sdb1 /mnt; do
  if [[ -f "$mp/etc/os-release" && -d "$mp/root" && -d "$mp/etc/ssh" ]]; then
    root="$mp"
    break
  fi
done

if [[ -z "$root" ]]; then
  mkdir -p /mnt/sahjony-discovery
  n=0
  while read -r dev fs mp type; do
    case "$type:$fs" in
      part:ext2|part:ext3|part:ext4|part:xfs|part:btrfs|lvm:ext2|lvm:ext3|lvm:ext4|lvm:xfs|lvm:btrfs) ;;
      *) continue ;;
    esac
    [[ -n "${mp:-}" ]] && continue
    n=$((n+1))
    target="/mnt/sahjony-discovery/$n"
    mkdir -p "$target"
    if [[ "$fs" == xfs ]]; then
      mount -o nouuid "$dev" "$target" 2>/dev/null || true
    else
      mount "$dev" "$target" 2>/dev/null || true
    fi
  done < <(lsblk -prno NAME,FSTYPE,MOUNTPOINT,TYPE 2>/dev/null)

  while read -r mp; do
    [[ "$mp" == / ]] && continue
    if [[ -f "$mp/etc/os-release" && -d "$mp/root" && -d "$mp/etc/ssh" ]]; then
      root="$mp"
      break
    fi
  done < <(findmnt -rn -o TARGET | sort -u)
fi

[[ -n "$root" ]] || { echo ORIGINAL_KALI_ROOT_NOT_FOUND=1 >&2; exit 20; }
echo "ORIGINAL_KALI_ROOT=$root"

install -d -m 700 "$root/root/.ssh"
touch "$root/root/.ssh/authorized_keys"
chmod 600 "$root/root/.ssh/authorized_keys"

# Remove only dead one-time SAHJONY recovery/bootstrap identities.
sed -i -E '/sahjony-(v7|v8|provider-bootstrap)-/d' "$root/root/.ssh/authorized_keys" || true
pub="$(cat "$PUB_FILE")"
printf '%s\n' "$pub" >> "$root/root/.ssh/authorized_keys"

install -d "$root/etc/ssh/sshd_config.d" "$root/run/sshd" "$root/etc/systemd/system/multi-user.target.wants"
cat > "$root/etc/ssh/sshd_config.d/99-sahjony-recovery-v8.conf" <<'EOF'
PubkeyAuthentication yes
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
chmod 600 "$root/etc/ssh/sshd_config.d/99-sahjony-recovery-v8.conf"

# Remove obsolete V7 drop-in to leave one authoritative SAHJONY SSH policy.
rm -f "$root/etc/ssh/sshd_config.d/99-sahjony-recovery-v7.conf"

enabled=false
for unit in ssh.service sshd.service; do
  target="$(find "$root/lib/systemd/system" "$root/usr/lib/systemd/system" -maxdepth 1 -name "$unit" -print -quit 2>/dev/null || true)"
  if [[ -n "$target" ]]; then
    ln -sfn "/${target#"$root/"}" "$root/etc/systemd/system/multi-user.target.wants/$unit"
    echo "SSH_UNIT_ENABLED=$unit"
    enabled=true
    break
  fi
done
[[ "$enabled" == true ]] || { echo SSH_SYSTEMD_UNIT_NOT_FOUND=1 >&2; exit 21; }

chroot "$root" /usr/bin/ssh-keygen -A 2>/dev/null || true
chroot "$root" /usr/sbin/sshd -t
chroot "$root" /usr/sbin/sshd -T 2>/dev/null | grep -E '^(permitrootlogin|pubkeyauthentication|passwordauthentication|authorizedkeysfile) ' || true
sync
echo ORIGINAL_KALI_SSH_V8_REPAIRED=1
