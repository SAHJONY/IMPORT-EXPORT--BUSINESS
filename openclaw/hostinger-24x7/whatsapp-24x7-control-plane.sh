#!/usr/bin/env bash
set -euo pipefail

# SAHJONY WhatsApp 24/7 control plane.
# Hostinger + Docker + OpenClaw is the authoritative production transport.
# No Meta Cloud dependency and no authentication/pairing bypass.

MODE="${MODE:-${1:-audit}}"
APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
HOST="${HOSTINGER_SSH_HOST:-69.62.68.67}"
USER="${HOSTINGER_SSH_USER:-root}"
SSH_KEY_FILE="${HOSTINGER_SSH_KEY_FILE:-${HOME}/.ssh/hostinger_control}"
REPO="${GITHUB_REPOSITORY:-SAHJONY/IMPORT-EXPORT--BUSINESS}"
GH_API="${GITHUB_API_URL:-https://api.github.com}"
LEGACY_RECOVERY_WORKFLOW="hostinger-recovery-docker-openclaw-v5.yml"
TARGET_RECOVERY_WORKFLOW="hostinger-whatsapp-24x7-recovery-v6.yml"
RECOVERY_COOLDOWN_MINUTES="${RECOVERY_COOLDOWN_MINUTES:-90}"
AUTO_RECOVERY="${SAHJONY_AUTO_RECOVERY:-false}"
FORCE_RECOVERY="${FORCE_RECOVERY:-false}"
GUARDIAN="${GUARDIAN_SCRIPT:-openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh}"

log(){ printf '[whatsapp-control-plane] %s\n' "$*"; }
warn(){ printf '[whatsapp-control-plane] WARN: %s\n' "$*" >&2; }
fail(){ printf '[whatsapp-control-plane] FAIL: %s\n' "$*" >&2; exit 1; }

health_body(){ curl -fsS --max-time 15 "$APP_URL/whatsapp/health" 2>/dev/null || true; }
health_flag(){ local body="$1" expr="$2"; jq -e "$expr" >/dev/null 2>&1 <<<"$body"; }
hostinger_ready(){ local b="$1"; health_flag "$b" '(.hostinger_independent_runtime // false) == true or ((.hostinger_openclaw.connected // false) == true)'; }
ssh_tcp(){ nc -z -w 4 "$HOST" 22 >/dev/null 2>&1; }
ssh_auth(){ [[ -s "$SSH_KEY_FILE" ]] && ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=6 -i "$SSH_KEY_FILE" "$USER@$HOST" 'printf SAHJONY_SSH_OK' 2>/dev/null | grep -q SAHJONY_SSH_OK; }

run_guardian_remote(){
  [[ -r "$GUARDIAN" ]] || fail "guardian script not found: $GUARDIAN"
  log 'persisting and installing Hostinger-only WhatsApp guardian over authenticated SSH'
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -i "$SSH_KEY_FILE" "$USER@$HOST" 'bash -s' < <(
    {
      cat <<'REMOTE'
set -euo pipefail
install -d -m 700 /opt/sahjony-openclaw
umask 077
cat > /opt/sahjony-openclaw/whatsapp-hostinger-only-guardian.sh <<'GUARDIAN_EOF'
REMOTE
      cat "$GUARDIAN"
      cat <<'REMOTE'
GUARDIAN_EOF
chmod 700 /opt/sahjony-openclaw/whatsapp-hostinger-only-guardian.sh
/opt/sahjony-openclaw/whatsapp-hostinger-only-guardian.sh install
REMOTE
    }
  )
}

gh_get(){ local path="$1"; [[ -n "${GITHUB_TOKEN:-}" ]] || return 1; curl -fsS -H "Authorization: Bearer $GITHUB_TOKEN" -H 'Accept: application/vnd.github+json' "$GH_API/repos/$REPO/$path"; }
workflow_runs(){ local wf="$1"; gh_get "actions/workflows/$wf/runs?per_page=10"; }

any_recovery_active(){
  local legacy target
  legacy="$(workflow_runs "$LEGACY_RECOVERY_WORKFLOW" 2>/dev/null || printf '{"workflow_runs":[]}')"
  target="$(workflow_runs "$TARGET_RECOVERY_WORKFLOW" 2>/dev/null || printf '{"workflow_runs":[]}')"
  jq -e -n --argjson a "$legacy" --argjson b "$target" '[$a.workflow_runs[], $b.workflow_runs[]] | any(.status == "in_progress" or .status == "queued" or .status == "pending")' >/dev/null
}

target_recovery_in_cooldown(){
  local runs last ts now age
  runs="$(workflow_runs "$TARGET_RECOVERY_WORKFLOW")" || return 1
  last="$(jq -r '[.workflow_runs[] | select(.status == "completed")][0].created_at // empty' <<<"$runs")"
  [[ -n "$last" ]] || return 1
  ts="$(date -u -d "$last" +%s 2>/dev/null || echo 0)"; now="$(date -u +%s)"; age=$(( (now - ts) / 60 ))
  (( age >= 0 && age < RECOVERY_COOLDOWN_MINUTES ))
}

dispatch_recovery(){
  [[ -n "${GITHUB_TOKEN:-}" ]] || fail 'GITHUB_TOKEN unavailable; cannot dispatch reviewed recovery workflow'
  if any_recovery_active; then log 'a V5/V6 Hostinger recovery is already active; refusing duplicate recovery'; return 0; fi
  if [[ "$FORCE_RECOVERY" != true ]] && target_recovery_in_cooldown; then log "V6 recovery is inside ${RECOVERY_COOLDOWN_MINUTES}m cooldown; refusing recovery loop"; return 0; fi
  log 'dispatching self-seeding Hostinger WhatsApp Recovery V6'
  curl -fsS -o /dev/null -X POST -H "Authorization: Bearer $GITHUB_TOKEN" -H 'Accept: application/vnd.github+json' -H 'Content-Type: application/json' --data '{"ref":"main"}' "$GH_API/repos/$REPO/actions/workflows/$TARGET_RECOVERY_WORKFLOW/dispatches"
  log 'Recovery V6 dispatched'
}

print_health_summary(){
  local b="$1" h=false
  [[ -n "$b" ]] || { printf '{"public_health_reachable":false,"authoritative_transport":"hostinger_openclaw"}\n'; return; }
  hostinger_ready "$b" && h=true || true
  printf '{"public_health_reachable":true,"authoritative_transport":"hostinger_openclaw","hostinger_ready":%s}\n' "$h"
}

main(){
  command -v curl >/dev/null 2>&1 || fail 'curl is required'; command -v jq >/dev/null 2>&1 || fail 'jq is required'; command -v nc >/dev/null 2>&1 || fail 'netcat is required'
  local health
  health="$(health_body)"; print_health_summary "$health"

  if [[ -n "$health" ]] && hostinger_ready "$health"; then
    log 'Hostinger OpenClaw WhatsApp transport is READY'
    return 0
  fi

  if ssh_tcp; then
    log 'Hostinger TCP/22 is reachable'
    if ssh_auth; then
      log 'Hostinger SSH authentication is valid'
      if [[ "$MODE" == heal || "$MODE" == recover ]]; then run_guardian_remote || warn 'guardian completed with a degraded result'; sleep 10; health="$(health_body)"; print_health_summary "$health"; fi
      if [[ -n "$health" ]] && hostinger_ready "$health"; then log 'Hostinger OpenClaw WhatsApp transport is READY after local healing'; return 0; fi
      [[ "$MODE" == verify ]] && fail 'SSH works but Hostinger WhatsApp transport is not ready'
      warn 'SSH works; Hostinger transport remains degraded and should be diagnosed locally before disk recovery'
      return 0
    fi
    warn 'TCP/22 is open but the durable SSH identity is unavailable or rejected'
  else
    warn 'Hostinger TCP/22 is not reachable'
  fi

  if [[ "$MODE" == recover ]]; then dispatch_recovery; return 0; fi
  if [[ "$MODE" == heal && "$AUTO_RECOVERY" == true ]]; then log 'AUTO_RECOVERY enabled; local healing unavailable'; dispatch_recovery; return 0; fi
  [[ "$MODE" == verify ]] && fail 'Hostinger OpenClaw WhatsApp transport is not verified ready'
  log 'audit/heal complete; Recovery was not authorized for this invocation'
}

case "$MODE" in audit|heal|recover|verify) main ;; *) fail "unsupported MODE '$MODE' (audit|heal|recover|verify)" ;; esac
