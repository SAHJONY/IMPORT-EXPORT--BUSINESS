#!/usr/bin/env bash
set -euo pipefail

# Evidence-based OpenClaw runtime recovery for the authorized SAHJONY Hostinger VPS.
# It never logs out/re-pairs WhatsApp and never fabricates a runtime from weak evidence.
#
# Commands:
#   audit        Read-only inventory and candidate scoring.
#   plan         Audit plus a human/machine-readable recovery decision.
#   reconstruct  Recreate ONLY an unambiguous compose runtime backed by retained
#                durable host state. Requires SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT.

MODE="${1:-audit}"
STATE_DIR="${SAHJONY_OPENCLAW_RECOVERY_STATE_DIR:-/var/lib/sahjony-openclaw-recovery}"
REPORT="$STATE_DIR/report.json"
CANDIDATES="$STATE_DIR/candidates.tsv"
ALLOW_TOKEN="${SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT:-}"
MIN_SCORE="${SAHJONY_OPENCLAW_MIN_RECOVERY_SCORE:-80}"

log(){ printf '[openclaw-runtime-recovery] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }
json_escape(){ python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().rstrip("\n")))'; }

[[ "$MODE" =~ ^(audit|plan|reconstruct)$ ]] || fail 'mode must be audit, plan, or reconstruct'
[[ "$(id -u)" -eq 0 ]] || fail 'run as root on the authorized Hostinger Kali VPS'
command -v python3 >/dev/null 2>&1 || fail 'python3 is required'
install -d -m 700 "$STATE_DIR"
: > "$CANDIDATES"

# Paths intentionally exclude /var/lib/docker: when Docker metadata is lost,
# a new Docker named volume could be empty and must not be mistaken for retained state.
STATE_ROOTS=(
  /root/.openclaw
  /root/.config/openclaw
  /var/lib/openclaw
  /opt/openclaw
  /srv/openclaw
  /root/openclaw
  /root/.hermes
)

state_evidence=()
for p in "${STATE_ROOTS[@]}"; do
  if [[ -e "$p" ]]; then
    count="$(find "$p" -xdev -type f 2>/dev/null | head -n 5000 | wc -l | tr -d ' ')"
    bytes="$(du -sb "$p" 2>/dev/null | awk '{print $1}' || echo 0)"
    state_evidence+=("$p|$count|$bytes")
  fi
done

# Broad artifact search, bounded to likely administration roots and small text files.
mapfile -t artifacts < <(
  find /root /opt /srv /etc /usr/local -xdev -type f \
    \( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'compose.yml' -o -name 'compose.yaml' -o -name '*openclaw*.sh' -o -name '*openclaw*.env' -o -name '.env' \) \
    -size -2M 2>/dev/null | sort -u | head -n 500
)

score_artifact(){
  local f="$1" score=0 reasons=() bind_sources=() durable=0 service_hint=0
  local lc
  lc="$(tr '[:upper:]' '[:lower:]' < "$f" 2>/dev/null || true)"
  if grep -Eq 'openclaw|open[ _-]?claw|claw gateway|whatsapp' <<<"$lc"; then score=$((score+35)); reasons+=(openclaw_reference); service_hint=1; fi
  if grep -Eq 'image:|docker run|docker compose|docker-compose' <<<"$lc"; then score=$((score+15)); reasons+=(container_definition); fi
  if grep -Eq 'whatsapp|linked.?device|session|auth' <<<"$lc"; then score=$((score+10)); reasons+=(session_reference); fi
  if grep -Eq 'restart:[[:space:]]*(unless-stopped|always)|--restart[ =](unless-stopped|always)' <<<"$lc"; then score=$((score+5)); reasons+=(restart_policy); fi

  # Extract likely absolute bind-mount sources from compose and docker-run syntax.
  # Avoid shell-quote gymnastics: capture absolute paths that immediately precede
  # a mount separator, then only count paths that actually exist on the host.
  while IFS= read -r src; do
    [[ -n "$src" ]] || continue
    [[ "$src" == /var/lib/docker* ]] && continue
    if [[ -e "$src" ]]; then
      bind_sources+=("$src")
      files="$(find "$src" -xdev -type f 2>/dev/null | head -n 2000 | wc -l | tr -d ' ')"
      if [[ "$files" =~ ^[0-9]+$ ]] && (( files > 0 )); then durable=1; fi
    fi
  done < <(
    {
      grep -Eo '(/[A-Za-z0-9._/@+-]+(/[A-Za-z0-9._@+-]+)*)[[:space:]]*:' "$f" 2>/dev/null | sed -E 's/[[:space:]]*:$//' || true
      grep -Eo -- '-v[[:space:]]+/[^[:space:]:]+:' "$f" 2>/dev/null | sed -E 's/^-v[[:space:]]+//; s/:$//' || true
    } | sort -u
  )

  # Explicit retained OpenClaw state elsewhere on host boosts confidence, but a
  # reconstruct action still requires a bind source to prevent empty-volume creation.
  if ((${#state_evidence[@]} > 0)); then score=$((score+10)); reasons+=(host_state_present); fi
  if (( durable == 1 )); then score=$((score+30)); reasons+=(durable_bind_state); fi
  if (( service_hint == 0 )); then score=0; fi
  (( score > 100 )) && score=100

  printf '%s\t%s\t%s\t%s\t%s\n' "$score" "$durable" "$f" "$(IFS=,; echo "${bind_sources[*]:-}")" "$(IFS=,; echo "${reasons[*]:-}")" >> "$CANDIDATES"
}

for f in "${artifacts[@]}"; do score_artifact "$f"; done
sort -t $'\t' -k1,1nr -k3,3 "$CANDIDATES" -o "$CANDIDATES"

# Docker facts are evidence only; audit never mutates.
docker_binary=false; docker_service=false; docker_root_present=false; containerd_root_present=false
command -v docker >/dev/null 2>&1 && docker_binary=true
systemctl is-active --quiet docker.service 2>/dev/null && docker_service=true || true
[[ -d /var/lib/docker && -n "$(find /var/lib/docker -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]] && docker_root_present=true
[[ -d /var/lib/containerd && -n "$(find /var/lib/containerd -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]] && containerd_root_present=true

existing_openclaw=()
if $docker_binary && $docker_service; then
  mapfile -t existing_openclaw < <(docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}' 2>/dev/null | grep -Ei 'openclaw|open[-_ ]?claw|claw' || true)
fi

python3 - "$REPORT" "$CANDIDATES" "$docker_binary" "$docker_service" "$docker_root_present" "$containerd_root_present" <<'PY'
import json,sys,os
report,cfile,dbin,dsvc,droot,croot=sys.argv[1:]
def b(v): return v.lower()=='true'
cands=[]
if os.path.exists(cfile):
    for line in open(cfile,encoding='utf-8',errors='replace'):
        parts=line.rstrip('\n').split('\t')
        if len(parts)<5: continue
        score,durable,path,binds,reasons=parts[:5]
        cands.append({"score":int(score),"durable_bind_state":durable=='1',"path":path,"bind_sources":[x for x in binds.split(',') if x],"reasons":[x for x in reasons.split(',') if x]})
state=[]
for p in ['/root/.openclaw','/root/.config/openclaw','/var/lib/openclaw','/opt/openclaw','/srv/openclaw','/root/openclaw','/root/.hermes']:
    if os.path.exists(p): state.append(p)
out={
  "docker":{"binary":b(dbin),"service_active":b(dsvc),"docker_state_present":b(droot),"containerd_state_present":b(croot)},
  "retained_state_paths":state,
  "candidates":cands[:50],
}
json.dump(out,open(report,'w'),indent=2,sort_keys=True)
print(json.dumps(out,indent=2,sort_keys=True))
PY

if [[ "$MODE" == audit ]]; then
  echo OPENCLAW_RUNTIME_AUDIT_COMPLETE=1
  exit 0
fi

mapfile -t eligible < <(awk -F '\t' -v min="$MIN_SCORE" '$1+0 >= min && $2==1 {print $0}' "$CANDIDATES")
if ((${#existing_openclaw[@]} == 1)); then
  log 'exactly one existing OpenClaw container is present; reconstruction is unnecessary'
  printf '%s\n' "${existing_openclaw[0]}"
  echo OPENCLAW_RUNTIME_DECISION=USE_EXISTING_CONTAINER
  exit 0
elif ((${#existing_openclaw[@]} > 1)); then
  printf '%s\n' "${existing_openclaw[@]}" >&2
  echo OPENCLAW_RUNTIME_DECISION=AMBIGUOUS_EXISTING_CONTAINERS
  exit 22
fi

if ((${#eligible[@]} == 0)); then
  echo OPENCLAW_RUNTIME_DECISION=FORENSICS_REQUIRED_NO_SAFE_RECONSTRUCTION
  echo OPENCLAW_RECONSTRUCTION_PERMITTED=false
  exit 24
fi
if ((${#eligible[@]} > 1)); then
  printf '%s\n' "${eligible[@]}"
  echo OPENCLAW_RUNTIME_DECISION=FORENSICS_REQUIRED_MULTIPLE_HIGH_CONFIDENCE_CANDIDATES
  echo OPENCLAW_RECONSTRUCTION_PERMITTED=false
  exit 25
fi

IFS=$'\t' read -r score durable candidate binds reasons <<<"${eligible[0]}"
echo "OPENCLAW_RECOVERY_CANDIDATE=$candidate"
echo "OPENCLAW_RECOVERY_SCORE=$score"
echo "OPENCLAW_RECOVERY_BIND_SOURCES=$binds"
echo OPENCLAW_RECONSTRUCTION_PERMITTED=true

if [[ "$MODE" == plan ]]; then
  echo OPENCLAW_RUNTIME_DECISION=SAFE_RECONSTRUCTION_CANDIDATE_FOUND
  exit 0
fi

[[ "$ALLOW_TOKEN" == RECOVER_RETAINED_OPENCLAW ]] || fail 'reconstruct requires SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT=RECOVER_RETAINED_OPENCLAW'
[[ "$candidate" =~ (docker-compose|compose)\.ya?ml$ ]] || fail 'automatic reconstruction is restricted to a retained compose file'
command -v docker >/dev/null 2>&1 || fail 'docker binary missing; restore Docker before reconstruct'
systemctl is-active --quiet docker.service || systemctl start docker.service

compose_cmd=()
if docker compose version >/dev/null 2>&1; then compose_cmd=(docker compose); elif command -v docker-compose >/dev/null 2>&1; then compose_cmd=(docker-compose); else fail 'Docker Compose is unavailable'; fi

# Validate config before any create/start operation.
"${compose_cmd[@]}" -f "$candidate" config >/tmp/sahjony-openclaw-compose.resolved.yml
# Re-check that every discovered retained bind source still exists immediately before reconstruction.
IFS=',' read -ra bind_arr <<<"$binds"
for src in "${bind_arr[@]}"; do [[ -e "$src" ]] || fail "retained bind source disappeared: $src"; done

log "reconstructing from retained compose evidence: $candidate"
"${compose_cmd[@]}" -f "$candidate" up -d --no-build
sleep 3
mapfile -t after < <(docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}|{{.Status}}' | grep -Ei 'openclaw|open[-_ ]?claw|claw' || true)
((${#after[@]} == 1)) || fail "reconstruction did not result in exactly one OpenClaw-like container (count=${#after[@]})"
cid="${after[0]%%|*}"
docker update --restart unless-stopped "$cid" >/dev/null
[[ "$(docker inspect -f '{{.State.Running}}' "$cid")" == true ]] || docker start "$cid" >/dev/null
# Probe only; never pair/logout here.
docker exec "$cid" sh -lc 'openclaw channels status --probe'
echo "OPENCLAW_RECONSTRUCTED_CONTAINER=$cid"
echo OPENCLAW_RUNTIME_RECONSTRUCTION=READY
