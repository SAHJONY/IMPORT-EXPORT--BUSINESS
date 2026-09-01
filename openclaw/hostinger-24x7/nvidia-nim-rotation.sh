#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${NVIDIA_NIM_STATE_DIR:-/var/lib/sahjony-nvidia-nim}"
LOG="${NVIDIA_NIM_LOG:-/var/log/sahjony-nvidia-nim.log}"
INVENTORY_URL="${NVIDIA_NIM_INVENTORY_URL:-https://integrate.api.nvidia.com/v1/models}"
LOCK_FILE="${NVIDIA_NIM_LOCK_FILE:-/run/lock/sahjony-nvidia-nim.lock}"

# Curated chat-capable models shipped by OpenClaw's NVIDIA provider. NVIDIA's
# public hosted catalog currently offers these models at zero model cost; actual
# availability/rate limits are checked dynamically instead of assumed forever.
CANDIDATES=(
  'nvidia/nemotron-3-ultra-550b-a55b'
  'deepseek-ai/deepseek-v4-pro'
  'moonshotai/kimi-k2.6'
  'z-ai/glm-5.2'
  'nvidia/nemotron-3-super-120b-a12b'
  'nvidia/nemotron-3.5-lightning-30b-a3b'
  'minimaxai/minimax-m3'
)

mkdir -p "$STATE_DIR" "$(dirname "$LOCK_FILE")"
chmod 700 "$STATE_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

log(){ printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }
fail(){ log "NVIDIA_NIM_ROTATION_FAIL=$*"; exit 1; }

command -v docker >/dev/null 2>&1 || fail docker_missing
command -v curl >/dev/null 2>&1 || fail curl_missing
command -v python3 >/dev/null 2>&1 || fail python3_missing

auth_present=false
cid="$(docker ps --format '{{.ID}} {{.Names}} {{.Image}}' | awk 'tolower($0) ~ /openclaw/ {print $1; exit}')"
[[ -n "$cid" ]] || fail openclaw_container_not_running

docker exec "$cid" sh -lc 'command -v openclaw >/dev/null 2>&1' || fail openclaw_cli_missing

# Ensure the stock NVIDIA provider stays enabled. No custom untrusted plugin is used.
docker exec "$cid" openclaw plugins enable nvidia >/dev/null 2>&1 || true

# Determine whether a usable NVIDIA auth profile exists without exposing secret data.
auth_json="$(docker exec "$cid" openclaw models auth list --provider nvidia --json 2>/dev/null || true)"
if AUTH_JSON="$auth_json" python3 - <<'PY'
import json, os, sys
raw=os.environ.get('AUTH_JSON','').strip()
if not raw:
    raise SystemExit(1)
try:
    data=json.loads(raw)
except Exception:
    raise SystemExit(1)
text=json.dumps(data).lower()
# Auth-list metadata varies by release; require a NVIDIA profile indicator and
# reject obvious empty/missing states. No key material is printed.
ok=('nvidia' in text and not ('"profiles": []' in text or '"profiles":[]' in text))
raise SystemExit(0 if ok else 1)
PY
then
  auth_present=true
fi

# Get live NVIDIA inference inventory. This endpoint is used only for model IDs;
# no API key is sent. If the inventory is temporarily unavailable, retain the
# last-known-good order, or fall back to OpenClaw's bundled curated list.
inventory="$(curl -fsS --connect-timeout 8 --max-time 20 "$INVENTORY_URL" 2>/dev/null || true)"
available_file="$STATE_DIR/available.txt"
: > "$available_file.tmp"
if [[ -n "$inventory" ]]; then
  INVENTORY="$inventory" python3 - <<'PY' > "$available_file.tmp" || true
import json, os
try:
    obj=json.loads(os.environ['INVENTORY'])
except Exception:
    raise SystemExit(1)
rows=obj.get('data', obj if isinstance(obj,list) else [])
for row in rows:
    if isinstance(row,dict):
        mid=row.get('id') or row.get('model')
        if isinstance(mid,str): print(mid)
PY
fi

if [[ -s "$available_file.tmp" ]]; then
  mv "$available_file.tmp" "$available_file"
else
  rm -f "$available_file.tmp"
fi

selected=()
if [[ -s "$available_file" ]]; then
  for id in "${CANDIDATES[@]}"; do
    grep -Fxq "$id" "$available_file" && selected+=("nvidia/$id")
  done
else
  # Inventory outage must not erase failover. Use bundled known-good refs.
  for id in "${CANDIDATES[@]}"; do selected+=("nvidia/$id"); done
fi

((${#selected[@]} > 0)) || fail no_curated_models_available

# Preserve any non-NVIDIA fallback models already configured, then append the
# dynamically available NVIDIA pool in capability-first order. OpenClaw handles
# immediate auth/rate-limit/timeout failover inside a turn; this controller only
# reconciles the candidate inventory and ordering.
model_json="$(docker exec "$cid" openclaw config get agents.defaults.model --json 2>/dev/null || echo '{}')"
MODEL_JSON="$model_json" NVIDIA_LIST="$(printf '%s\n' "${selected[@]}")" python3 - <<'PY' > "$STATE_DIR/target.json"
import json, os
try:
    obj=json.loads(os.environ.get('MODEL_JSON') or '{}')
except Exception:
    obj={}
old=obj.get('fallbacks') if isinstance(obj,dict) else []
if not isinstance(old,list): old=[]
non=[x for x in old if isinstance(x,str) and not x.startswith('nvidia/')]
nv=[x for x in os.environ.get('NVIDIA_LIST','').splitlines() if x]
seen=set(); out=[]
for x in non+nv:
    if x not in seen:
        seen.add(x); out.append(x)
print(json.dumps(out,separators=(',',':')))
PY

target="$(cat "$STATE_DIR/target.json")"
docker exec "$cid" openclaw config set agents.defaults.model.fallbacks "$target" --strict-json >/dev/null
docker exec "$cid" openclaw config validate >/dev/null

printf '%s\n' "${selected[@]}" > "$STATE_DIR/nvidia-order.txt"
chmod 600 "$STATE_DIR"/* 2>/dev/null || true

primary="$(docker exec "$cid" openclaw config get agents.defaults.model.primary 2>/dev/null || true)"
log "NVIDIA_NIM_ROTATION=READY auth=$auth_present primary=${primary:-unset} candidates=${#selected[@]}"
if [[ "$auth_present" == true ]]; then
  touch "$STATE_DIR/auth-ready"
  rm -f "$STATE_DIR/auth-required"
else
  touch "$STATE_DIR/auth-required"
  rm -f "$STATE_DIR/auth-ready"
  log 'NVIDIA_NIM_AUTH=REQUIRED rotation pool configured but inference waits for NVIDIA API key'
fi

# Keep status machine-readable for external health collectors.
AUTH_PRESENT="$auth_present" PRIMARY="$primary" COUNT="${#selected[@]}" python3 - <<'PY' > "$STATE_DIR/status.json.tmp"
import json, os, datetime
print(json.dumps({
  'status':'ready',
  'provider':'nvidia',
  'auth_ready': os.environ['AUTH_PRESENT']=='true',
  'primary_preserved': os.environ.get('PRIMARY',''),
  'rotation_mode':'live_inventory_plus_runtime_failover',
  'candidate_count': int(os.environ['COUNT']),
  'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, separators=(',',':')))
PY
mv "$STATE_DIR/status.json.tmp" "$STATE_DIR/status.json"
