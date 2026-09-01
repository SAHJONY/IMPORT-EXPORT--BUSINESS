#!/usr/bin/env bash
set -euo pipefail

# Restore the local container engine only when retained OpenClaw/Docker state exists.
# Never creates a fresh OpenClaw container and never re-pairs WhatsApp.

MODE="${1:-heal}"
[[ "$MODE" =~ ^(audit|heal)$ ]] || { echo 'use audit or heal' >&2; exit 2; }
[[ "$(id -u)" -eq 0 ]] || { echo RUN_AS_ROOT=1 >&2; exit 3; }

log(){ printf '[runtime-bootstrap] %s\n' "$*"; }

has_nonempty_dir(){
  [[ -d "$1" ]] && find "$1" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null | grep -q .
}

find_openclaw_artifacts(){
  find /opt /srv /root /var/lib -maxdepth 5 \
    \( -iname '*openclaw*' -o -iname '*claw*' -o -name 'docker-compose.yml' -o -name 'compose.yml' -o -name 'compose.yaml' \) \
    -print 2>/dev/null | head -n 120 || true
}

artifact_list="$(find_openclaw_artifacts)"
docker_state=false
containerd_state=false
openclaw_artifacts=false
has_nonempty_dir /var/lib/docker && docker_state=true || true
has_nonempty_dir /var/lib/containerd && containerd_state=true || true
[[ -n "$artifact_list" ]] && openclaw_artifacts=true || true

printf 'DOCKER_STATE_PRESENT=%s\n' "$docker_state"
printf 'CONTAINERD_STATE_PRESENT=%s\n' "$containerd_state"
printf 'OPENCLAW_ARTIFACTS_PRESENT=%s\n' "$openclaw_artifacts"
if [[ -n "$artifact_list" ]]; then
  echo '=== retained runtime artifacts ==='
  printf '%s\n' "$artifact_list"
fi

audit_native(){
  command -v docker >/dev/null 2>&1 && echo "DOCKER_BINARY=$(command -v docker)" || echo DOCKER_BINARY_MISSING=1
  command -v containerd >/dev/null 2>&1 && echo "CONTAINERD_BINARY=$(command -v containerd)" || true
  command -v podman >/dev/null 2>&1 && echo "PODMAN_BINARY=$(command -v podman)" || true
  command -v openclaw >/dev/null 2>&1 && echo "OPENCLAW_NATIVE_BINARY=$(command -v openclaw)" || true
  systemctl list-unit-files --no-legend 2>/dev/null | grep -Ei 'docker|containerd|podman|openclaw|claw' | head -n 80 || true
  dpkg-query -W -f='${Package}|${Status}|${Version}\n' 2>/dev/null | grep -Ei 'docker|containerd|podman|openclaw' | head -n 80 || true
}

audit_native
[[ "$MODE" == audit ]] && exit 0

if ! command -v docker >/dev/null 2>&1; then
  if [[ "$docker_state" != true && "$containerd_state" != true && "$openclaw_artifacts" != true ]]; then
    echo NO_RETAINED_RUNTIME_STATE_REFUSING_FRESH_DOCKER_INSTALL=1 >&2
    exit 20
  fi
  command -v apt-get >/dev/null 2>&1 || { echo APT_NOT_AVAILABLE=1 >&2; exit 21; }
  log 'Docker binary missing but retained runtime state exists; restoring distro Docker package'
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq docker.io >/dev/null
fi

systemctl enable --now docker >/dev/null 2>&1 || { echo DOCKER_SERVICE_START_FAILED=1 >&2; exit 22; }
docker info >/dev/null 2>&1 || { echo DOCKER_DAEMON_UNAVAILABLE=1 >&2; exit 23; }

mapfile -t ids < <(docker ps -aq | while read -r id; do
  meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}' 2>/dev/null || true)"
  grep -Eqi 'openclaw|claw' <<<"$meta" && echo "$id" || true
done)

if ((${#ids[@]} == 0)); then
  echo '=== docker inventory ==='
  docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}' || true
  echo OPENCLAW_CONTAINER_NOT_FOUND_AFTER_DOCKER_RESTORE=1 >&2
  echo REFUSING_TO_CREATE_NEW_OPENCLAW_CONTAINER=1 >&2
  exit 24
fi

if ((${#ids[@]} > 1)); then
  echo "OPENCLAW_CONTAINER_AMBIGUITY=${#ids[@]}" >&2
  for id in "${ids[@]}"; do docker inspect "$id" --format '{{.Id}}|{{.Name}}|{{.Config.Image}}|{{.State.Status}}|{{range .Mounts}}{{.Source}}->{{.Destination}};{{end}}'; done
  exit 25
fi

cid="${ids[0]}"
docker update --restart unless-stopped "$cid" >/dev/null
[[ "$(docker inspect "$cid" --format '{{.State.Running}}')" == true ]] || docker start "$cid" >/dev/null
sleep 3

echo "OPENCLAW_CONTAINER_ID=$cid"
docker inspect "$cid" --format 'OPENCLAW name={{.Name}} image={{.Config.Image}} status={{.State.Status}} restart={{.HostConfig.RestartPolicy.Name}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}'

echo SAHJONY_RUNTIME_BOOTSTRAP_READY=1
