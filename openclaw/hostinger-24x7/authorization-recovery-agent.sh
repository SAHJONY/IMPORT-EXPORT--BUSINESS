#!/usr/bin/env bash
set -euo pipefail

# SAHJONY Hostinger/OpenClaw authorization recovery agent.
# This does NOT bypass authentication. It discovers already-authorized connection
# paths and safely selects the first usable one.

log(){ printf '[hostinger-recovery] %s\n' "$*"; }

OPENCLAW_HEALTH_URL="${OPENCLAW_HEALTH_URL:-https://www.sahjony.com/whatsapp/health}"
REPO_DIR="${REPO_DIR:-/opt/sahjony-openclaw/repo}"

probe_health(){
  curl -fsS --max-time 15 "$OPENCLAW_HEALTH_URL" 2>/dev/null || true
}

find_existing_openclaw(){
  if command -v docker >/dev/null 2>&1; then
    docker ps -a --format '{{.Names}} {{.Image}}' 2>/dev/null | grep -i openclaw || true
  fi
  command -v openclaw >/dev/null 2>&1 && command -v openclaw || true
}

find_authorized_ssh_material(){
  # Only reports presence; never prints private key contents.
  for key in "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_rsa"; do
    [ -s "$key" ] && printf '%s\n' "$key"
  done
}

find_hostinger_connector(){
  local cfg="$HOME/.openclaw/openclaw.json"
  [ -f "$cfg" ] || return 0
  grep -Eio 'hostinger[^" ]*|mcp[^" ]*hostinger[^" ]*' "$cfg" 2>/dev/null | head -20 || true
}

main(){
  log "preflight start"
  health="$(probe_health)"
  if printf '%s' "$health" | grep -q '"gateway_connected"[[:space:]]*:[[:space:]]*true'; then
    log "gateway already healthy; no recovery required"
    exit 0
  fi

  existing="$(find_existing_openclaw)"
  if [ -n "$existing" ]; then
    log "existing OpenClaw runtime detected"
    if [ -x "$REPO_DIR/openclaw/hostinger-24x7/bootstrap-existing-openclaw.sh" ]; then
      log "running non-destructive bootstrap"
      exec "$REPO_DIR/openclaw/hostinger-24x7/bootstrap-existing-openclaw.sh"
    fi
    log "bootstrap script not present at expected path"
    exit 20
  fi

  connector="$(find_hostinger_connector)"
  if [ -n "$connector" ]; then
    log "existing Hostinger/OpenClaw connector evidence detected; preserve it and use connector-native authorization"
    exit 10
  fi

  ssh_material="$(find_authorized_ssh_material)"
  if [ -n "$ssh_material" ]; then
    log "existing SSH identity detected locally (contents not exposed)"
    log "an SSH host/user is still required before remote execution can be attempted safely"
    exit 11
  fi

  log "no already-authorized Hostinger control path found"
  log "authentication cannot be bypassed; waiting for Hostinger Connector or SSH authorization"
  exit 12
}

main "$@"
