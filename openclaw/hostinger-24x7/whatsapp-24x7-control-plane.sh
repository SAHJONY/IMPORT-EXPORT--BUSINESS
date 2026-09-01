#!/usr/bin/env bash
set -euo pipefail

# SAHJONY WhatsApp 24/7 control plane.
# Intended for GitHub Actions or another authorized operator host.
# It never bypasses Meta/WhatsApp/Hostinger authentication. It selects among
# truthful health verification, safe SSH healing, and the reviewed V5.1
# Hostinger recovery workflow.

MODE="${MODE:-${1:-audit}}"
APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
HOST="${HOSTINGER_SSH_HOST:-69.62.68.67}"
USER="${HOSTINGER_SSH_USER:-root}"
SSH_KEY_FILE="${HOSTINGER_SSH_KEY_FILE:-${HOME}/.ssh/hostinger_control}"
REPO="${GITHUB_REPOSITORY:-SAHJONY/IMPORT-EXPORT--BUSINESS}"
GH_API="${GITHUB_API_URL:-https://api.github.com}"
RECOVERY_WORKFLOW="hostinger-recovery-docker-openclaw-v5.yml"
RECOVERY_COOLDOWN_MINUTES="${RECOVERY_COOLDOWN_MINUTES:-90}"
AUTO_RECOVERY="${SAHJONY_AUTO_RECOVERY:-false}"
FORCE_RECOVERY="${FORCE_RECOVERY:-false}"
GUARDIAN="${GUARDIAN_SCRIPT:-openclaw/hostinger-24x7/whatsapp-24x7-guardian.sh}"

log(){ printf '[whatsapp-control-plane] %s\n' "$*"; }
warn(){ printf '[whatsapp-control-plane] WARN: %s\n' "$*" >&2; }
fail(){ printf '[whatsapp-control-plane] FAIL: %s\n' "$*" >&2; exit 1; }

health_body(){ curl -fsS --max-time 15 "$APP_URL/whatsapp/health" 2>/dev/null || true; }

health_flag(){
  local body="$1" expr="$2"
  command -v jq >/dev/null 2>&1 || return 1
  jq -e "$expr" >/dev/null 2>&1 <<<"$body"
}

meta_ready(){
  local b="$1"
  health_flag "$b" '(.cloud_independent_of_local_mac // false) == true or (((.meta_cloud.send_ready // false) == true) and ((.meta_cloud.webhook_ready // false) == true))'
}

hostinger_ready(){
  local b="$1"
  health_flag "$b" '(.hostinger_independent_runtime // false) == true or ((.hostinger_openclaw.connected // false) == true) or (((.provider // "") == "openclaw") and ((.gateway_connected // false) == true))'
}

ssh_tcp(){ nc -z -w 4 "$HOST" 22 >/dev/null 2>&1; }

ssh_auth(){
  [[ -s "$SSH_KEY_FILE" ]] || return 1
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=6 \
    -i "$SSH_KEY_FILE" "$USER@$HOST" 'printf SAHJONY_SSH_OK' 2>/dev/null | grep -q SAHJONY_SSH_OK
}

run_guardian_remote(){
  [[ -r "$GUARDIAN" ]] || fail "guardian script not found: $GUARDIAN"
  log 'running safe Hostinger-local guardian over authenticated SSH'
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 \
    -i "$SSH_KEY_FILE" "$USER@$HOST" 'bash -s -- heal' <"$GUARDIAN"
}

gh_get(){
  local path="$1"
  [[ -n "${GITHUB_TOKEN:-}" ]] || return 1
  curl -fsS -H "Authorization: Bearer $GITHUB_TOKEN" -H 'Accept: application/vnd.github+json' \
    "$GH_API/repos/$REPO/$path"
}

recovery_runs(){ gh_get "actions/workflows/$RECOVERY_WORKFLOW/runs?per_page=10"; }

recovery_active(){
  local runs="$1"
  jq -e '[.workflow_runs[] | select(.status == "in_progress" or .status == "queued" or .status == "pending")] | length > 0' >/dev/null <<<"$runs"
}

recovery_in_cooldown(){
  local runs="$1" last ts now age
  last="$(jq -r '[.workflow_runs[] | select(.status == "completed")][0].created_at // empty' <<<"$runs")"
  [[ -n "$last" ]] || return 1
  ts="$(date -u -d "$last" +%s 2>/dev/null || echo 0)"
  now="$(date -u +%s)"
  age=$(( (now - ts) / 60 ))
  (( age >= 0 && age < RECOVERY_COOLDOWN_MINUTES ))
}

dispatch_recovery(){
  [[ -n "${GITHUB_TOKEN:-}" ]] || fail 'GITHUB_TOKEN unavailable; cannot dispatch reviewed recovery workflow'
  local runs
  runs="$(recovery_runs)" || fail 'unable to inspect Hostinger recovery workflow runs'
  if recovery_active "$runs"; then
    log 'a Hostinger recovery run is already active; refusing duplicate recovery'
    return 0
  fi
  if [[ "$FORCE_RECOVERY" != true ]] && recovery_in_cooldown "$runs"; then
    log "recent recovery is inside ${RECOVERY_COOLDOWN_MINUTES}m cooldown; refusing recovery loop"
    return 0
  fi
  log 'dispatching reviewed Hostinger Recovery V5.1 workflow'
  curl -fsS -o /dev/null -X POST \
    -H "Authorization: Bearer $GITHUB_TOKEN" \
    -H 'Accept: application/vnd.github+json' \
    -H 'Content-Type: application/json' \
    --data '{"ref":"main"}' \
    "$GH_API/repos/$REPO/actions/workflows/$RECOVERY_WORKFLOW/dispatches"
  log 'recovery workflow dispatched'
}

print_health_summary(){
  local b="$1" m=false h=false g=false
  [[ -n "$b" ]] || { printf '{"public_health_reachable":false}\n'; return; }
  meta_ready "$b" && m=true || true
  hostinger_ready "$b" && h=true || true
  health_flag "$b" '(.gateway_connected // false) == true' && g=true || true
  printf '{"public_health_reachable":true,"meta_cloud_ready":%s,"hostinger_ready":%s,"gateway_connected":%s}\n' "$m" "$h" "$g"
}

main(){
  command -v curl >/dev/null 2>&1 || fail 'curl is required'
  command -v jq >/dev/null 2>&1 || fail 'jq is required'
  command -v nc >/dev/null 2>&1 || fail 'netcat is required'

  local health
  health="$(health_body)"
  print_health_summary "$health"

  if [[ -n "$health" ]] && meta_ready "$health"; then
    log 'Meta Cloud transport is independently READY; production WhatsApp has a cloud-primary path'
    # Keep validating Hostinger fallback, but do not perform recovery solely because fallback is degraded.
    if hostinger_ready "$health"; then
      log 'Hostinger OpenClaw fallback is also READY'
      return 0
    fi
  fi

  if ssh_tcp; then
    log 'Hostinger TCP/22 is reachable'
    if ssh_auth; then
      log 'Hostinger SSH authentication is valid'
      if [[ "$MODE" == heal || "$MODE" == recover ]]; then
        run_guardian_remote || warn 'guardian completed with a degraded result'
        sleep 10
        health="$(health_body)"
        print_health_summary "$health"
      fi
      if [[ -n "$health" ]] && { meta_ready "$health" || hostinger_ready "$health"; }; then
        log 'WhatsApp has at least one production-ready transport after local healing'
        return 0
      fi
      [[ "$MODE" == verify ]] && fail 'SSH works but WhatsApp transport is not ready'
      warn 'SSH works; transport is still degraded and should be diagnosed locally before disk recovery'
      return 0
    fi
    warn 'TCP/22 is open but authorized SSH key is not accepted or unavailable'
  else
    warn 'Hostinger TCP/22 is not reachable'
  fi

  if [[ "$MODE" == recover ]]; then
    dispatch_recovery
    return 0
  fi

  if [[ "$MODE" == heal && "$AUTO_RECOVERY" == true ]]; then
    log 'AUTO_RECOVERY is enabled and safe local healing is unavailable'
    dispatch_recovery
    return 0
  fi

  if [[ "$MODE" == verify ]]; then
    fail 'neither Meta Cloud nor Hostinger OpenClaw is currently verified ready'
  fi

  log 'audit complete; recovery not authorized for this invocation'
}

case "$MODE" in
  audit|heal|recover|verify) main ;;
  *) fail "unsupported MODE '$MODE' (audit|heal|recover|verify)" ;;
esac
