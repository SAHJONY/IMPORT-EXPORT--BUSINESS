#!/usr/bin/env bash
set -euo pipefail

# SAHJONY Hostinger OpenClaw 24x7 activator
# Safe-by-default: discovers one existing OpenClaw runtime, backs up state,
# enables restart/watchdog, and never prints secrets or opens public ports.

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root (or sudo)."
  exit 1
fi

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_ROOT="/var/backups/sahjony-openclaw"
WATCHDOG="/usr/local/sbin/sahjony-openclaw-watchdog"
SERVICE="/etc/systemd/system/sahjony-openclaw-watchdog.service"
TIMER="/etc/systemd/system/sahjony-openclaw-watchdog.timer"
mkdir -p "$BACKUP_ROOT"

echo "=== SAHJONY HOSTINGER OPENCLAW 24X7 ACTIVATION ==="
echo "timestamp_utc=$TS"

# 1) Back up recognizable OpenClaw state without reading/printing secret values.
STATE=""
for p in /root/.openclaw "$HOME/.openclaw" /home/*/.openclaw /var/lib/openclaw; do
  if [ -d "$p" ] && { [ -f "$p/openclaw.json" ] || find "$p" -maxdepth 3 -name 'openclaw*.sqlite' -print -quit 2>/dev/null | grep -q .; }; then
    STATE="$p"
    break
  fi
done

if [ -n "$STATE" ]; then
  ARCHIVE="$BACKUP_ROOT/openclaw-state-$TS.tar.gz"
  tar --exclude='*.log' --exclude='cache' -czf "$ARCHIVE" -C "$(dirname "$STATE")" "$(basename "$STATE")"
  chmod 600 "$ARCHIVE"
  echo "state_backup=$ARCHIVE"
else
  echo "state_backup=not_found (runtime may be container-volume-only)"
fi

# 2) Detect exactly one OpenClaw Docker container OR exactly one systemd service.
DOCKER_IDS=()
if command -v docker >/dev/null 2>&1; then
  while IFS= read -r id; do
    [ -n "$id" ] && DOCKER_IDS+=("$id")
  done < <(docker ps -a --format '{{.ID}} {{.Names}} {{.Image}}' 2>/dev/null | grep -Ei 'openclaw|open-claw' | awk '{print $1}' | sort -u)
fi

SYSTEMD_UNITS=()
if command -v systemctl >/dev/null 2>&1; then
  while IFS= read -r unit; do
    [ -n "$unit" ] && SYSTEMD_UNITS+=("$unit")
  done < <(systemctl list-unit-files --type=service --no-legend 2>/dev/null | awk '{print $1}' | grep -Ei '^openclaw.*\.service$|^.*openclaw.*\.service$' | sort -u)
fi

RUNTIME_TYPE=""
RUNTIME_ID=""
if [ "${#DOCKER_IDS[@]}" -eq 1 ] && [ "${#SYSTEMD_UNITS[@]}" -eq 0 ]; then
  RUNTIME_TYPE="docker"
  RUNTIME_ID="${DOCKER_IDS[0]}"
elif [ "${#DOCKER_IDS[@]}" -eq 0 ] && [ "${#SYSTEMD_UNITS[@]}" -eq 1 ]; then
  RUNTIME_TYPE="systemd"
  RUNTIME_ID="${SYSTEMD_UNITS[0]}"
elif [ "${#DOCKER_IDS[@]}" -eq 1 ] && [ "${#SYSTEMD_UNITS[@]}" -eq 1 ]; then
  # Prefer the currently running runtime only when exactly one is active.
  D_RUNNING="$(docker inspect -f '{{.State.Running}}' "${DOCKER_IDS[0]}" 2>/dev/null || echo false)"
  S_RUNNING="$(systemctl is-active "${SYSTEMD_UNITS[0]}" 2>/dev/null || true)"
  if [ "$D_RUNNING" = "true" ] && [ "$S_RUNNING" != "active" ]; then
    RUNTIME_TYPE="docker"; RUNTIME_ID="${DOCKER_IDS[0]}"
  elif [ "$D_RUNNING" != "true" ] && [ "$S_RUNNING" = "active" ]; then
    RUNTIME_TYPE="systemd"; RUNTIME_ID="${SYSTEMD_UNITS[0]}"
  fi
fi

if [ -z "$RUNTIME_TYPE" ]; then
  echo "ERROR: could not identify exactly one safe OpenClaw runtime."
  echo "docker_candidates=${#DOCKER_IDS[@]} systemd_candidates=${#SYSTEMD_UNITS[@]}"
  echo "Run: bash openclaw/hostinger/discover-openclaw-host.sh"
  exit 2
fi

echo "runtime_type=$RUNTIME_TYPE"
if [ "$RUNTIME_TYPE" = "docker" ]; then
  NAME="$(docker inspect -f '{{.Name}}' "$RUNTIME_ID" | sed 's#^/##')"
  IMAGE="$(docker inspect -f '{{.Config.Image}}' "$RUNTIME_ID")"
  echo "container_name=$NAME"
  echo "container_image=$IMAGE"
  docker update --restart unless-stopped "$RUNTIME_ID" >/dev/null
  if [ "$(docker inspect -f '{{.State.Running}}' "$RUNTIME_ID")" != "true" ]; then
    docker start "$RUNTIME_ID" >/dev/null
  fi
else
  echo "systemd_unit=$RUNTIME_ID"
  systemctl enable "$RUNTIME_ID" >/dev/null
  systemctl start "$RUNTIME_ID" >/dev/null || true
fi

# 3) Install a fail-safe watchdog. It checks the local OpenClaw gateway only.
cat > "$WATCHDOG" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
RUNTIME_TYPE="${SAHJONY_OPENCLAW_RUNTIME_TYPE:-}"
RUNTIME_ID="${SAHJONY_OPENCLAW_RUNTIME_ID:-}"
PORT="${SAHJONY_OPENCLAW_PORT:-18789}"

healthy=0
if command -v curl >/dev/null 2>&1; then
  # Any HTTP response proves the local listener is alive; auth may return 401/403.
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "http://127.0.0.1:${PORT}/" || true)"
  case "$code" in 2*|3*|4*) healthy=1 ;; esac
fi

if [ "$healthy" -eq 1 ]; then exit 0; fi

if [ "$RUNTIME_TYPE" = "docker" ] && command -v docker >/dev/null 2>&1; then
  docker restart "$RUNTIME_ID" >/dev/null 2>&1 || true
elif [ "$RUNTIME_TYPE" = "systemd" ] && command -v systemctl >/dev/null 2>&1; then
  systemctl restart "$RUNTIME_ID" >/dev/null 2>&1 || true
fi
EOF
chmod 700 "$WATCHDOG"

cat > "$SERVICE" <<EOF
[Unit]
Description=SAHJONY OpenClaw health watchdog
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=SAHJONY_OPENCLAW_RUNTIME_TYPE=$RUNTIME_TYPE
Environment=SAHJONY_OPENCLAW_RUNTIME_ID=$RUNTIME_ID
Environment=SAHJONY_OPENCLAW_PORT=18789
ExecStart=$WATCHDOG
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
EOF

cat > "$TIMER" <<'EOF'
[Unit]
Description=Run SAHJONY OpenClaw health watchdog every minute

[Timer]
OnBootSec=90s
OnUnitActiveSec=60s
AccuracySec=15s
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now sahjony-openclaw-watchdog.timer >/dev/null

# 4) Validate local runtime without exposing credentials.
sleep 2
if command -v curl >/dev/null 2>&1; then
  CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:18789/ || true)"
  echo "local_gateway_http=$CODE"
fi
if command -v openclaw >/dev/null 2>&1; then
  (openclaw status --deep 2>&1 || openclaw status 2>&1 || true) \
    | sed -E 's/(token|secret|password|api[_-]?key|authorization|cookie|bearer)[=: ]+[^ ,;]+/\1=<REDACTED>/Ig' \
    | tail -80
fi

echo "watchdog_timer=$(systemctl is-active sahjony-openclaw-watchdog.timer 2>/dev/null || true)"
echo "public_exposure_changed=false"
echo "secrets_changed=false"
echo "OPENCLAW_24X7_BASELINE_READY=1"
