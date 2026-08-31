#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/IMPORT-EXPORT--BUSINESS"
OPENCLAW_DIR="${HOME}/.openclaw"
OPENCLAW_ENV="${OPENCLAW_DIR}/.env"
TMP_ENV="$(mktemp -t sahjony-vercel-env.XXXXXX)"
trap 'rm -f "$TMP_ENV"' EXIT

cd "$ROOT"

if ! command -v vercel >/dev/null 2>&1; then
  echo "ERROR: Vercel CLI not found in PATH."
  exit 2
fi

if ! command -v openclaw >/dev/null 2>&1; then
  echo "ERROR: OpenClaw CLI not found in PATH."
  exit 2
fi

mkdir -p "$OPENCLAW_DIR"

echo "Pulling Production environment from linked Vercel project..."
vercel env pull "$TMP_ENV" --environment=production --yes >/dev/null
chmod 600 "$TMP_ENV"

NVIDIA_KEY="$(python3 - "$TMP_ENV" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
for raw in p.read_text().splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    k, v = line.split('=', 1)
    if k.strip() != 'NVIDIA_API_KEY':
        continue
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in {'"', "'"}:
        v = v[1:-1]
    print(v, end='')
    break
PY
)"

if [[ -z "$NVIDIA_KEY" ]]; then
  echo "ERROR: NVIDIA_API_KEY is not present in Vercel Production env."
  exit 3
fi

if [[ "$NVIDIA_KEY" == \[SENSITIVE* || "$NVIDIA_KEY" == SENSITIVE* || "$NVIDIA_KEY" == *"Sensitive values cannot be read"* ]]; then
  echo "Vercel confirms NVIDIA_API_KEY exists, but it is Sensitive and cannot be read back."
  echo "Enter the same NVIDIA NIM key once to synchronize the local OpenClaw runtime."
  IFS= read -r -s -p "NVIDIA API key (nvapi-...): " NVIDIA_KEY
  echo
fi

if [[ "$NVIDIA_KEY" != nvapi-* ]]; then
  echo "ERROR: NVIDIA_API_KEY does not look like a hosted NVIDIA NIM key (expected nvapi- prefix)."
  if [[ -n "$NVIDIA_KEY" ]]; then
    echo "Detected prefix only: ${NVIDIA_KEY:0:8}"
  fi
  exit 4
fi

if (( ${#NVIDIA_KEY} < 30 )); then
  echo "ERROR: NVIDIA_API_KEY is unexpectedly short."
  exit 4
fi

python3 - "$OPENCLAW_ENV" "$NVIDIA_KEY" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
key = sys.argv[2]
lines = p.read_text().splitlines() if p.exists() else []
out = [line for line in lines if not line.startswith('NVIDIA_API_KEY=')]
out.append('NVIDIA_API_KEY=' + key)
p.write_text('\n'.join(out) + '\n')
PY
chmod 600 "$OPENCLAW_ENV"

launchctl setenv NVIDIA_API_KEY "$NVIDIA_KEY"
export NVIDIA_API_KEY="$NVIDIA_KEY"

echo "NVIDIA key synchronized to OpenClaw local environment (value hidden)."
echo "Prefix: ${NVIDIA_KEY:0:8}...  Length: ${#NVIDIA_KEY}"

echo "Testing hosted NVIDIA inference..."
HTTP="$(curl -sS -o /tmp/sahjony-nvidia-sync-test.json -w '%{http_code}' --max-time 60 \
  https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-ai/deepseek-v4-flash-0731","messages":[{"role":"user","content":"Reply exactly NVIDIA_OK. Do not explain."}],"max_tokens":256,"temperature":0}')"

if [[ "$HTTP" != "200" ]]; then
  echo "ERROR: NVIDIA inference test failed with HTTP $HTTP"
  python3 - <<'PY'
from pathlib import Path
p=Path('/tmp/sahjony-nvidia-sync-test.json')
if p.exists(): print(p.read_text()[:600])
PY
  exit 5
fi

python3 - <<'PY'
import json
from pathlib import Path
p=Path('/tmp/sahjony-nvidia-sync-test.json')
d=json.loads(p.read_text())
choices=d.get('choices') or []
if not choices:
    raise SystemExit('ERROR: NVIDIA returned HTTP 200 but no choices payload.')
choice=choices[0] if isinstance(choices[0], dict) else {}
msg=choice.get('message') or {}
content=msg.get('content') or choice.get('text') or d.get('output_text') or ''
reasoning=msg.get('reasoning_content') or msg.get('reasoning') or ''
finish=choice.get('finish_reason')
usage=d.get('usage') or {}
print('Inference HTTP: 200')
print('Finish reason:', finish)
print('Completion tokens:', usage.get('completion_tokens', 'unknown'))
if isinstance(content, list):
    parts=[]
    for item in content:
        if isinstance(item, dict): parts.append(str(item.get('text') or item.get('content') or ''))
        else: parts.append(str(item))
    content=''.join(parts)
print('Inference response:', str(content)[:160].replace('\n',' '))
if content and 'NVIDIA_OK' in str(content):
    print('NVIDIA_INFERENCE_TEXT_OK')
elif reasoning:
    print('NVIDIA_INFERENCE_AUTH_AND_MODEL_OK (reasoning response received)')
elif finish is not None or usage:
    print('NVIDIA_INFERENCE_AUTH_AND_MODEL_OK (valid completion envelope)')
else:
    raise SystemExit('ERROR: NVIDIA returned HTTP 200 but response shape was not a valid completion.')
PY

openclaw gateway restart >/dev/null
sleep 8
openclaw channels status --probe

echo "NVIDIA_VERCEL_TO_OPENCLAW_SYNC_OK"
