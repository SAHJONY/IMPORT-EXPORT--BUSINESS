#!/usr/bin/env bash
set -euo pipefail

# Evidence-based OpenClaw runtime recovery for the authorized SAHJONY Hostinger VPS.
# The forensic phase is Python-backed so bounded searches do not use early-exit
# shell pipelines that can surface SIGPIPE/rc=141 under `set -o pipefail`.
# Never logs out/re-pairs WhatsApp and never reconstructs from weak evidence.

MODE="${1:-audit}"
STATE_DIR="${SAHJONY_OPENCLAW_RECOVERY_STATE_DIR:-/var/lib/sahjony-openclaw-recovery}"
REPORT="$STATE_DIR/report.json"
DECISION="$STATE_DIR/decision.json"
ALLOW_TOKEN="${SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT:-}"
MIN_SCORE="${SAHJONY_OPENCLAW_MIN_RECOVERY_SCORE:-80}"

log(){ printf '[openclaw-runtime-recovery] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }

[[ "$MODE" =~ ^(audit|plan|reconstruct)$ ]] || fail 'mode must be audit, plan, or reconstruct'
[[ "$(id -u)" -eq 0 ]] || fail 'run as root on the authorized Hostinger Kali VPS'
command -v python3 >/dev/null 2>&1 || fail 'python3 is required'
[[ "$MIN_SCORE" =~ ^[0-9]+$ ]] || fail 'SAHJONY_OPENCLAW_MIN_RECOVERY_SCORE must be numeric'
install -d -m 700 "$STATE_DIR"

python3 - "$REPORT" "$DECISION" "$MIN_SCORE" <<'PY'
import json, os, re, shutil, subprocess, sys
from pathlib import Path

report_path, decision_path, min_score_s = sys.argv[1:]
min_score = int(min_score_s)
STATE_ROOTS = [
    '/root/.openclaw', '/root/.config/openclaw', '/var/lib/openclaw',
    '/opt/openclaw', '/srv/openclaw', '/root/openclaw', '/root/.hermes'
]
SEARCH_ROOTS = ['/root', '/opt', '/srv', '/etc', '/usr/local']
ARTIFACT_NAMES = {'docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml', '.env'}
MAX_ARTIFACTS = 500
MAX_STATE_FILES = 5000
MAX_BIND_FILES = 2000
MAX_FILE_BYTES = 2 * 1024 * 1024


def limited_file_count(path, limit):
    count = 0
    try:
        for _base, _dirs, files in os.walk(path, followlinks=False):
            count += len(files)
            if count >= limit:
                return limit
    except OSError:
        pass
    return count


def command_ok(args):
    try:
        return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
    except OSError:
        return False


def command_text(args):
    try:
        return subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True)
    except (OSError, subprocess.CalledProcessError):
        return ''


def collect_artifacts():
    found, seen = [], set()
    for root in SEARCH_ROOTS:
        if not os.path.isdir(root):
            continue
        for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
            dirs[:] = [d for d in dirs if d not in {'.git', 'node_modules', '__pycache__'}]
            for name in files:
                lname = name.lower()
                if not (name in ARTIFACT_NAMES or ('openclaw' in lname and (lname.endswith('.sh') or lname.endswith('.env')))):
                    continue
                path = os.path.join(base, name)
                if path in seen:
                    continue
                seen.add(path)
                try:
                    if os.path.getsize(path) > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                found.append(path)
                if len(found) >= MAX_ARTIFACTS:
                    return sorted(found)
    return sorted(found)


def read_text(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read(MAX_FILE_BYTES)
    except OSError:
        return ''


def score_artifact(path, host_state_present):
    text = read_text(path)
    lc = text.lower()
    score, reasons, service_hint = 0, [], False
    if re.search(r'openclaw|open[ _-]?claw|claw gateway|whatsapp', lc):
        score += 35; reasons.append('openclaw_reference'); service_hint = True
    if re.search(r'image:|docker run|docker compose|docker-compose', lc):
        score += 15; reasons.append('container_definition')
    if re.search(r'whatsapp|linked.?device|session|auth', lc):
        score += 10; reasons.append('session_reference')
    if re.search(r'restart:\s*(unless-stopped|always)|--restart[ =](unless-stopped|always)', lc):
        score += 5; reasons.append('restart_policy')

    raw_sources = set(re.findall(r'(/[A-Za-z0-9._/@+\-]+(?:/[A-Za-z0-9._@+\-]+)*)\s*:', text))
    raw_sources.update(re.findall(r'-v\s+(/[^\s:]+):', text))
    bind_sources, durable = [], False
    for src in sorted(raw_sources):
        if src.startswith('/var/lib/docker'):
            continue
        if os.path.exists(src):
            bind_sources.append(src)
            if limited_file_count(src, MAX_BIND_FILES) > 0:
                durable = True
    if host_state_present:
        score += 10; reasons.append('host_state_present')
    if durable:
        score += 30; reasons.append('durable_bind_state')
    if not service_hint:
        score = 0
    return {
        'score': min(score, 100), 'durable_bind_state': durable, 'path': path,
        'bind_sources': bind_sources, 'reasons': reasons,
    }

state = []
for p in STATE_ROOTS:
    if os.path.exists(p):
        try:
            size = int(command_text(['du', '-sb', p]).split()[0])
        except Exception:
            size = 0
        state.append({'path': p, 'files': limited_file_count(p, MAX_STATE_FILES), 'bytes': size})

artifacts = collect_artifacts()
candidates = [score_artifact(p, bool(state)) for p in artifacts]
candidates.sort(key=lambda x: (-x['score'], x['path']))
docker_binary = shutil.which('docker') is not None
docker_service = command_ok(['systemctl', 'is-active', '--quiet', 'docker.service'])
docker_state = os.path.isdir('/var/lib/docker') and any(Path('/var/lib/docker').iterdir()) if os.path.isdir('/var/lib/docker') else False
containerd_state = os.path.isdir('/var/lib/containerd') and any(Path('/var/lib/containerd').iterdir()) if os.path.isdir('/var/lib/containerd') else False

existing = []
if docker_binary and docker_service:
    for line in command_text(['docker', 'ps', '-a', '--format', '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}']).splitlines():
        if re.search(r'openclaw|open[-_ ]?claw|claw', line, re.I):
            existing.append(line)

eligible = [c for c in candidates if c['score'] >= min_score and c['durable_bind_state']]
if len(existing) == 1:
    decision = {'code': 0, 'class': 'USE_EXISTING_CONTAINER', 'existing_container': existing[0], 'candidate': None}
elif len(existing) > 1:
    decision = {'code': 22, 'class': 'AMBIGUOUS_EXISTING_CONTAINERS', 'existing_containers': existing, 'candidate': None}
elif len(eligible) == 0:
    decision = {'code': 24, 'class': 'FORENSICS_REQUIRED_NO_SAFE_RECONSTRUCTION', 'candidate': None}
elif len(eligible) > 1:
    decision = {'code': 25, 'class': 'FORENSICS_REQUIRED_MULTIPLE_HIGH_CONFIDENCE_CANDIDATES', 'candidates': eligible[:20], 'candidate': None}
else:
    decision = {'code': 0, 'class': 'SAFE_RECONSTRUCTION_CANDIDATE_FOUND', 'candidate': eligible[0]}

report = {
    'engine': 'python_pipefail_safe_v2', 'min_score': min_score,
    'docker': {'binary': docker_binary, 'service_active': docker_service,
               'docker_state_present': bool(docker_state), 'containerd_state_present': bool(containerd_state)},
    'retained_state_paths': state, 'existing_openclaw_containers': existing,
    'artifact_count': len(artifacts), 'candidates': candidates[:50], 'decision': decision,
}
with open(report_path, 'w', encoding='utf-8') as f:
    json.dump(report, f, indent=2, sort_keys=True)
with open(decision_path, 'w', encoding='utf-8') as f:
    json.dump(decision, f, indent=2, sort_keys=True)
print(json.dumps(report, indent=2, sort_keys=True))
PY

echo OPENCLAW_RUNTIME_FORENSIC_ENGINE=PYTHON_PIPEFAIL_SAFE_V2
[[ "$MODE" == audit ]] && { echo OPENCLAW_RUNTIME_AUDIT_COMPLETE=1; exit 0; }

read_decision(){ python3 - "$DECISION" "$1" <<'PY'
import json,sys
d=json.load(open(sys.argv[1],encoding='utf-8')); v=d.get(sys.argv[2])
if isinstance(v,(dict,list)): print(json.dumps(v,separators=(',',':')))
elif v is not None: print(v)
PY
}

RC="$(read_decision code)"
CLASS="$(read_decision class)"
[[ "$RC" =~ ^[0-9]+$ ]] || fail 'forensic decision code missing'
echo "OPENCLAW_RUNTIME_DECISION=$CLASS"

case "$CLASS" in
  USE_EXISTING_CONTAINER)
    echo "OPENCLAW_EXISTING_CONTAINER=$(read_decision existing_container)"; exit 0 ;;
  AMBIGUOUS_EXISTING_CONTAINERS)
    echo OPENCLAW_RECONSTRUCTION_PERMITTED=false; exit 22 ;;
  FORENSICS_REQUIRED_NO_SAFE_RECONSTRUCTION)
    echo OPENCLAW_RECONSTRUCTION_PERMITTED=false; exit 24 ;;
  FORENSICS_REQUIRED_MULTIPLE_HIGH_CONFIDENCE_CANDIDATES)
    echo OPENCLAW_RECONSTRUCTION_PERMITTED=false; exit 25 ;;
esac

CANDIDATE="$(python3 - "$DECISION" <<'PY'
import json,sys
c=json.load(open(sys.argv[1],encoding='utf-8')).get('candidate') or {}; print(c.get('path',''))
PY
)"
SCORE="$(python3 - "$DECISION" <<'PY'
import json,sys
c=json.load(open(sys.argv[1],encoding='utf-8')).get('candidate') or {}; print(c.get('score',0))
PY
)"
mapfile -t BIND_SOURCES < <(python3 - "$DECISION" <<'PY'
import json,sys
c=json.load(open(sys.argv[1],encoding='utf-8')).get('candidate') or {}
for p in c.get('bind_sources',[]): print(p)
PY
)
echo "OPENCLAW_RECOVERY_CANDIDATE=$CANDIDATE"
echo "OPENCLAW_RECOVERY_SCORE=$SCORE"
printf 'OPENCLAW_RECOVERY_BIND_SOURCE=%s\n' "${BIND_SOURCES[@]:-}"
echo OPENCLAW_RECONSTRUCTION_PERMITTED=true
[[ "$MODE" == plan ]] && exit 0

[[ "$ALLOW_TOKEN" == RECOVER_RETAINED_OPENCLAW ]] || fail 'reconstruct requires SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT=RECOVER_RETAINED_OPENCLAW'
[[ "$CANDIDATE" =~ (docker-compose|compose)\.ya?ml$ ]] || fail 'automatic reconstruction is restricted to a retained compose file'
((${#BIND_SOURCES[@]} > 0)) || fail 'safe reconstruction requires at least one retained host bind source'
for src in "${BIND_SOURCES[@]}"; do [[ -e "$src" ]] || fail "retained bind source disappeared: $src"; done
command -v docker >/dev/null 2>&1 || fail 'docker binary missing; restore Docker before reconstruct'
systemctl is-active --quiet docker.service || systemctl start docker.service
compose_cmd=()
if docker compose version >/dev/null 2>&1; then compose_cmd=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then compose_cmd=(docker-compose)
else fail 'Docker Compose is unavailable'
fi
"${compose_cmd[@]}" -f "$CANDIDATE" config >/tmp/sahjony-openclaw-compose.resolved.yml
log "reconstructing only from retained compose evidence: $CANDIDATE"
"${compose_cmd[@]}" -f "$CANDIDATE" up -d --no-build
sleep 3
mapfile -t AFTER < <(docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}' | grep -Ei 'openclaw|open[-_ ]?claw|claw' || true)
((${#AFTER[@]} == 1)) || fail "reconstruction did not result in exactly one OpenClaw-like container (count=${#AFTER[@]})"
CID="${AFTER[0]%%|*}"
docker update --restart unless-stopped "$CID" >/dev/null
[[ "$(docker inspect -f '{{.State.Running}}' "$CID")" == true ]] || docker start "$CID" >/dev/null
docker exec "$CID" sh -lc 'openclaw channels status --probe'
echo "OPENCLAW_RECONSTRUCTED_CONTAINER=$CID"
echo OPENCLAW_RUNTIME_RECONSTRUCTION=READY
