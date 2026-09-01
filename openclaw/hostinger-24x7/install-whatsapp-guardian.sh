#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
install -m 0755 "$ROOT/whatsapp-guardian.sh" /usr/local/sbin/sahjony-whatsapp-guardian
cat >/etc/systemd/system/sahjony-whatsapp-guardian.service <<'EOF'
[Unit]
Description=SAHJONY WhatsApp 24/7 self-healing guardian
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/sahjony-whatsapp-guardian
TimeoutStartSec=120
EOF
cat >/etc/systemd/system/sahjony-whatsapp-guardian.timer <<'EOF'
[Unit]
Description=Run SAHJONY WhatsApp guardian every minute

[Timer]
OnBootSec=45s
OnUnitActiveSec=60s
AccuracySec=10s
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now sahjony-whatsapp-guardian.timer
systemctl start sahjony-whatsapp-guardian.service || true
systemctl --no-pager status sahjony-whatsapp-guardian.timer || true
echo SAHJONY_WHATSAPP_GUARDIAN_INSTALLED=1
