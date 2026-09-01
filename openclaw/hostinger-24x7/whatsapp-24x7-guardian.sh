#!/usr/bin/env bash
set -euo pipefail

# SAHJONY WhatsApp 24/7 local guardian.
# Runs on the authorized Hostinger VPS. It never bypasses authentication,
# Meta verification, pairing, 2FA, or provider policy. It only performs safe,
# reversible local healing of the existing Docker/OpenClaw runtime.

MODE="${1:-heal}"
APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
INSTALL_ROOT="${SAHJONY_OPENCLAW_ROOT:-/opt/sahjony-openclaw}"
REPO_DIR="${INSTALL_ROOT}/repo"
LOCK_FILE="${INSTALL_ROOT}/whatsapp-24x7.guard.lock"
RESTART_STAMP="${INSTALL_ROOT}/whatsapp-24x7.last-restart"
RESTART_COOLDOWN="${SAHJONY_RESTART_COOLDOWN_SECONDS:-300}"
GATEWAY_ID="${SAHJONY_GATEWAY_ID:-hostinger-vps}"

mkdir -p "$INSTALL_ROOT"
chmod 700 "$INSTALL_ROOT" 2>/dev/null || true

log(){ printf '[whatsapp-24x7] %s\n' "$*"; }
fail(){ log "FAIL: $*"; exit 1; }

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || { log 'another guardian instance is active; exiting cleanly'; exit 0; }
fi

need(){ command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }

public_health(){
  curl -fsS --max-time 12 "$APP_URL/whatsapp/health" 2>/dev/null || true
}

json_true(){
  local body="$1" expr="$2"
  command -v jq >/dev/null 2>&1 || return 1
  jq -e "$expr == true" >/dev/null 2>&1 <<<"$body"
}

find_container(){
  docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null \
    | awk -F'|' 'tolower($0) ~ /openclaw|claw/ {print $1; exit}'
}

container_running(){
  local cid="$1"
  [[ "$(docker inspect "$cid" --format '{{.State.Running}}' 2>/dev/null || true)" == true ]]
}

restart_allowed(){
  local now last=0
  now="$(date +%s)"
  [[ -f "$RESTART_STAMP" ]] && last="$(cat "$RESTART_STAMP" 2>/dev/null || echo 0)"
  (( now - last >= RESTART_COOLDOWN ))
}

restart_once(){
  local cid="$1" reason="$2"
  if restart_allowed; then
    log "restarting OpenClaw once: $reason"
    date +%s >"$RESTART_STAMP"
    docker restart "$cid" >/dev/null
    sleep 8
  else
    log "restart suppressed by ${RESTART_COOLDOWN}s cooldown: $reason"
  fi
}

channel_probe(){
  local cid="$1"
  if docker exec "$cid" sh -lc 'command -v openclaw >/dev/null 2>&1'; then
    docker exec "$cid" openclaw channels status --probe 2>&1 || true
  else
    printf 'OPENCLAW_CLI_NOT_EXPOSED\n'
  fi
}

whatsapp_connected_from_probe(){
  grep -Eiq 'whatsapp.*(connected|ready|active|healthy)|(connected|ready|active|healthy).*whatsapp'
}

ensure_timers(){
  local missing=0
  systemctl is-active --quiet sahjony-openclaw-watchdog.timer || missing=1
  systemctl is-active --quiet sahjony-openclaw-backup.timer || missing=1
  if (( missing == 1 )) && [[ -x "$REPO_DIR/openclaw/hostinger-24x7/bootstrap-existing-openclaw.sh" ]]; then
    log 'required timers missing; running reviewed non-destructive bootstrap'
    "$REPO_DIR/openclaw/hostinger-24x7/bootstrap-existing-openclaw.sh"
  fi
}

install_guardian_timer(){
  local self="$REPO_DIR/openclaw/hostinger-24x7/whatsapp-24x7-guardian.sh"
  [[ -x "$self" ]] || self="$(readlink -f "$0" 2>/dev/null || printf '%s' "$0")"
  cat >/etc/systemd/system/sahjony-whatsapp-24x7-guardian.service <<EOF
[Unit]
Description=SAHJONY WhatsApp 24/7 local guardian
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=${self} heal
EOF
  cat >/etc/systemd/system/sahjony-whatsapp-24x7-guardian.timer <<'EOF'
[Unit]
Description=Run SAHJONY WhatsApp 24/7 guardian every two minutes

[Timer]
OnBootSec=90s
OnUnitActiveSec=2min
AccuracySec=15s
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now sahjony-whatsapp-24x7-guardian.timer
  log 'guardian timer installed and active'
}

summary(){
  local cid="$1" probe="$2" health="$3"
  local running=false restart_policy=unknown channel=false watchdog=false backup=false guardian=false public_gateway=false meta_ready=false hostinger_ready=false
  if [[ -n "$cid" ]]; then
    container_running "$cid" && running=true
    restart_policy="$(docker inspect "$cid" --format '{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || echo unknown)"
  fi
  printf '%s' "$probe" | whatsapp_connected_from_probe && channel=true || true
  systemctl is-active --quiet sahjony-openclaw-watchdog.timer && watchdog=true || true
  systemctl is-active --quiet sahjony-openclaw-backup.timer && backup=true || true
  systemctl is-active --quiet sahjony-whatsapp-24x7-guardian.timer && guardian=true || true
  if [[ -n "$health" ]] && command -v jq >/dev/null 2>&1; then
    json_true "$health" '.gateway_connected' && public_gateway=true || true
    json_true "$health" '.cloud_independent_of_local_mac' && meta_ready=true || true
    json_true "$health" '.hostinger_independent_runtime' && hostinger_ready=true || true
  fi
  printf '{"gateway_id":"%s","container_running":%s,"restart_policy":"%s","whatsapp_channel_connected":%s,"watchdog_timer":%s,"backup_timer":%s,"guardian_timer":%s,"public_gateway_connected":%s,"meta_cloud_ready":%s,"hostinger_runtime_ready":%s}\n' \
    "$GATEWAY_ID" "$running" "$restart_policy" "$channel" "$watchdog" "$backup" "$guardian" "$public_gateway" "$meta_ready" "$hostinger_ready"
}

main(){
  [[ "$(id -u)" -eq 0 ]] || fail 'run as root on the authorized Hostinger VPS'
  need docker
  need curl
  systemctl enable --now docker >/dev/null 2>&1 || true

  local cid probe health
  cid="$(find_container || true)"
  [[ -n "$cid" ]] || fail 'existing OpenClaw Docker container not found; refusing to install a second instance blindly'

  docker update --restart unless-stopped "$cid" >/dev/null 2>&1 || true
  if ! container_running "$cid"; then
    log 'OpenClaw container is stopped; starting existing container'
    docker start "$cid" >/dev/null
    sleep 8
  fi

  probe="$(channel_probe "$cid")"
  if [[ "$MODE" != audit ]] && ! printf '%s' "$probe" | whatsapp_connected_from_probe; then
    restart_once "$cid" 'WhatsApp channel probe is not connected/ready'
    probe="$(channel_probe "$cid")"
  fi

  if [[ "$MODE" == heal || "$MODE" == install ]]; then
    ensure_timers
  fi
  if [[ "$MODE" == install ]]; then
    install_guardian_timer
  fi

  health="$(public_health)"
  summary "$cid" "$probe" "$health"

  if printf '%s' "$probe" | whatsapp_connected_from_probe; then
    log 'local WhatsApp channel is connected'
    exit 0
  fi

  # Public Meta Cloud readiness can keep WhatsApp production online even if the
  # OpenClaw fallback is degraded, but the fallback still remains a repair target.
  if [[ -n "$health" ]] && json_true "$health" '.cloud_independent_of_local_mac'; then
    log 'Meta Cloud transport is independently ready; OpenClaw fallback remains degraded'
    exit 0
  fi

  fail 'WhatsApp is not yet connected through OpenClaw and Meta Cloud is not independently ready'
}

case "$MODE" in
  audit|heal|install) main ;;
  *) fail "unsupported mode '$MODE' (use audit|heal|install)" ;;
esac
