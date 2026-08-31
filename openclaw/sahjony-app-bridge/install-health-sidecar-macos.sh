#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
SIDE_CAR_DIR="$STATE_DIR/sidecars/sahjony-whatsapp-health"
PYTHON_BIN="$(command -v python3)"
OPENCLAW_BIN="${OPENCLAW_BIN:-$STATE_DIR/bin/openclaw}"
PLIST="$HOME/Library/LaunchAgents/com.sahjony.openclaw-whatsapp-health.plist"
LOG_DIR="$HOME/Library/Logs/openclaw"

mkdir -p "$SIDE_CAR_DIR" "$LOG_DIR" "$HOME/Library/LaunchAgents"
chmod 700 "$STATE_DIR" "$SIDE_CAR_DIR"

cp "$SCRIPT_DIR/health-sidecar.py" "$SIDE_CAR_DIR/health-sidecar.py"
chmod 700 "$SIDE_CAR_DIR/health-sidecar.py"

if [[ ! -x "$OPENCLAW_BIN" ]]; then
  echo "OpenClaw binary not executable: $OPENCLAW_BIN" >&2
  exit 1
fi

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.sahjony.openclaw-whatsapp-health</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$SIDE_CAR_DIR/health-sidecar.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>$HOME</string>
    <key>OPENCLAW_STATE_DIR</key>
    <string>$STATE_DIR</string>
    <key>OPENCLAW_BIN</key>
    <string>$OPENCLAW_BIN</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>30</integer>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/sahjony-whatsapp-health.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/sahjony-whatsapp-health.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/com.sahjony.openclaw-whatsapp-health" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/com.sahjony.openclaw-whatsapp-health"

sleep 3

echo "One-shot verification:"
"$PYTHON_BIN" "$SIDE_CAR_DIR/health-sidecar.py" || true

echo
echo "Installed SAHJONY WhatsApp health sidecar."
echo "LaunchAgent: $PLIST"
echo "Logs: $LOG_DIR/sahjony-whatsapp-health.log"
echo "Check: curl -s https://www.sahjony.com/whatsapp/health"
