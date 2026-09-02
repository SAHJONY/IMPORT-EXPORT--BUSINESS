#!/usr/bin/env bash
set -euo pipefail

OWNER_NAME="${OWNER_NAME:-Juan Gonzalez}"
OWNER_WHATSAPP_E164="${OWNER_WHATSAPP_E164:-}"
APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
STATE_DIR=/var/lib/sahjony-owner-report

fail(){ echo "SOFIA_OWNER_REPORT_FAIL=$*" >&2; exit 1; }
[[ "$OWNER_WHATSAPP_E164" =~ ^\+[1-9][0-9]{7,14}$ ]] || fail owner_whatsapp_e164_missing_or_invalid
command -v docker >/dev/null 2>&1 || fail docker_missing

find_openclaw_container(){
  docker ps -q | while read -r id; do
    meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}' 2>/dev/null || true)"
    if grep -Eqi 'openclaw|claw' <<<"$meta"; then printf '%s\n' "$id"; return 0; fi
  done
}

run_openclaw(){
  local id="$1"; shift
  if docker exec "$id" sh -lc 'command -v openclaw >/dev/null 2>&1'; then docker exec "$id" openclaw "$@"; return; fi
  if docker exec "$id" sh -lc '[ -x /root/.openclaw/bin/openclaw ]'; then docker exec "$id" /root/.openclaw/bin/openclaw "$@"; return; fi
  return 127
}

cid="$(find_openclaw_container)"
[[ -n "$cid" ]] || fail openclaw_container_missing

channel="$(run_openclaw "$cid" channels status --channel whatsapp --probe 2>&1 || true)"
if grep -Eqi 'connected|ready|active|healthy|linked' <<<"$channel"; then wa_status=CONNECTED; else wa_status=ATTENTION; fi
guardian="$(systemctl is-active sahjony-whatsapp-guardian.timer 2>/dev/null || true)"
container="$(docker inspect "$cid" --format '{{.State.Status}} / restart={{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || echo unknown)"
disk="$(df -h / | awk 'NR==2 {print $5 " used, " $4 " free"}')"
load="$(awk '{print $1 ", " $2 ", " $3}' /proc/loadavg)"
sales_http="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 12 "${APP_URL%/}/whatsapp/sofia/sales-os/health" 2>/dev/null || echo 000)"
business_http="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 12 "${APP_URL%/}/business-os/health" 2>/dev/null || echo 000)"
timestamp="$(TZ=America/Chicago date '+%Y-%m-%d %I:%M %p %Z')"

message="Buenos días, ${OWNER_NAME}. Reporte ejecutivo de Sofia — ${timestamp}

• Sofia/WhatsApp: ${wa_status}
• OpenClaw: ${container}
• Guardian 24/7: ${guardian}
• Sales OS público: HTTP ${sales_http}
• Business OS público: HTTP ${business_http}
• Hostinger: disco ${disk}; carga ${load}

Control del propietario: SUPERADMIN / owner:full / acceso a datos autorizado / costo interno $0.
Responde a Sofia con cualquier solicitud de reporte específico y la procesará con tu autoridad de propietario, manteniendo seguridad, privacidad, legalidad y evidencia verificable."

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
if ! run_openclaw "$cid" message send --channel whatsapp --target "$OWNER_WHATSAPP_E164" --message "$message"; then
  fail whatsapp_send_failed
fi
printf '%s\n' "$timestamp" >"$STATE_DIR/last-success"
chmod 600 "$STATE_DIR/last-success"
echo SOFIA_OWNER_DAILY_REPORT_SENT=1
