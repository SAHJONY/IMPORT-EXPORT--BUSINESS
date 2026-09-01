#!/usr/bin/env bash
set -euo pipefail

echo "HOST=$(hostname)"
systemctl is-active --quiet ssh || systemctl enable --now ssh

command -v docker >/dev/null 2>&1 || { echo DOCKER_MISSING=1 >&2; exit 20; }
systemctl is-active --quiet docker || systemctl enable --now docker

[[ -f /tmp/openclaw-runtime-recovery.sh ]] || { echo OPENCLAW_RUNTIME_RECOVERY_TOOL_MISSING=1 >&2; exit 21; }
[[ -f /tmp/openclaw-runtime-resolver.sh ]] || { echo OPENCLAW_RUNTIME_RESOLVER_MISSING=1 >&2; exit 22; }
install -m 0755 /tmp/openclaw-runtime-recovery.sh /usr/local/sbin/sahjony-openclaw-runtime-recovery
install -m 0755 /tmp/openclaw-runtime-resolver.sh /usr/local/sbin/sahjony-openclaw-runtime-resolver
if [[ -f /tmp/openclaw-docker-metadata-forensics.sh ]]; then
  install -m 0755 /tmp/openclaw-docker-metadata-forensics.sh /usr/local/sbin/sahjony-openclaw-docker-forensics
fi
if [[ -f /tmp/openclaw-state-audit.sh ]]; then
  install -m 0755 /tmp/openclaw-state-audit.sh /usr/local/sbin/sahjony-openclaw-state-audit
fi
bash -n /usr/local/sbin/sahjony-openclaw-runtime-recovery
bash -n /usr/local/sbin/sahjony-openclaw-runtime-resolver
[[ ! -x /usr/local/sbin/sahjony-openclaw-docker-forensics ]] || bash -n /usr/local/sbin/sahjony-openclaw-docker-forensics
[[ ! -x /usr/local/sbin/sahjony-openclaw-state-audit ]] || bash -n /usr/local/sbin/sahjony-openclaw-state-audit

echo '=== OPENCLAW RUNTIME RESOLVER ==='
/usr/local/sbin/sahjony-openclaw-runtime-resolver

mapfile -t OPENCLAW_IDS < <(docker ps -aq | while read -r id; do
  [[ -n "$id" ]] || continue
  meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}|{{json .Config.Labels}}' 2>/dev/null || true)"
  grep -Eqi 'openclaw|open[-_ ]?claw|claw' <<<"$meta" && echo "$id"
done)
((${#OPENCLAW_IDS[@]} == 1)) || { echo "OPENCLAW_CONTAINER_COUNT=${#OPENCLAW_IDS[@]}" >&2; exit 23; }

for id in "${OPENCLAW_IDS[@]}"; do
  docker update --restart unless-stopped "$id" >/dev/null
  [[ "$(docker inspect -f '{{.State.Running}}' "$id")" == true ]] || docker start "$id" >/dev/null
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

# Local acceptance evidence only. Public Vercel health remains secondary.
docker exec "${OPENCLAW_IDS[0]}" sh -lc 'openclaw channels status --probe'
echo SAHJONY_HOSTINGER_LOCAL_RUNTIME=READY
echo SAHJONY_HOSTINGER_BOOTSTRAP_STABILIZATION_COMPLETE=1
