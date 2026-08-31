#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
CONFIG="$OPENCLAW_HOME/openclaw.json"
ENV_FILE="$OPENCLAW_HOME/.env"
BACKUP_DIR="$OPENCLAW_HOME/backups/model-rotation"
NVIDIA_BASE_URL="${NVIDIA_BASE_URL:-https://integrate.api.nvidia.com/v1}"

CANDIDATES=(
  "nvidia/nemotron-3-super-120b-a12b"
  "nvidia/nemotron-3-nano-30b-a3b"
  "deepseek-ai/deepseek-v4-flash-0731"
)

mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d%H%M%S)"
cp "$CONFIG" "$BACKUP_DIR/openclaw.json.nvidia-probe.$stamp"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "ERROR: NVIDIA_API_KEY is not available in environment or $ENV_FILE" >&2
  exit 2
fi

MODELS_JSON="$(mktemp)"
trap 'rm -f "$MODELS_JSON"' EXIT

http_code="$(curl -sS -o "$MODELS_JSON" -w '%{http_code}' --max-time 30 \
  "$NVIDIA_BASE_URL/models" \
  -H "Authorization: Bearer $NVIDIA_API_KEY")"

if [[ "$http_code" != "200" ]]; then
  echo "ERROR: NVIDIA /models probe failed with HTTP $http_code" >&2
  python3 - "$MODELS_JSON" <<'PY'
import json, sys
try:
    d=json.load(open(sys.argv[1]))
    print(json.dumps(d, indent=2)[:2000])
except Exception:
    pass
PY
  exit 3
fi

mapfile_compat() {
  while IFS= read -r line; do
    [[ -n "$line" ]] && printf '%s\n' "$line"
  done
}

available_models="$(python3 - "$MODELS_JSON" <<'PY'
import json, sys
j=json.load(open(sys.argv[1]))
for row in j.get('data', []):
    mid=row.get('id')
    if mid:
        print(mid)
PY
)"

healthy=()
failed=()

echo "=== NVIDIA direct inference probes ==="
for model in "${CANDIDATES[@]}"; do
  if ! grep -Fxq "$model" <<<"$available_models"; then
    echo "SKIP $model — not present in live /models inventory"
    failed+=("$model:not-in-inventory")
    continue
  fi

  body="$(mktemp)"
  code="$(curl -sS -o "$body" -w '%{http_code}' --max-time 45 \
    "$NVIDIA_BASE_URL/chat/completions" \
    -H "Authorization: Bearer $NVIDIA_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply exactly NVIDIA_OK\"}],\"max_tokens\":16,\"temperature\":0}")" || code="curl-error"

  ok="$(python3 - "$body" "$code" <<'PY'
import json, sys
path, code = sys.argv[1], sys.argv[2]
try:
    d=json.load(open(path))
except Exception:
    d={}
text=''
try:
    text=d['choices'][0]['message']['content'] or ''
except Exception:
    pass
if code == '200' and text.strip():
    print('yes')
else:
    print('no')
PY
)"

  if [[ "$ok" == "yes" ]]; then
    echo "PASS $model"
    healthy+=("$model")
  else
    echo "FAIL $model — HTTP $code"
    python3 - "$body" <<'PY'
import json, sys
try:
    d=json.load(open(sys.argv[1]))
    err=d.get('error', d)
    print('  response:', json.dumps(err, ensure_ascii=False)[:800])
except Exception:
    pass
PY
    failed+=("$model:http-$code")
  fi
  rm -f "$body"
done

if [[ ${#healthy[@]} -eq 0 ]]; then
  echo "ERROR: No NVIDIA fallback model passed direct inference. Config was not changed." >&2
  exit 4
fi

# Convert NVIDIA API model ids to OpenClaw model refs by prefixing provider name.
refs=()
for model in "${healthy[@]}"; do
  refs+=("nvidia/$model")
done

python3 - "$CONFIG" "${refs[@]}" <<'PY'
import json, sys
from pathlib import Path
p=Path(sys.argv[1])
nvidia_refs=sys.argv[2:]
d=json.loads(p.read_text())
defaults=d.setdefault('agents',{}).setdefault('defaults',{})
model=defaults.setdefault('model',{})
if isinstance(model, str):
    model={'primary':model,'fallbacks':[]}
    defaults['model']=model
primary=model.get('primary','openai/gpt-5.6-sol')
# Keep one OpenAI fallback last, but make healthy NVIDIA routes first.
existing=model.get('fallbacks',[]) or []
openai_tail=[]
for ref in existing:
    if ref.startswith('openai/') and ref != primary and ref not in openai_tail:
        openai_tail.append(ref)
if 'openai/gpt-5.4' not in openai_tail and primary != 'openai/gpt-5.4':
    openai_tail.append('openai/gpt-5.4')
model['fallbacks']=list(nvidia_refs)+openai_tail

policy=defaults.setdefault('modelPolicy',{})
allow=policy.get('allow') or []
merged=[]
for ref in list(allow)+[primary]+list(nvidia_refs)+openai_tail:
    if ref and ref not in merged:
        merged.append(ref)
policy['allow']=merged

models=defaults.setdefault('models',{})
for ref in [primary]+list(nvidia_refs)+openai_tail:
    models.setdefault(ref,{})
for ref in [primary]+openai_tail:
    if ref.startswith('openai/'):
        models.setdefault(ref,{})['agentRuntime']={'id':'openclaw'}

p.write_text(json.dumps(d, indent=2)+'\n')
print('Repaired fallback chain:')
print(' primary:', primary)
for i, ref in enumerate(model['fallbacks'],1):
    print(f' fallback {i}: {ref}')
PY

if ! openclaw config validate; then
  echo "Validation failed; restoring backup." >&2
  cp "$BACKUP_DIR/openclaw.json.nvidia-probe.$stamp" "$CONFIG"
  exit 5
fi

openclaw gateway restart
sleep 10

echo
echo "=== OpenClaw route ==="
openclaw models status || true

echo
echo "=== WhatsApp ==="
openclaw channels status --probe || true

echo
echo "NVIDIA_FALLBACK_PROBE_AND_REPAIR_OK"
echo "Healthy NVIDIA models: ${healthy[*]}"
if [[ ${#failed[@]} -gt 0 ]]; then
  echo "Failed/skipped NVIDIA models: ${failed[*]}"
fi
