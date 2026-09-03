#!/usr/bin/env bash
set -Eeuo pipefail

# Installs the authorized SAHJONY CRM bridge and the WhatsApp CRM/RFQ skill.
# This script does not change WhatsApp authentication, linked-device state,
# gateway provider, owner credentials, or model credentials.

ROOT="${SAHJONY_CRM_BRIDGE_SOURCE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
TOOL_SOURCE="$ROOT/sahjony-crm-bridge.py"
SKILL_SOURCE="${SAHJONY_CRM_BRIDGE_SKILL_SOURCE:-$ROOT/../skills/whatsapp-crm-bridge/SKILL.md}"
TOOL_DEST="/usr/local/sbin/sahjony-crm-bridge"
STATE_DIR="${SAHJONY_CRM_BRIDGE_STATE_DIR:-/var/lib/sahjony-crm-bridge}"
OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-/var/lib/sahjony-openclaw-state}"
OPENCLAW_HOME="${OPENCLAW_HOME:-/home/node/.openclaw}"

log(){ printf '[crm-bridge-install] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || fail "run as root on the authorized Hostinger VPS"
[[ -f "$TOOL_SOURCE" ]] || fail "missing $TOOL_SOURCE"
[[ -f "$SKILL_SOURCE" ]] || fail "missing $SKILL_SOURCE"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"

python3 -m py_compile "$TOOL_SOURCE"
install -d -m 700 "$STATE_DIR"
install -m 700 "$TOOL_SOURCE" "$TOOL_DEST"

install_native_skill(){
  local installed=0 dest
  for dest in \
    "$OPENCLAW_HOME/skills/whatsapp-crm-bridge" \
    "$OPENCLAW_STATE_DIR/skills/whatsapp-crm-bridge"
  do
    install -d -m 700 "$dest"
    install -m 600 "$SKILL_SOURCE" "$dest/SKILL.md"
    installed=$((installed+1))
  done
  if id node >/dev/null 2>&1; then
    chown -R node:node "$OPENCLAW_HOME/skills/whatsapp-crm-bridge" 2>/dev/null || true
  fi
  log "Installed WhatsApp CRM/RFQ skill into $installed native OpenClaw skill paths"
}

find_running_container(){
  command -v docker >/dev/null 2>&1 || return 0
  docker ps --filter status=running --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null \
    | awk -F'|' 'tolower($0) ~ /openclaw|claw/ {print $1; exit}'
}

install_container_skill(){
  command -v docker >/dev/null 2>&1 || return 0
  local cid
  cid="$(find_running_container || true)"
  if [[ -z "$cid" ]]; then
    log "No running OpenClaw container detected; native OpenClaw skill install is authoritative"
    return 0
  fi
  if ! docker exec "$cid" sh -lc 'mkdir -p "$HOME/.openclaw/skills/whatsapp-crm-bridge" && chmod 700 "$HOME/.openclaw/skills/whatsapp-crm-bridge"' >/dev/null 2>&1; then
    log "Running OpenClaw container $cid became unavailable; skipping optional container skill install"
    return 0
  fi
  if ! docker cp "$SKILL_SOURCE" "$cid:/tmp/sahjony-whatsapp-crm-skill.md" >/dev/null 2>&1; then
    log "Container copy failed for $cid; native OpenClaw skill install remains authoritative"
    return 0
  fi
  if ! docker exec "$cid" sh -lc 'mv /tmp/sahjony-whatsapp-crm-skill.md "$HOME/.openclaw/skills/whatsapp-crm-bridge/SKILL.md" && chmod 600 "$HOME/.openclaw/skills/whatsapp-crm-bridge/SKILL.md"' >/dev/null 2>&1; then
    log "Container finalization failed for $cid; native OpenClaw skill install remains authoritative"
    return 0
  fi
  log "Installed WhatsApp CRM/RFQ skill into running OpenClaw container $cid"
}

cat >/etc/systemd/system/sahjony-crm-bridge.service <<EOF
[Unit]
Description=SAHJONY authorized OpenClaw CRM bridge doctor
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=SAHJONY_CRM_BRIDGE_STATE_DIR=$STATE_DIR
ExecStart=$TOOL_DEST doctor
User=root
Group=root
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=read-only
ProtectSystem=strict
ReadWritePaths=$STATE_DIR /run /tmp
EOF

cat >/etc/systemd/system/sahjony-crm-bridge.timer <<'EOF'
[Unit]
Description=Run SAHJONY CRM bridge doctor every two minutes

[Timer]
OnBootSec=90s
OnUnitActiveSec=2min
AccuracySec=15s
Persistent=true

[Install]
WantedBy=timers.target
EOF

install_native_skill
install_container_skill
systemctl daemon-reload
systemctl enable --now sahjony-crm-bridge.timer

# Immediate diagnostics are non-fatal because the remote app deployment may be
# updating at the same moment; the timer performs bounded recovery afterwards.
set +e
"$TOOL_DEST" doctor
rc=$?
set -e
systemctl is-active --quiet sahjony-crm-bridge.timer || fail "CRM bridge timer is not active"
test -s "$OPENCLAW_HOME/skills/whatsapp-crm-bridge/SKILL.md" || fail "native OpenClaw CRM/RFQ skill was not installed"

log "CRM bridge + governed RFQ skill installed; initial doctor exit=$rc. No authorization control was bypassed."
