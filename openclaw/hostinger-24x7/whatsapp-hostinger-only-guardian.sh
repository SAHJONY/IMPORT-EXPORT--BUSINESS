#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-heal}"
ROOT="${SAHJONY_OPENCLAW_ROOT:-/opt/sahjony-openclaw}"
LOCK="$ROOT/hostinger-whatsapp.guard.lock"
STAMP="$ROOT/hostinger-whatsapp.last-restart"
COOLDOWN="${SAHJONY_RESTART_COOLDOWN_SECONDS:-300}"
GATEWAY_ID="${SAHJONY_GATEWAY_ID:-hostinger-vps}"

mkdir -p "$ROOT"
chmod 700 "$ROOT" 2>/dev/null || true

log(){ printf '[hostinger-whatsapp] %s\n' "$*"; }
fail(){ log "FAIL: $*"; exit 1; }

if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  flock -n 9 || { log 'another guardian instance is active'; exit 0; }
fi

command -v docker >/dev/null 2>&1 || fail 'docker is not installed'

find_container(){
  docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null \
    | awk -F'|' 'tolower($0) ~ /openclaw|claw/ {print $1; exit}'
}

probe_channel(){
  local cid="$1"
  docker exec "$cid" sh -lc 'command -v openclaw >/dev/null 2>&1' || return 1
  docker exec "$cid" openclaw channels status --probe 2>&1 || true
}

is_whatsapp_ready(){
  grep -Eiq 'whatsapp.*(connected|ready|active|healthy)|(connected|ready|active|healthy).*whatsapp'
}

restart_allowed(){
  local now last=0
  now="$(date +%s)"
  [[ -f "$STAMP" ]] && last="$(cat "$STAMP" 2>/dev/null || echo 0)"
  (( now - last >= COOLDOWN ))
}

install_timer(){
  install -m 700 "$0" "$ROOT/whatsapp-hostinger-only-guardian.sh"
  cat >/etc/systemd/system/sahjony-whatsapp-hostinger.service <<EOF
[Unit]
Description=SAHJONY Hostinger WhatsApp guardian
After=docker.service network-online.target
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=$ROOT/whatsapp-hostinger-only-guardian.sh heal
EOF
  cat >/etc/systemd/system/sahjony-whatsapp-hostinger.timer <<'EOF'
[Unit]
Description=Run SAHJONY Hostinger WhatsApp guardian every two minutes

[Timer]
OnBootSec=90s
OnUnitActiveSec=2min
AccuracySec=15s
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now sahjony-whatsapp-hostinger.timer
}

main(){
  [[ "$(id -u)" -eq 0 ]] || fail 'run as root on the authorized Hostinger VPS'
  systemctl enable --now docker >/dev/null 2>&1 || true

  local cid probe running restart_policy timer=false
  cid="$(find_container || true)"
  [[ -n "$cid" ]] || fail 'existing OpenClaw container not found; refusing to create a duplicate'

  docker update --restart unless-stopped "$cid" >/dev/null 2>&1 || true
  if [[ "$(docker inspect "$cid" --format '{{.State.Running}}' 2>/dev/null || true)" != true ]]; then
    docker start "$cid" >/dev/null
    sleep 8
  fi

  probe="$(probe_channel "$cid" || true)"
  if [[ "$MODE" != audit ]] && ! printf '%s' "$probe" | is_whatsapp_ready; then
    if restart_allowed; then
      log 'WhatsApp channel not ready; restarting existing OpenClaw container once'
      date +%s >"$STAMP"
      docker restart "$cid" >/dev/null
      sleep 8
      probe="$(probe_channel "$cid" || true)"
    else
      log "restart suppressed by ${COOLDOWN}s cooldown"
    fi
  fi

  if [[ "$MODE" == install ]]; then install_timer; fi
  systemctl is-active --quiet sahjony-whatsapp-hostinger.timer && timer=true || true
  running="$(docker inspect "$cid" --format '{{.State.Running}}' 2>/dev/null || echo false)"
  restart_policy="$(docker inspect "$cid" --format '{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || echo unknown)"

  local ready=false
  printf '%s' "$probe" | is_whatsapp_ready && ready=true || true
  printf '{"gateway_id":"%s","authoritative_transport":"hostinger_openclaw","container_running":%s,"restart_policy":"%s","whatsapp_connected":%s,"guardian_timer":%s}\n' \
    "$GATEWAY_ID" "$running" "$restart_policy" "$ready" "$timer"

  [[ "$ready" == true ]] || fail 'WhatsApp is not connected through Hostinger OpenClaw; if the durable WhatsApp session expired, a valid re-pairing is required'
  log 'Hostinger OpenClaw WhatsApp channel is READY'
}

case "$MODE" in audit|heal|install) main ;; *) fail "use audit, heal, or install" ;; esac
