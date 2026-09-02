#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${NVIDIA_NIM_STATE_DIR:-/var/lib/sahjony-nvidia-nim}"
LOG="${NVIDIA_NIM_LOG:-/var/log/sahjony-nvidia-nim.log}"
INVENTORY_URL="${NVIDIA_NIM_INVENTORY_URL:-https://integrate.api.nvidia.com/v1/models}"
LOCK_FILE="${NVIDIA_NIM_LOCK_FILE:-/run/lock/sahjony-nvidia-nim.lock}"
NATIVE_HOME="${OPENCLAW_NATIVE_HOME:-/home/node}"
NATIVE_STATE_DIR="${OPENCLAW_NATIVE_STATE_DIR:-/var/lib/sahjony-openclaw-state}"
NATIVE_CONFIG_PATH="${OPENCLAW_NATIVE_CONFIG_PATH:-${NATIVE_STATE_DIR}/openclaw.json}"

# Keep the rotation pool deliberately small. These NVIDIA NIMs have produced
# successful inference on this account/runtime. Do not re-add inventory-only
# models: an inventory listing does not guarantee account-level serving access.
# In particular, moonshotai/kimi-k2.6 produced provider 404s in production.
CANDIDATES=(
  'nvidia/nemotron-3.5-lightning-30b-a3b'
  'nvidia/nemotron-3-super-120b-a12b'
  'nvidia/nemotron-3-ultra-550b-a55b'
)

mkdir -p "$STATE_DIR" "$(dirname "$LOCK_FILE")"
chmod 700 "$STATE_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

log(){ printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }
fail(){ log "NVIDIA_NIM_ROTATION_FAIL=$*"; exit 1; }

command -v curl >/dev/null 2>&1 || fail curl_missing
command -v python3 >/dev/null 2>&1 || fail python3_missing

RUNTIME=""
CID=""
if command -v openclaw >/dev/null 2>&1 && systemctl cat openclaw-gateway.service >/dev/null 2>&1; then
  RUNTIME=native
elif command -v docker >/dev/null 2>&1; then
  CID="$(docker ps --format '{{.ID}} {{.Names}} {{.Image}}' | awk 'tolower($0) ~ /openclaw/ {print $1; exit}')"
  [[ -n "$CID" ]] && RUNTIME=docker
fi
[[ -n "$RUNTIME" ]] || fail openclaw_runtime_not_found

oc(){
  if [[ "$RUNTIME" == native ]]; then
    env HOME="$NATIVE_HOME" \
        OPENCLAW_HOME="$NATIVE_HOME" \
        OPENCLAW_STATE_DIR="$NATIVE_STATE_DIR" \
        OPENCLAW_CONFIG_PATH="$NATIVE_CONFIG_PATH" \
        openclaw "$@"
  else
    docker exec "$CID" openclaw "$@"
  fi
}

if [[ "$RUNTIME" == docker ]]; then
  docker exec "$CID" sh -lc 'command -v openclaw >/dev/null 2>&1' || fail openclaw_cli_missing
else
  [[ -f "$NATIVE_CONFIG_PATH" ]] || fail native_config_missing
  systemctl is-active --quiet openclaw-gateway.service || fail native_gateway_inactive
fi

oc plugins enable nvidia >/dev/null 2>&1 || true

auth_present=false
auth_json="$(oc models auth list --provider nvidia --json 2>/dev/null || true)"
if AUTH_JSON="$auth_json" python3 - <<'PY'
import json, os
raw=os.environ.get('AUTH_JSON','').strip()
if not raw: raise SystemExit(1)
try: data=json.loads(raw)
except Exception: raise SystemExit(1)
text=json.dumps(data).lower()
ok=('nvidia' in text and not ('"profiles": []' in text or '"profiles":[]' in text))
raise SystemExit(0 if ok else 1)
PY
then
  auth_present=true
fi

inventory="$(curl -fsS --connect-timeout 8 --max-time 20 "$INVENTORY_URL" 2>/dev/null || true)"
available_file="$STATE_DIR/available.txt"
: > "$available_file.tmp"
if [[ -n "$inventory" ]]; then
  INVENTORY="$inventory" python3 - <<'PY' > "$available_file.tmp" || true
import json, os
try: obj=json.loads(os.environ['INVENTORY'])
except Exception: raise SystemExit(1)
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
  for id in "${CANDIDATES[@]}"; do selected+=("nvidia/$id"); done
fi
((${#selected[@]} > 0)) || fail no_curated_models_available

# Replace the NVIDIA fallback pool instead of merging old candidates. This
# prevents removed/invalid inventory-only models from surviving indefinitely.
NVIDIA_LIST="$(printf '%s\n' "${selected[@]}")" python3 - <<'PY' > "$STATE_DIR/target.json"
import json, os
nv=[x for x in os.environ.get('NVIDIA_LIST','').splitlines() if x]
seen=set(); out=[]
for x in nv:
    if x not in seen:
        seen.add(x); out.append(x)
print(json.dumps(out,separators=(',',':')))
PY

target="$(cat "$STATE_DIR/target.json")"
oc config set agents.defaults.model.fallbacks "$target" --strict-json >/dev/null
oc config validate >/dev/null
printf '%s\n' "${selected[@]}" > "$STATE_DIR/nvidia-order.txt"
chmod 600 "$STATE_DIR"/* 2>/dev/null || true

primary="$(oc config get agents.defaults.model.primary 2>/dev/null || true)"
log "NVIDIA_NIM_ROTATION=READY runtime=$RUNTIME auth=$auth_present primary=${primary:-unset} candidates=${#selected[@]}"
if [[ "$auth_present" == true ]]; then
  touch "$STATE_DIR/auth-ready"; rm -f "$STATE_DIR/auth-required"
else
  touch "$STATE_DIR/auth-required"; rm -f "$STATE_DIR/auth-ready"
  log 'NVIDIA_NIM_AUTH=REQUIRED validated fallback pool retained but inference waits for NVIDIA API key'
fi

AUTH_PRESENT="$auth_present" PRIMARY="$primary" COUNT="${#selected[@]}" RUNTIME="$RUNTIME" python3 - <<'PY' > "$STATE_DIR/status.json.tmp"
import json, os, datetime
print(json.dumps({
  'status':'ready',
  'provider':'nvidia',
  'auth_ready': os.environ['AUTH_PRESENT']=='true',
  'primary_preserved': os.environ.get('PRIMARY',''),
  'runtime': os.environ.get('RUNTIME','unknown'),
  'rotation_mode':'validated_curated_runtime_failover',
  'candidate_count': int(os.environ['COUNT']),
  'updated_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, separators=(',',':')))
PY
mv "$STATE_DIR/status.json.tmp" "$STATE_DIR/status.json"
