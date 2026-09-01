#!/usr/bin/env bash
set -euo pipefail

# Read-only diagnostic wrapper for the retained OpenClaw runtime planner.
# It never pairs/logs out WhatsApp, never creates a container, and never mutates
# Docker state. Its job is to turn planner failures into explicit classifications.

PLANNER="${SAHJONY_RUNTIME_PLANNER:-/usr/local/sbin/sahjony-openclaw-runtime-recovery}"
[[ -x "$PLANNER" ]] || PLANNER="${SAHJONY_RUNTIME_PLANNER_LOCAL:-openclaw/hostinger-24x7/openclaw-runtime-recovery.sh}"
REPORT="${SAHJONY_OPENCLAW_RECOVERY_STATE_DIR:-/var/lib/sahjony-openclaw-recovery}/report.json"

log(){ printf '[runtime-plan-doctor] %s\n' "$*"; }

[[ -f "$PLANNER" || -x "$PLANNER" ]] || { echo RUNTIME_PLANNER_MISSING=1 >&2; exit 2; }
bash -n "$PLANNER" || { echo RUNTIME_PLANNER_SYNTAX_INVALID=1 >&2; exit 3; }

log 'running read-only audit'
set +e
"$PLANNER" audit
AUDIT_RC=$?
set -e
if (( AUDIT_RC != 0 )); then
  echo "RUNTIME_AUDIT_RC=$AUDIT_RC"
  if (( AUDIT_RC == 141 )); then
    echo RUNTIME_PIPEFAIL_SIGPIPE_DETECTED=1
    echo RUNTIME_REMEDIATION=REPLACE_EARLY_EXIT_PIPELINES_WITH_FULL_DRAIN_LIMITERS
  fi
  exit "$AUDIT_RC"
fi

log 'running read-only plan classification'
set +e
"$PLANNER" plan
PLAN_RC=$?
set -e

echo "RUNTIME_PLAN_RC=$PLAN_RC"
case "$PLAN_RC" in
  0)
    echo RUNTIME_PLAN_CLASS=SAFE_ACTION_AVAILABLE
    ;;
  22)
    echo RUNTIME_PLAN_CLASS=AMBIGUOUS_EXISTING_CONTAINERS
    ;;
  24)
    echo RUNTIME_PLAN_CLASS=NO_SAFE_RECONSTRUCTION_CANDIDATE
    ;;
  25)
    echo RUNTIME_PLAN_CLASS=MULTIPLE_HIGH_CONFIDENCE_CANDIDATES
    ;;
  141)
    echo RUNTIME_PLAN_CLASS=PIPEFAIL_SIGPIPE
    echo RUNTIME_PIPEFAIL_SIGPIPE_DETECTED=1
    echo RUNTIME_REMEDIATION=USE_PIPEFAIL_SAFE_FORENSIC_ENGINE
    ;;
  *)
    echo RUNTIME_PLAN_CLASS=UNEXPECTED_FAILURE
    ;;
esac

if [[ -f "$REPORT" ]]; then
  python3 - "$REPORT" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,encoding='utf-8'))
except Exception as e:
    print('RUNTIME_REPORT_PARSE_ERROR='+str(e).replace('\n',' '))
    raise SystemExit(0)
print('RUNTIME_DOCKER_BINARY='+str(bool(d.get('docker',{}).get('binary'))).lower())
print('RUNTIME_DOCKER_ACTIVE='+str(bool(d.get('docker',{}).get('service_active'))).lower())
print('RUNTIME_DOCKER_STATE='+str(bool(d.get('docker',{}).get('docker_state_present'))).lower())
print('RUNTIME_CONTAINERD_STATE='+str(bool(d.get('docker',{}).get('containerd_state_present'))).lower())
print('RUNTIME_RETAINED_STATE_PATHS='+str(len(d.get('retained_state_paths',[]))))
c=d.get('candidates',[])
print('RUNTIME_CANDIDATE_COUNT='+str(len(c)))
for i,x in enumerate(c[:5],1):
    print(f"RUNTIME_CANDIDATE_{i}=score:{x.get('score',0)} durable:{str(bool(x.get('durable_bind_state'))).lower()} path:{x.get('path','')}")
PY
fi

# Treat forensic classifications as a successful doctor run: the doctor found
# the reason and did not perform a destructive action.
case "$PLAN_RC" in
  0|22|24|25) exit 0 ;;
  *) exit "$PLAN_RC" ;;
esac
