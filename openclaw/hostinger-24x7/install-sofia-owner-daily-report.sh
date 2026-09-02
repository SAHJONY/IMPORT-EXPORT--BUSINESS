#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OWNER_WHATSAPP_E164="${OWNER_WHATSAPP_E164:-}"
[[ "$OWNER_WHATSAPP_E164" =~ ^\+[1-9][0-9]{7,14}$ ]] || { echo OWNER_WHATSAPP_E164_INVALID=1 >&2; exit 2; }

install -m 0755 "$ROOT/sofia-owner-daily-report.sh" /usr/local/sbin/sofia-owner-daily-report
install -d -m 0700 /etc/sahjony
{
  printf 'OWNER_NAME=%q\n' 'Juan Gonzalez'
  printf 'OWNER_WHATSAPP_E164=%q\n' "$OWNER_WHATSAPP_E164"
  printf 'SAHJONY_APP_URL=%q\n' "${SAHJONY_APP_URL:-https://www.sahjony.com}"
} >/etc/sahjony/owner-report.env
chmod 600 /etc/sahjony/owner-report.env

cat >/etc/systemd/system/sofia-owner-daily-report.service <<'EOF'
[Unit]
Description=Sofia daily executive report for Juan Gonzalez
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
EnvironmentFile=/etc/sahjony/owner-report.env
ExecStart=/usr/local/sbin/sofia-owner-daily-report
TimeoutStartSec=180
EOF

cat >/etc/systemd/system/sofia-owner-daily-report.timer <<'EOF'
[Unit]
Description=Send Sofia owner report daily at 06:00 America/Chicago

[Timer]
OnCalendar=*-*-* 06:00:00 America/Chicago
Persistent=true
AccuracySec=30s
Unit=sofia-owner-daily-report.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now sofia-owner-daily-report.timer
systemctl is-active --quiet sofia-owner-daily-report.timer
systemctl list-timers sofia-owner-daily-report.timer --no-pager
echo SOFIA_OWNER_DAILY_REPORT_INSTALLED=1
