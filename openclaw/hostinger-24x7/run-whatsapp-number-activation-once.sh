#!/usr/bin/env bash
set -Eeuo pipefail

# Run on the authorized Hostinger Kali VPS only.
# This wrapper never installs plugins, creates/recreates containers, touches Meta,
# or initiates WhatsApp pairing/relinking. It operates on the one retained
# OpenClaw container and the already-authorized Linked Device session only.

SRC_DIR="${SAHJONY_ACTIVATION_SRC_DIR:-/tmp/sahjony-whatsapp-number-activation}"
ACTIVATOR_SRC="$SRC_DIR/whatsapp-number-activate.sh"
GUARDIAN_SRC="$SRC_DIR/whatsapp-guardian.sh"
INSTALL_GUARDIAN_SRC="$SRC_DIR/install-whatsapp-guardian.sh"
ACTIVATOR_DST=/usr/local/sbin/sahjony-whatsapp-number-activate

fail(){ printf 'SAHJONY_ACTIVATION_FAIL=%s\n' "$1" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail docker_not_installed
command -v curl >/dev/null 2>&1 || fail curl_not_installed
command -v python3 >/dev/null 2>&1 || fail python3_not_installed
systemctl is-active --quiet docker.service || fail docker_not_active

for f in "$ACTIVATOR_SRC" "$GUARDIAN_SRC" "$INSTALL_GUARDIAN_SRC"; do
  [[ -s "$f" ]] || fail "missing_$(basename "$f")"
  bash -n "$f" || fail "syntax_$(basename "$f")"
done

mapfile -t ids < <(
  docker ps -aq | while read -r id; do
    meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}' 2>/dev/null || true)"
    grep -Eqi 'openclaw|open[-_ ]?claw|claw' <<<"$meta" && echo "$id"
  done
)
((${#ids[@]} == 1)) || fail "openclaw_container_count_${#ids[@]}"
cid="${ids[0]}"
name="$(docker inspect "$cid" --format '{{.Name}}')"
echo "OPENCLAW_CONTAINER=$name"

[[ "$(docker inspect "$cid" --format '{{.State.Running}}')" == true ]] || fail openclaw_container_not_running
docker update --restart unless-stopped "$cid" >/dev/null
[[ "$(docker inspect "$cid" --format '{{.HostConfig.RestartPolicy.Name}}')" == unless-stopped ]] || fail restart_policy_not_persistent

install -m 700 "$ACTIVATOR_SRC" "$ACTIVATOR_DST"
echo '=== LINKED DEVICE NUMBER ACTIVATION ==='
SAHJONY_GATEWAY_ID=hostinger-vps "$ACTIVATOR_DST"

echo '=== 24/7 GUARDIAN REFRESH ==='
bash "$INSTALL_GUARDIAN_SRC"
/usr/local/sbin/sahjony-whatsapp-guardian
systemctl is-enabled --quiet sahjony-whatsapp-guardian.timer || fail guardian_timer_not_enabled
systemctl is-active --quiet sahjony-whatsapp-guardian.timer || fail guardian_timer_not_active

last_good=/var/lib/sahjony-whatsapp-guardian/last-good
[[ -s "$last_good" ]] || fail guardian_last_good_missing
last_epoch="$(date -d "$(cat "$last_good")" +%s 2>/dev/null)" || fail guardian_last_good_invalid
now_epoch="$(date +%s)"
age=$((now_epoch-last_epoch))
echo "SAHJONY_GUARDIAN_LAST_GOOD_AGE_SECONDS=$age"
(( age >= 0 && age <= 180 )) || fail guardian_last_good_stale

echo '=== AUTHORITATIVE LOCAL WHATSAPP PROBE ==='
probe="$(docker exec "$cid" sh -lc '
  if command -v openclaw >/dev/null 2>&1; then openclaw channels status --probe
  elif [ -x "$HOME/.openclaw/bin/openclaw" ]; then "$HOME/.openclaw/bin/openclaw" channels status --probe
  elif [ -x /root/.openclaw/bin/openclaw ]; then /root/.openclaw/bin/openclaw channels status --probe
  else exit 127
  fi
' 2>&1)" || fail local_openclaw_probe_failed
printf '%s\n' "$probe" | sed -E 's/(token|secret|key|password)[=:][^[:space:]]+/\1=[REDACTED]/Ig'
PROBE_TEXT="$probe" python3 -c 'import os,re,sys; t=os.environ["PROBE_TEXT"]; ok=bool(re.search(r"WhatsApp[^\n]*\bconnected\b",t,re.I) or re.search(r"linked,\s*running,\s*connected",t,re.I)); print("SAHJONY_LOCAL_WHATSAPP_PROBE=CONNECTED" if ok else "SAHJONY_LOCAL_WHATSAPP_PROBE=NOT_CONNECTED"); sys.exit(0 if ok else 1)' || fail local_whatsapp_not_connected
unset PROBE_TEXT

echo '=== PRODUCTION HEALTH GATES ==='
health="$(curl -fsS https://www.sahjony.com/whatsapp/health)" || fail production_health_unreachable
HEALTH_JSON="$health" python3 -c 'import json,os,sys; h=json.loads(os.environ["HEALTH_JSON"]); n=h.get("hostinger_openclaw") or {}; checks={"status_ok":h.get("status")=="ok","hostinger_independent_runtime":h.get("hostinger_independent_runtime") is True,"send_ready":h.get("send_ready") is True,"webhook_ready":h.get("webhook_ready") is True,"hostinger_connected":n.get("connected") is True,"gateway_matches":n.get("gateway_id")=="hostinger-vps","business_number_present":bool(n.get("business_number")),"heartbeat_fresh":n.get("heartbeat_fresh") is True}; print(json.dumps({"checks":checks,"gateway_id":n.get("gateway_id"),"business_number":n.get("business_number"),"last_seen_at":n.get("last_seen_at")},separators=(",",":"))); sys.exit(0 if all(checks.values()) else 1)' || fail production_health_gates_not_ready
unset HEALTH_JSON

echo SAHJONY_HOSTINGER_WHATSAPP_24X7=READY
