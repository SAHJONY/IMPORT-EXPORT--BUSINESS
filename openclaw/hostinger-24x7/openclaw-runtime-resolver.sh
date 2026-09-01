#!/usr/bin/env bash
set -euo pipefail

# Resolve the OpenClaw runtime on the authorized SAHJONY Hostinger Kali VPS.
# This tool never enters Hostinger Recovery, never touches Meta, and never logs out,
# re-pairs, or replaces the authorized WhatsApp Linked Device session.
#
# Automatic reconstruction is intentionally narrow: exactly one high-confidence
# retained compose definition backed by non-empty host bind state. If that gate is
# not met, deeper Docker/state forensics run read-only and the resolver stops.

RUNTIME_RECOVERY_SOURCE="${RUNTIME_RECOVERY_SOURCE:-/tmp/openclaw-runtime-recovery.sh}"
RUNTIME_RECOVERY="${RUNTIME_RECOVERY:-/usr/local/sbin/sahjony-openclaw-runtime-recovery}"
DOCKER_FORENSICS_SOURCE="${DOCKER_FORENSICS_SOURCE:-/tmp/openclaw-docker-metadata-forensics.sh}"
DOCKER_FORENSICS="${DOCKER_FORENSICS:-/usr/local/sbin/sahjony-openclaw-docker-forensics}"
STATE_AUDIT_SOURCE="${STATE_AUDIT_SOURCE:-/tmp/openclaw-state-audit.sh}"
STATE_AUDIT="${STATE_AUDIT:-/usr/local/sbin/sahjony-openclaw-state-audit}"
STATE_DIR="${SAHJONY_OPENCLAW_RESOLVER_STATE_DIR:-/var/lib/sahjony-openclaw-resolver}"
PLAN_LOG="$STATE_DIR/plan.log"
AUDIT_LOG="$STATE_DIR/audit.log"
DEEP_LOG="$STATE_DIR/deep-forensics.log"
READY_MARKER="$STATE_DIR/ready"

log(){ printf '[openclaw-runtime-resolver] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }

[[ "$(id -u)" -eq 0 ]] || fail 'run as root'
command -v docker >/dev/null 2>&1 || fail 'Docker is missing'
systemctl is-active --quiet docker.service || systemctl enable --now docker.service
install -d -m 700 "$STATE_DIR"

install_optional_tool(){
  local source="$1" dest="$2"
  if [[ -f "$source" ]]; then install -m 755 "$source" "$dest"; fi
  [[ ! -x "$dest" ]] || bash -n "$dest" || fail "syntax validation failed: $dest"
}

install_optional_tool "$RUNTIME_RECOVERY_SOURCE" "$RUNTIME_RECOVERY"
install_optional_tool "$DOCKER_FORENSICS_SOURCE" "$DOCKER_FORENSICS"
install_optional_tool "$STATE_AUDIT_SOURCE" "$STATE_AUDIT"
[[ -x "$RUNTIME_RECOVERY" ]] || fail "runtime forensic tool missing: $RUNTIME_RECOVERY"

openclaw_ids(){
  docker ps -aq 2>/dev/null | while read -r id; do
    [[ -n "$id" ]] || continue
    meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}|{{json .Config.Labels}}' 2>/dev/null || true)"
    grep -Eqi 'openclaw|open[-_ ]?claw|claw' <<<"$meta" && printf '%s\n' "$id"
  done
}

stabilize_one(){
  local id="$1"
  log "stabilizing existing OpenClaw container $id"
  docker update --restart unless-stopped "$id" >/dev/null
  [[ "$(docker inspect -f '{{.State.Running}}' "$id")" == true ]] || docker start "$id" >/dev/null
  docker inspect "$id" --format 'name={{.Name}} image={{.Config.Image}} status={{.State.Status}} restart={{.HostConfig.RestartPolicy.Name}}'
  docker exec "$id" sh -lc 'openclaw channels status --probe'
  date -u +'%Y-%m-%dT%H:%M:%SZ' > "$READY_MARKER"
  echo SAHJONY_OPENCLAW_RUNTIME_RESOLVER=READY
}

run_deep_forensics(){
  : > "$DEEP_LOG"
  echo '=== DEEP OPENCLAW FORENSICS ===' | tee -a "$DEEP_LOG"
  if [[ -x "$DOCKER_FORENSICS" ]]; then
    "$DOCKER_FORENSICS" 2>&1 | tee -a "$DEEP_LOG" || true
  else
    echo OPENCLAW_DOCKER_FORENSICS_TOOL_UNAVAILABLE=1 | tee -a "$DEEP_LOG"
  fi
  if [[ -x "$STATE_AUDIT" ]]; then
    "$STATE_AUDIT" 2>&1 | tee -a "$DEEP_LOG" || true
  else
    echo OPENCLAW_STATE_AUDIT_TOOL_UNAVAILABLE=1 | tee -a "$DEEP_LOG"
  fi
  echo "OPENCLAW_DEEP_FORENSICS_LOG=$DEEP_LOG"
}

mapfile -t ids < <(openclaw_ids)
if ((${#ids[@]} == 1)); then
  echo OPENCLAW_RUNTIME_DECISION=USE_EXISTING_CONTAINER
  stabilize_one "${ids[0]}"
  exit 0
elif ((${#ids[@]} > 1)); then
  printf '%s\n' "${ids[@]}" >&2
  run_deep_forensics
  echo OPENCLAW_RUNTIME_DECISION=AMBIGUOUS_EXISTING_CONTAINERS >&2
  exit 31
fi

log 'no OpenClaw container in current Docker metadata; starting read-only retained-state forensics'
set +e
"$RUNTIME_RECOVERY" audit >"$AUDIT_LOG" 2>&1
audit_rc=$?
set -e
cat "$AUDIT_LOG"
[[ "$audit_rc" == 0 ]] || { run_deep_forensics; fail "runtime audit failed rc=$audit_rc"; }

set +e
"$RUNTIME_RECOVERY" plan >"$PLAN_LOG" 2>&1
plan_rc=$?
set -e
cat "$PLAN_LOG"

case "$plan_rc" in
  0)
    if grep -q '^OPENCLAW_RUNTIME_DECISION=SAFE_RECONSTRUCTION_CANDIDATE_FOUND$' "$PLAN_LOG"; then
      log 'one evidence-backed reconstruction candidate found; executing guarded reconstruction'
      SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT=RECOVER_RETAINED_OPENCLAW "$RUNTIME_RECOVERY" reconstruct
    elif grep -q '^OPENCLAW_RUNTIME_DECISION=USE_EXISTING_CONTAINER$' "$PLAN_LOG"; then
      log 'planner found an existing container during the scan'
    else
      run_deep_forensics
      fail 'planner returned success without a recognized decision'
    fi
    ;;
  22)
    run_deep_forensics
    echo OPENCLAW_RUNTIME_RESOLUTION=BLOCKED_AMBIGUOUS_EXISTING_CONTAINERS >&2
    exit 32
    ;;
  24)
    run_deep_forensics
    echo OPENCLAW_RUNTIME_RESOLUTION=FORENSICS_REQUIRED_NO_SAFE_RECONSTRUCTION >&2
    exit 34
    ;;
  25)
    run_deep_forensics
    echo OPENCLAW_RUNTIME_RESOLUTION=FORENSICS_REQUIRED_MULTIPLE_SAFE_CANDIDATES >&2
    exit 35
    ;;
  141)
    run_deep_forensics
    echo OPENCLAW_RUNTIME_RESOLUTION=SIGPIPE_REGRESSION_DETECTED >&2
    exit 41
    ;;
  *)
    run_deep_forensics
    fail "unexpected runtime planner rc=$plan_rc"
    ;;
esac

mapfile -t ids < <(openclaw_ids)
((${#ids[@]} == 1)) || { run_deep_forensics; fail "resolver did not converge to exactly one OpenClaw container (count=${#ids[@]})"; }
stabilize_one "${ids[0]}"
