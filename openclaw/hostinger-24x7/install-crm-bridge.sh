#!/usr/bin/env bash
set -Eeuo pipefail

# Installs the authorized SAHJONY CRM bridge client on the Hostinger VPS and,
# when the retained OpenClaw container exists, installs the corresponding skill
# into the persisted OpenClaw home. This script never changes WhatsApp auth,
# linked-device state, owner credentials, or provider security controls.

ROOT="${SAHJONY_CRM_BRIDGE_SOURCE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
TOOL_SOURCE="$ROOT/sahjony-crm-bridge.py"
SKILL_SOURCE="${SAHJONY_CRM_BRIDGE_SKILL_SOURCE:-$ROOT/../skills/whatsapp-crm-bridge/SKILL.md}"
TOOL_DEST="/usr/local/sbin/sahjony-crm-bridge"
STATE_DIR="${SAHJONY_CRM_BRIDGE_STATE_DIR:-/var/lib/sahjony-crm-bridge}"

log(){ printf '[crm-bridge-install] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || fail "run as root on the authorized Hostinger VPS"
[[ -f "$TOOL_SOURCE" ]] || fail "missing $TOOL_SOURCE"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"

python3 -m py_compile "$TOOL_SOURCE"
install -d -m 700 "$STATE_DIR"
install -m 700 "$TOOL_SOURCE" "$TOOL_DEST"

find_container(){
  docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null \
    | awk -F'|' 'tolower($0) ~ /openclaw|claw/ {print $1; exit}'
}

install_skill(){
  command -v docker >/dev/null 2>&1 || { log 'Docker unavailable; host CRM client installed, OpenClaw skill install deferred.'; return 0; }
  local cid
  cid="$(find_container || true)"
  [[ -n "$cid" ]] || { log 'Existing OpenClaw container not found; skill install deferred without creating a container.'; return 0; }
  [[ -f "$SKILL_SOURCE" ]] || { log "Skill source not present at $SKILL_SOURCE; host client remains installed."; return 0; }

  docker exec "$cid" sh -lc 'mkdir -p "$HOME/.openclaw/skills/whatsapp-crm-bridge" && chmod 700 "$HOME/.openclaw/skills/whatsapp-crm-bridge"' >/dev/null
  docker cp "$SKILL_SOURCE" "$cid:/tmp/sahjony-whatsapp-crm-skill.md" >/dev/null
  docker exec "$cid" sh -lc 'mv /tmp/sahjony-whatsapp-crm-skill.md "$HOME/.openclaw/skills/whatsapp-crm-bridge/SKILL.md" && chmod 600 "$HOME/.openclaw/skills/whatsapp-crm-bridge/SKILL.md"' >/dev/null
  log "Installed WhatsApp CRM skill into retained OpenClaw container $cid"
}

cat >/etc/systemd/system/sahjony-crm-bridge.service <<EOF
[Unit]
Description=SAHJONY authorized OpenClaw CRM bridge doctor
After=network-online.target docker.service
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

install_skill
systemctl daemon-reload
systemctl enable --now sahjony-crm-bridge.timer

# One immediate diagnostic is intentionally non-fatal so installation can land
# before the matching application deployment is live. The timer will retry.
set +e
"$TOOL_DEST" doctor
rc=$?
set -e
systemctl is-active --quiet sahjony-crm-bridge.timer || fail "CRM bridge timer is not active"

log "CRM bridge installed; initial doctor exit=$rc. No authorization control was bypassed."
