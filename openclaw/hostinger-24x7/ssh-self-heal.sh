#!/usr/bin/env bash
set -euo pipefail

# SAHJONY Hostinger Kali SSH Self-Heal
# Repairs only the distro-native ssh.service. It never starts a competing sshd.
# Usage:
#   sudo ./ssh-self-heal.sh                 # live system
#   ROOT_PREFIX=/mnt/sdb1 ./ssh-self-heal.sh # offline mounted root from Recovery

ROOT_PREFIX="${ROOT_PREFIX:-/}"
MODE="${1:-repair}"

log() { printf '[sahjony-ssh-self-heal] %s\n' "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

rp() {
  local p="$1"
  if [[ "$ROOT_PREFIX" == "/" ]]; then printf '%s' "$p"; else printf '%s%s' "${ROOT_PREFIX%/}" "$p"; fi
}

is_live=false
[[ "$ROOT_PREFIX" == "/" ]] && is_live=true

require_root() {
  [[ "$(id -u)" -eq 0 ]] || fail "must run as root"
}

remove_competing_units() {
  log "removing legacy competing SSH units"
  local unit="$(rp /etc/systemd/system/sahjony-sshd.service)"
  rm -f "$unit"
  rm -f "$(rp /etc/systemd/system/multi-user.target.wants/sahjony-sshd.service)"
  rm -f "$(rp /etc/systemd/system/graphical.target.wants/sahjony-sshd.service)"
  rm -f "$(rp /etc/systemd/system/rescue.target.wants/sahjony-sshd.service)"
  rm -f "$(rp /etc/systemd/system/emergency.target.wants/sahjony-sshd.service)"
}

remove_kill_switches() {
  rm -f "$(rp /etc/ssh/sshd_not_to_be_run)"
  for u in ssh.service sshd.service ssh.socket; do
    local p="$(rp /etc/systemd/system/$u)"
    if [[ -L "$p" ]] && [[ "$(readlink "$p" 2>/dev/null || true)" == "/dev/null" ]]; then
      log "unmasking $u"
      rm -f "$p"
    fi
  done
}

install_native_config() {
  install -d -m 0755 "$(rp /etc/ssh/sshd_config.d)"
  cat > "$(rp /etc/ssh/sshd_config.d/99-sahjony-native.conf)" <<'EOF'
Port 22
AddressFamily any
ListenAddress 0.0.0.0
PubkeyAuthentication yes
PermitRootLogin prohibit-password
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
  chmod 0600 "$(rp /etc/ssh/sshd_config.d/99-sahjony-native.conf)"

  # Defensive creation of the privilege-separation directory at boot.
  install -d -m 0755 "$(rp /etc/tmpfiles.d)"
  cat > "$(rp /etc/tmpfiles.d/sahjony-sshd.conf)" <<'EOF'
d /run/sshd 0755 root root -
EOF

  # Add a native ssh.service override; do not replace ExecStart or RuntimeDirectory.
  install -d -m 0755 "$(rp /etc/systemd/system/ssh.service.d)"
  cat > "$(rp /etc/systemd/system/ssh.service.d/20-sahjony-self-heal.conf)" <<'EOF'
[Service]
ExecStartPre=/usr/bin/install -d -m 0755 -o root -g root /run/sshd
Restart=on-failure
RestartSec=5s
EOF
}

install_watchdog() {
  install -d -m 0755 "$(rp /usr/local/sbin)"
  cat > "$(rp /usr/local/sbin/sahjony-ssh-runtime-guard)" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
install -d -m 0755 -o root -g root /run/sshd
/usr/sbin/sshd -t
if ! systemctl is-active --quiet ssh.service; then
  systemctl restart ssh.service
fi
if ! ss -lnt '( sport = :22 )' | grep -q ':22'; then
  systemctl restart ssh.service
  sleep 2
fi
ss -lnt '( sport = :22 )' | grep -q ':22'
EOF
  chmod 0755 "$(rp /usr/local/sbin/sahjony-ssh-runtime-guard)"

  cat > "$(rp /etc/systemd/system/sahjony-ssh-runtime-guard.service)" <<'EOF'
[Unit]
Description=SAHJONY native SSH runtime self-heal
After=network.target ssh.service
Wants=ssh.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sahjony-ssh-runtime-guard
EOF

  cat > "$(rp /etc/systemd/system/sahjony-ssh-runtime-guard.timer)" <<'EOF'
[Unit]
Description=Run SAHJONY native SSH self-heal every two minutes

[Timer]
OnBootSec=45s
OnUnitActiveSec=2min
AccuracySec=15s
Persistent=true
Unit=sahjony-ssh-runtime-guard.service

[Install]
WantedBy=timers.target
EOF
}

enable_native_service_offline() {
  install -d -m 0755 "$(rp /etc/systemd/system/multi-user.target.wants)"
  local native=""
  for candidate in /lib/systemd/system/ssh.service /usr/lib/systemd/system/ssh.service; do
    [[ -f "$(rp "$candidate")" ]] && { native="$candidate"; break; }
  done
  [[ -n "$native" ]] || fail "native ssh.service not found"
  ln -sfn "$native" "$(rp /etc/systemd/system/multi-user.target.wants/ssh.service)"

  install -d -m 0755 "$(rp /etc/systemd/system/timers.target.wants)"
  ln -sfn ../sahjony-ssh-runtime-guard.timer "$(rp /etc/systemd/system/timers.target.wants/sahjony-ssh-runtime-guard.timer)"
}

validate_offline() {
  [[ -x "$(rp /usr/sbin/sshd)" ]] || fail "sshd binary missing"
  chroot "$ROOT_PREFIX" /usr/bin/ssh-keygen -A >/dev/null 2>&1 || true
  chroot "$ROOT_PREFIX" /usr/sbin/sshd -t
  log "offline sshd configuration validates"
}

repair_live() {
  install -d -m 0755 -o root -g root /run/sshd
  ssh-keygen -A >/dev/null 2>&1 || true
  /usr/sbin/sshd -t
  systemctl daemon-reload
  systemctl unmask ssh.service sshd.service 2>/dev/null || true
  systemctl enable ssh.service >/dev/null 2>&1 || true
  systemctl restart ssh.service
  systemctl enable --now sahjony-ssh-runtime-guard.timer >/dev/null 2>&1
  sleep 2
  systemctl is-active --quiet ssh.service || fail "native ssh.service is not active"
  ss -lnt '( sport = :22 )' | grep -q ':22' || fail "TCP/22 is not listening"
  log "LIVE_SSH_READY=1"
}

status_live() {
  echo '=== ssh.service ==='
  systemctl status ssh.service --no-pager || true
  echo '=== runtime guard ==='
  systemctl status sahjony-ssh-runtime-guard.timer --no-pager || true
  echo '=== listeners ==='
  ss -lntp '( sport = :22 )' || true
  echo '=== /run/sshd ==='
  stat /run/sshd || true
  echo '=== competing units ==='
  systemctl status sahjony-sshd.service --no-pager 2>/dev/null || true
}

require_root

if [[ "$MODE" == "status" ]]; then
  $is_live || fail "status mode requires live root"
  status_live
  exit 0
fi

remove_competing_units
remove_kill_switches
install_native_config
install_watchdog

if $is_live; then
  repair_live
  status_live
else
  enable_native_service_offline
  validate_offline
  log "OFFLINE_SSH_REPAIR_READY=1"
fi
