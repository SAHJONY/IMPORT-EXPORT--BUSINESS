#!/usr/bin/env bash
set -euo pipefail

# SAHJONY WhatsApp 24/7 control plane.
# Hostinger + Docker + OpenClaw is authoritative. Meta is not a dependency.
# Exactly one canonical recovery workflow is allowed to mutate VM 767852.

MODE="${MODE:-${1:-audit}}"
APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
HOST="${HOSTINGER_SSH_HOST:-69.62.68.67}"
USER="${HOSTINGER_SSH_USER:-root}"
SSH_KEY_FILE="${HOSTINGER_SSH_KEY_FILE:-${HOME}/.ssh/hostinger_control}"
REPO="${GITHUB_REPOSITORY:-SAHJONY/IMPORT-EXPORT--BUSINESS}"
GH_API="${GITHUB_API_URL:-https://api.github.com}"
TARGET_RECOVERY_WORKFLOW="hostinger-whatsapp-recovery-v7.yml"
RECOVERY_COOLDOWN_MINUTES="${RECOVERY_COOLDOWN_MINUTES:-90}"
AUTO_RECOVERY="${SAHJONY_AUTO_RECOVERY:-false}"
FORCE_RECOVERY="${FORCE_RECOVERY:-false}"
GUARDIAN="${GUARDIAN_SCRIPT:-openclaw/hostinger-24x7/whatsapp-guardian.sh}"
INSTALLER="${GUARDIAN_INSTALLER:-openclaw/hostinger-24x7/install-whatsapp-guardian.sh}"

log(){ printf '[whatsapp-control-plane] %s\n' "$*"; }
warn(){ printf '[whatsapp-control-plane] WARN: %s\n' "$*" >&2; }
fail(){ printf '[whatsapp-control-plane] FAIL: %s\n' "$*" >&2; exit 1; }
health_body(){ curl -fsS --max-time 15 "$APP_URL/whatsapp/health" 2>/dev/null || true; }
ssh_tcp(){ nc -z -w 4 "$HOST" 22 >/dev/null 2>&1; }
ssh_auth(){ [[ -s "$SSH_KEY_FILE" ]] && ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=6 -i "$SSH_KEY_FILE" "$USER@$HOST" 'printf SAHJONY_SSH_OK' 2>/dev/null | grep -q SAHJONY_SSH_OK; }

gh_get(){ local path="$1"; [[ -n "${GITHUB_TOKEN:-}" ]] || return 1; curl -fsS -H "Authorization: Bearer $GITHUB_TOKEN" -H 'Accept: application/vnd.github+json' "$GH_API/repos/$REPO/$path"; }
workflow_runs(){ gh_get "actions/workflows/$TARGET_RECOVERY_WORKFLOW/runs?per_page=10"; }

recovery_active(){
  local runs
  runs="$(workflow_runs 2>/dev/null || printf '{"workflow_runs":[]}')"
  jq -e '[.workflow_runs[]? | select(.status == "in_progress" or .status == "queued" or .status == "pending")] | length > 0' >/dev/null <<<"$runs"
}

recovery_in_cooldown(){
  local runs last ts now age
  runs="$(workflow_runs)" || return 1
  last="$(jq -r '[.workflow_runs[] | select(.status == "completed")][0].created_at // empty' <<<"$runs")"
  [[ -n "$last" ]] || return 1
  ts="$(date -u -d "$last" +%s 2>/dev/null || echo 0)"; now="$(date -u +%s)"; age=$(( (now - ts) / 60 ))
  (( age >= 0 && age < RECOVERY_COOLDOWN_MINUTES ))
}

dispatch_v7(){
  [[ -n "${GITHUB_TOKEN:-}" ]] || fail 'GITHUB_TOKEN unavailable'
  if recovery_active; then log 'canonical V7 already active/queued; duplicate dispatch refused'; return 0; fi
  if [[ "$FORCE_RECOVERY" != true ]] && recovery_in_cooldown; then log "canonical V7 inside ${RECOVERY_COOLDOWN_MINUTES}m cooldown; recovery loop refused"; return 0; fi
  log 'dispatching canonical Hostinger WhatsApp Recovery V7'
  curl -fsS -o /dev/null -X POST -H "Authorization: Bearer $GITHUB_TOKEN" -H 'Accept: application/vnd.github+json' -H 'Content-Type: application/json' --data '{"ref":"main"}' "$GH_API/repos/$REPO/actions/workflows/$TARGET_RECOVERY_WORKFLOW/dispatches"
  echo SAHJONY_CANONICAL_V7_DISPATCHED=1
}

heal_over_ssh(){
  [[ -r "$GUARDIAN" && -r "$INSTALLER" ]] || fail 'guardian files missing'
  local remote=/opt/sahjony/openclaw/hostinger-24x7
  scp -q -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "$SSH_KEY_FILE" "$GUARDIAN" "$INSTALLER" "$USER@$HOST:/tmp/"
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -i "$SSH_KEY_FILE" "$USER@$HOST" "install -d '$remote'; mv /tmp/whatsapp-guardian.sh /tmp/install-whatsapp-guardian.sh '$remote/'; chmod +x '$remote/'*.sh; cd '$remote' && ./install-whatsapp-guardian.sh; /usr/local/sbin/sahjony-whatsapp-guardian"
}

main(){
  command -v curl >/dev/null || fail 'curl required'; command -v jq >/dev/null || fail 'jq required'; command -v nc >/dev/null || fail 'netcat required'
  health="$(health_body)"
  if [[ -n "$health" ]]; then
    printf '%s\n' "$health" | jq '{status,provider,gateway_connected,hostinger_independent_runtime,hostinger_openclaw}' 2>/dev/null || true
  fi
  echo PUBLIC_HEALTH_IS_SECONDARY_EVIDENCE=1

  if ssh_tcp; then
    log 'Hostinger TCP/22 is reachable'
    if ssh_auth; then
      log 'durable Hostinger SSH authentication is valid'
      if [[ "$MODE" == heal || "$MODE" == recover ]]; then heal_over_ssh || warn 'local guardian returned degraded status'; fi
      [[ "$MODE" == verify ]] && heal_over_ssh
      return 0
    fi
    warn 'TCP/22 is open but durable SSH authentication is unavailable/rejected'
  else
    warn 'Hostinger TCP/22 is closed'
  fi

  case "$MODE" in
    recover) dispatch_v7 ;;
    heal) if [[ "$AUTO_RECOVERY" == true ]]; then dispatch_v7; else log 'automatic recovery disabled'; fi ;;
    verify) fail 'Hostinger local runtime cannot be verified over authenticated SSH' ;;
    audit) log 'audit complete; no mutation requested' ;;
    *) fail "unsupported MODE '$MODE'" ;;
  esac
}

main
