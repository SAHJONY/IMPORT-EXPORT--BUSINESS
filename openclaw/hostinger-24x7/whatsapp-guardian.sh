#!/usr/bin/env bash
set -euo pipefail

# SAHJONY WhatsApp 24/7 Guardian
# Hostinger-local runtime is authoritative. Public health is secondary evidence.
# Repairs only reversible runtime state; it does not bypass Meta/WhatsApp authentication or policy gates.

LOCK=/run/lock/sahjony-whatsapp-guardian.lock
STATE_DIR=/var/lib/sahjony-whatsapp-guardian
LOG=/var/log/sahjony-whatsapp-guardian.log
mkdir -p "$STATE_DIR" "$(dirname "$LOCK")"
exec 9>"$LOCK"
flock -n 9 || exit 0
exec >>"$LOG" 2>&1
printf '\n[%s] guardian start\n' "$(date -Is)"

fail(){ echo "GUARDIAN_FAIL=$*"; exit 1; }
command -v docker >/dev/null 2>&1 || fail docker_missing
systemctl is-active --quiet docker || { systemctl enable --now docker || fail docker_start_failed; }

mapfile -t IDS < <(docker ps -aq | while read -r id; do
  meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}' 2>/dev/null || true)"
  grep -Eqi 'openclaw|claw' <<<"$meta" && echo "$id"
done)
((${#IDS[@]})) || fail openclaw_container_missing

healthy=false
for id in "${IDS[@]}"; do
  docker update --restart unless-stopped "$id" >/dev/null || true
  status="$(docker inspect "$id" --format '{{.State.Status}}' 2>/dev/null || true)"
  [[ "$status" == running ]] || docker start "$id" >/dev/null || true
  name="$(docker inspect "$id" --format '{{.Name}}' 2>/dev/null | sed 's#^/##')"
  echo "OPENCLAW_CONTAINER=$name status=$(docker inspect "$id" --format '{{.State.Status}}') restart=$(docker inspect "$id" --format '{{.HostConfig.RestartPolicy.Name}}')"

  probe="$(docker exec "$id" sh -lc 'command -v openclaw >/dev/null 2>&1 && openclaw channels status --probe 2>&1' || true)"
  printf '%s\n' "$probe"
  if grep -Eqi 'whatsapp.*(connected|ready|ok)|connected.*whatsapp' <<<"$probe"; then
    healthy=true
    break
  fi
done

if [[ "$healthy" != true ]]; then
  echo OPENCLAW_WHATSAPP_PROBE_FAILED=1
  for id in "${IDS[@]}"; do docker restart "$id" >/dev/null || true; done
  sleep 20
  for id in "${IDS[@]}"; do
    probe="$(docker exec "$id" sh -lc 'command -v openclaw >/dev/null 2>&1 && openclaw channels status --probe 2>&1' || true)"
    printf '%s\n' "$probe"
    grep -Eqi 'whatsapp.*(connected|ready|ok)|connected.*whatsapp' <<<"$probe" && healthy=true && break
  done
fi

if [[ "$healthy" == true ]]; then
  date -Is > "$STATE_DIR/last-good"
  echo SAHJONY_HOSTINGER_LOCAL_RUNTIME=READY
else
  echo SAHJONY_HOSTINGER_LOCAL_RUNTIME=DEGRADED
  exit 2
fi

# Secondary observation only: never downgrade a healthy Hostinger-local runtime because Vercel is stale.
curl -fsS --max-time 15 https://www.sahjony.com/whatsapp/health > "$STATE_DIR/public-health.json.tmp" 2>/dev/null && mv "$STATE_DIR/public-health.json.tmp" "$STATE_DIR/public-health.json" || true
