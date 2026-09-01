#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${SAHJONY_OPENCLAW_INSTALL_DIR:-/opt/sahjony-openclaw}"
STATE_DIR="${SAHJONY_OPENCLAW_STATE_DIR:-/var/lib/sahjony-openclaw-state}"
AUTH_DIR="${SAHJONY_OPENCLAW_AUTH_DIR:-/var/lib/sahjony-openclaw-auth}"
IMAGE="${SAHJONY_OPENCLAW_IMAGE:-ghcr.io/openclaw/openclaw:latest}"
CONTAINER_NAME="sahjony-openclaw-gateway"

log(){ printf '[openclaw-install] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || fail 'run as root on the authorized Hostinger VPS'
command -v docker >/dev/null 2>&1 || fail 'Docker is not installed'
command -v openssl >/dev/null 2>&1 || fail 'openssl is required'

systemctl enable --now docker.service
docker info >/dev/null
if ! docker compose version >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq docker-compose-v2 >/dev/null 2>&1 || apt-get install -y -qq docker-compose >/dev/null
fi
docker compose version >/dev/null

install -d -m 700 "$INSTALL_DIR" "$STATE_DIR" "$AUTH_DIR" /var/backups/sahjony-openclaw

# Preserve any pre-existing native OpenClaw state. Never delete or overwrite it.
if [[ -d /root/.openclaw && -n "$(find /root/.openclaw -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  tar -C /root -czf "/var/backups/sahjony-openclaw/root-openclaw-$ts.tgz" .openclaw
  chmod 600 "/var/backups/sahjony-openclaw/root-openclaw-$ts.tgz"
  log 'existing /root/.openclaw state backed up'
fi

# The official image runs as node (uid/gid 1000). Keep mounted state private but writable.
chown -R 1000:1000 "$STATE_DIR" "$AUTH_DIR"

cd "$INSTALL_DIR"
if [[ ! -s .env ]]; then
  token="$(openssl rand -hex 32)"
  umask 077
  printf 'OPENCLAW_IMAGE=%s\nOPENCLAW_GATEWAY_TOKEN=%s\nOPENCLAW_GATEWAY_BIND=lan\nOPENCLAW_GATEWAY_PORT=18789\nOPENCLAW_TZ=UTC\nOPENCLAW_DISABLE_BONJOUR=1\n' "$IMAGE" "$token" > .env
fi
chmod 600 .env

cat > docker-compose.yml <<'COMPOSE'
services:
  openclaw-gateway:
    container_name: sahjony-openclaw-gateway
    image: ${OPENCLAW_IMAGE:-ghcr.io/openclaw/openclaw:latest}
    env_file:
      - .env
    environment:
      HOME: /home/node
      OPENCLAW_HOME: /home/node
      OPENCLAW_STATE_DIR: /home/node/.openclaw
      OPENCLAW_CONFIG_PATH: /home/node/.openclaw/openclaw.json
      OPENCLAW_CONFIG_DIR: /home/node/.openclaw
      OPENCLAW_WORKSPACE_DIR: /home/node/.openclaw/workspace
      OPENCLAW_GATEWAY_PORT: "18789"
      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN}
      OPENCLAW_DISABLE_BONJOUR: "1"
      OPENCLAW_NO_RESPAWN: "1"
      NODE_COMPILE_CACHE: /tmp/openclaw-compile-cache
      TZ: ${OPENCLAW_TZ:-UTC}
    volumes:
      - /var/lib/sahjony-openclaw-state:/home/node/.openclaw
      - /var/lib/sahjony-openclaw-auth:/home/node/.config/openclaw
    cap_drop:
      - NET_RAW
      - NET_ADMIN
    security_opt:
      - no-new-privileges:true
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ports:
      - "127.0.0.1:18789:18789"
    init: true
    restart: unless-stopped
    command: ["node","dist/index.js","gateway","--bind","lan","--port","18789"]
    healthcheck:
      test: ["CMD","node","dist/docker-healthcheck.js"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 20s

  openclaw-cli:
    image: ${OPENCLAW_IMAGE:-ghcr.io/openclaw/openclaw:latest}
    network_mode: "service:openclaw-gateway"
    env_file:
      - .env
    environment:
      HOME: /home/node
      OPENCLAW_HOME: /home/node
      OPENCLAW_STATE_DIR: /home/node/.openclaw
      OPENCLAW_CONFIG_PATH: /home/node/.openclaw/openclaw.json
      OPENCLAW_CONFIG_DIR: /home/node/.openclaw
      OPENCLAW_WORKSPACE_DIR: /home/node/.openclaw/workspace
      OPENCLAW_GATEWAY_PORT: "18789"
      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN}
      BROWSER: echo
      TZ: ${OPENCLAW_TZ:-UTC}
    volumes:
      - /var/lib/sahjony-openclaw-state:/home/node/.openclaw
      - /var/lib/sahjony-openclaw-auth:/home/node/.config/openclaw
    cap_drop:
      - NET_RAW
      - NET_ADMIN
    security_opt:
      - no-new-privileges:true
    stdin_open: true
    tty: true
    init: true
    entrypoint: ["node","dist/index.js"]
    depends_on:
      - openclaw-gateway
COMPOSE
chmod 600 docker-compose.yml

log "pulling official image $IMAGE"
docker compose pull openclaw-gateway openclaw-cli

# Initialize only when no OpenClaw config exists yet.
if [[ ! -s "$STATE_DIR/openclaw.json" ]]; then
  log 'creating baseline OpenClaw state'
  docker compose run -T --rm --no-deps --entrypoint node openclaw-gateway \
    dist/index.js setup --baseline --workspace /home/node/.openclaw/workspace
fi

# Enforce the minimum local gateway configuration without embedding the secret token.
docker compose run -T --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js config set --batch-json '[{"path":"gateway.mode","value":"local"},{"path":"gateway.bind","value":"lan"},{"path":"gateway.auth.mode","value":"token"}]'

# Install the official WhatsApp plugin if possible. Core installation remains valid if
# capability review or registry availability requires a later retry.
set +e
docker compose run -T --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js plugins install clawhub:@openclaw/whatsapp >/tmp/sahjony-openclaw-whatsapp-plugin.log 2>&1
plugin_rc=$?
set -e
if [[ $plugin_rc -eq 0 ]]; then
  log 'WhatsApp plugin installed'
else
  log 'WhatsApp plugin deferred; OpenClaw core installation continues'
  tail -n 30 /tmp/sahjony-openclaw-whatsapp-plugin.log | sed -E 's/(token|secret|key|password)[=:][^[:space:]]+/\1=[REDACTED]/Ig' || true
fi

log 'starting OpenClaw gateway'
docker compose up -d openclaw-gateway

healthy=false
for i in $(seq 1 36); do
  status="$(docker inspect "$CONTAINER_NAME" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)"
  log "health probe $i/36: ${status:-unknown}"
  if [[ "$status" == healthy ]]; then healthy=true; break; fi
  if [[ "$status" == exited || "$status" == dead ]]; then break; fi
  sleep 5
done

if [[ "$healthy" != true ]]; then
  docker compose ps >&2 || true
  docker compose logs --tail=120 openclaw-gateway 2>&1 | sed -E 's/(token|secret|key|password)[=:][^[:space:]]+/\1=[REDACTED]/Ig' >&2 || true
  fail 'OpenClaw gateway did not become healthy'
fi

docker update --restart unless-stopped "$CONTAINER_NAME" >/dev/null
restart_policy="$(docker inspect "$CONTAINER_NAME" --format '{{.HostConfig.RestartPolicy.Name}}')"
[[ "$restart_policy" == unless-stopped || "$restart_policy" == always ]] || fail "unexpected restart policy: $restart_policy"

set +e
docker compose run -T --rm openclaw-cli gateway probe >/tmp/sahjony-openclaw-gateway-probe.log 2>&1
probe_rc=$?
set -e
if [[ $probe_rc -eq 0 ]]; then
  log 'gateway RPC probe ready'
else
  log 'gateway container healthy; RPC probe deferred/degraded'
  tail -n 30 /tmp/sahjony-openclaw-gateway-probe.log | sed -E 's/(token|secret|key|password)[=:][^[:space:]]+/\1=[REDACTED]/Ig' || true
fi

printf 'SAHJONY_OPENCLAW_CONTAINER=%s\n' "$CONTAINER_NAME"
printf 'SAHJONY_OPENCLAW_IMAGE=%s\n' "$(docker inspect "$CONTAINER_NAME" --format '{{.Config.Image}}')"
printf 'SAHJONY_OPENCLAW_RESTART_POLICY=%s\n' "$restart_policy"
printf 'SAHJONY_OPENCLAW_DOCKER_RUNTIME=READY\n'
