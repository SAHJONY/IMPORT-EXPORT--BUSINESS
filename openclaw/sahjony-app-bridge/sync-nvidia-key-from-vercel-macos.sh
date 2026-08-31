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

# Parse the dotenv file without sourcing arbitrary values into the shell.
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

if [[ "$NVIDIA_KEY" != nvapi-* ]]; then
  echo "ERROR: Vercel NVIDIA_API_KEY does not look like a hosted NVIDIA NIM key (expected nvapi- prefix)."
  echo "Detected prefix only: ${NVIDIA_KEY:0:8}"
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
HTTP="$(curl -sS -o /tmp/sahjony-nvidia-sync-test.json -w '%{http_code}' \
  https://integrate.api.nvidia.com/v1/chat/completions \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-ai/deepseek-v4-flash-0731","messages":[{"role":"user","content":"Reply exactly NVIDIA_OK"}],"max_tokens":20,"temperature":0}')"

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
text=''
try: text=d['choices'][0]['message']['content'] or ''
except Exception: pass
print('Inference response:', text[:120].replace('\n',' '))
if 'NVIDIA_OK' not in text:
    raise SystemExit('ERROR: NVIDIA returned HTTP 200 but did not return expected inference text.')
PY

openclaw gateway restart >/dev/null
sleep 8
openclaw channels status --probe

echo "NVIDIA_VERCEL_TO_OPENCLAW_SYNC_OK"
