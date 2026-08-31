#!/usr/bin/env bash
set -euo pipefail

redact() {
  sed -E \
    -e 's/(token|secret|password|api[_-]?key|authorization|cookie|bearer)[=: ]+[^ ,;]+/\1=<REDACTED>/Ig' \
    -e 's/(sk-[A-Za-z0-9_-]{12,}|nvapi-[A-Za-z0-9_-]{12,}|EA[A-Za-z0-9_-]{20,})/<REDACTED_SECRET>/g'
}

echo '=== SAHJONY OPENCLAW HOST DISCOVERY ==='
echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "hostname=$(hostname 2>/dev/null || true)"
echo "kernel=$(uname -a 2>/dev/null || true)"
echo

echo '=== OpenClaw binary ==='
if command -v openclaw >/dev/null 2>&1; then
  command -v openclaw
  (openclaw --version 2>&1 || true) | redact
  (openclaw status --deep 2>&1 || openclaw status 2>&1 || true) | redact
else
  echo 'openclaw_binary=not_found_in_PATH'
fi

echo

echo '=== Docker containers matching OpenClaw/agent/gateway ==='
if command -v docker >/dev/null 2>&1; then
  docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}' 2>/dev/null \
    | grep -Ei 'openclaw|claw|agent|gateway|sahjony' || true
  echo
  echo '=== Docker volumes ==='
  docker volume ls --format '{{.Name}}' 2>/dev/null | grep -Ei 'openclaw|claw|agent|gateway|sahjony' || true
  echo
  echo '=== Candidate container mounts/ports (no environment variables) ==='
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    docker inspect "$id" --format 'name={{.Name}} image={{.Config.Image}} restart={{.HostConfig.RestartPolicy.Name}} ports={{json .NetworkSettings.Ports}} mounts={{range .Mounts}}{{.Type}}:{{.Source}}->{{.Destination}};{{end}}' 2>/dev/null | redact || true
  done < <(docker ps -aq --filter name=openclaw 2>/dev/null; docker ps -aq --filter name=claw 2>/dev/null)
else
  echo 'docker=not_found'
fi

echo

echo '=== systemd services ==='
if command -v systemctl >/dev/null 2>&1; then
  systemctl list-unit-files --type=service 2>/dev/null | grep -Ei 'openclaw|claw|agent|gateway|sahjony' || true
  systemctl --no-pager --plain --type=service --state=running 2>/dev/null | grep -Ei 'openclaw|claw|agent|gateway|sahjony' || true
fi

echo

echo '=== Processes ==='
ps aux 2>/dev/null | grep -Ei '[o]penclaw|[c]law.*gateway|[s]ahjony.*agent' | redact || true

echo

echo '=== Listening ports of interest ==='
if command -v ss >/dev/null 2>&1; then
  ss -lntp 2>/dev/null | grep -E ':18789|:3000|:3001|:8080|:80 |:443 ' | redact || true
elif command -v netstat >/dev/null 2>&1; then
  netstat -lntp 2>/dev/null | grep -E ':18789|:3000|:3001|:8080|:80 |:443 ' | redact || true
fi

echo

echo '=== Candidate OpenClaw state/config paths ==='
for p in \
  "$HOME/.openclaw" \
  /root/.openclaw \
  /home/*/.openclaw \
  /opt/openclaw \
  /srv/openclaw \
  /var/lib/openclaw; do
  if [ -e "$p" ]; then
    echo "$p"
    find "$p" -maxdepth 2 -type f \( -name 'openclaw.json' -o -name '*.sqlite' -o -name 'package.json' -o -name 'docker-compose.yml' -o -name 'compose.yml' \) -print 2>/dev/null | head -100
  fi
done

echo

echo '=== Reverse proxy hints ==='
for d in /etc/nginx/sites-enabled /etc/nginx/conf.d /etc/caddy /etc/traefik; do
  if [ -d "$d" ]; then
    grep -RHiE '18789|openclaw|gateway|websocket|proxy_pass' "$d" 2>/dev/null \
      | sed -E 's/(Authorization|token|secret|password).*/\1 <REDACTED>/Ig' \
      | head -150 || true
  fi
done

echo

echo '=== Public hostname clues (no secret values) ==='
(hostname -f 2>/dev/null || true)
if command -v curl >/dev/null 2>&1; then
  curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null | sed 's/^/public_ip=/' || true
fi

echo

echo 'DISCOVERY_COMPLETE=1'
