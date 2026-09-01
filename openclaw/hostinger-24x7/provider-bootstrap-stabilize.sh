#!/usr/bin/env bash
set -euo pipefail

echo "HOST=$(hostname)"
systemctl is-active --quiet ssh || systemctl enable --now ssh

command -v docker >/dev/null 2>&1 || { echo DOCKER_MISSING=1 >&2; exit 20; }
systemctl is-active --quiet docker || systemctl enable --now docker

echo '=== EXISTING OPENCLAW CANDIDATES ==='
mapfile -t OPENCLAW_IDS < <(docker ps -aq | while read -r id; do
  meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}' 2>/dev/null || true)"
  grep -Eqi 'openclaw|claw' <<<"$meta" && echo "$id"
done)
((${#OPENCLAW_IDS[@]})) || { echo OPENCLAW_CONTAINER_MISSING=1 >&2; exit 21; }

for id in "${OPENCLAW_IDS[@]}"; do
  docker inspect "$id" --format 'name={{.Name}} image={{.Config.Image}} status={{.State.Status}} restart={{.HostConfig.RestartPolicy.Name}}'
done

install -d -m 0755 /opt/sahjony-whatsapp-guardian
install -m 0755 /tmp/whatsapp-guardian.sh /opt/sahjony-whatsapp-guardian/whatsapp-guardian.sh
install -m 0755 /tmp/install-whatsapp-guardian.sh /opt/sahjony-whatsapp-guardian/install-whatsapp-guardian.sh
/opt/sahjony-whatsapp-guardian/install-whatsapp-guardian.sh

echo '=== GUARDIAN TIMER ==='
systemctl is-enabled sahjony-whatsapp-guardian.timer
systemctl is-active sahjony-whatsapp-guardian.timer

echo '=== LAST GUARDIAN OUTPUT ==='
tail -n 100 /var/log/sahjony-whatsapp-guardian.log 2>/dev/null || true

echo '=== LAST GOOD ==='
cat /var/lib/sahjony-whatsapp-guardian/last-good 2>/dev/null || true

echo '=== OPENCLAW RESTART POLICY ==='
for id in "${OPENCLAW_IDS[@]}"; do
  docker inspect "$id" --format 'name={{.Name}} status={{.State.Status}} restart={{.HostConfig.RestartPolicy.Name}}'
done

echo SAHJONY_HOSTINGER_BOOTSTRAP_STABILIZATION_COMPLETE=1
