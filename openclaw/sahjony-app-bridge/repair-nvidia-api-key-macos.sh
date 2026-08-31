#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
ENV_FILE="$OPENCLAW_HOME/.env"
TEST_MODEL="${SAHJONY_NVIDIA_TEST_MODEL:-deepseek-ai/deepseek-v4-flash-0731}"
ENDPOINT="https://integrate.api.nvidia.com/v1/chat/completions"

mkdir -p "$OPENCLAW_HOME"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

if [[ ! -t 0 ]]; then
  echo "ERROR: interactive terminal required to enter NVIDIA API key securely." >&2
  exit 2
fi

read -r -s -p "NVIDIA API key (nvapi-...): " NVIDIA_API_KEY
echo

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  echo "ERROR: key is empty." >&2
  exit 2
fi

if [[ "$NVIDIA_API_KEY" != nvapi-* ]]; then
  echo "ERROR: key does not start with nvapi-. This does not look like an NVIDIA hosted inference API key." >&2
  exit 3
fi

if (( ${#NVIDIA_API_KEY} < 20 )); then
  echo "ERROR: key length looks invalid for an NVIDIA hosted inference API key." >&2
  exit 3
fi

export NVIDIA_API_KEY

python3 - "$ENV_FILE" <<'PY'
import os, sys
from pathlib import Path
p = Path(sys.argv[1])
key = os.environ['NVIDIA_API_KEY']
lines = p.read_text().splitlines() if p.exists() else []
out = []
replaced = False
for line in lines:
    if line.startswith('NVIDIA_API_KEY='):
        if not replaced:
            out.append('NVIDIA_API_KEY=' + key)
            replaced = True
    else:
        out.append(line)
if not replaced:
    out.append('NVIDIA_API_KEY=' + key)
p.write_text('\n'.join(out).rstrip() + '\n')
PY
chmod 600 "$ENV_FILE"

launchctl setenv NVIDIA_API_KEY "$NVIDIA_API_KEY"

payload="$(python3 - "$TEST_MODEL" <<'PY'
import json, sys
print(json.dumps({
  'model': sys.argv[1],
  'messages': [{'role':'user','content':'Reply exactly NVIDIA_OK'}],
  'max_tokens': 32,
  'temperature': 0,
}))
PY
)"

body="$(mktemp)"
trap 'rm -f "$body"' EXIT
code="$(curl -sS -o "$body" -w '%{http_code}' "$ENDPOINT" \
  -H "Authorization: Bearer $NVIDIA_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "$payload")"

if [[ "$code" != "200" ]]; then
  echo "ERROR: NVIDIA inference authentication/test failed (HTTP $code)." >&2
  python3 - "$body" <<'PY'
import json, sys
from pathlib import Path
raw = Path(sys.argv[1]).read_text(errors='replace')
try:
    obj=json.loads(raw)
    for k in ('status','title','detail','error','message'):
        if k in obj:
            print(f'{k}: {obj[k]}')
except Exception:
    print(raw[:500])
PY
  exit 4
fi

result="$(python3 - "$body" <<'PY'
import json, sys
from pathlib import Path
obj=json.loads(Path(sys.argv[1]).read_text())
choices=obj.get('choices') or []
text=''
if choices:
    msg=choices[0].get('message') or {}
    text=msg.get('content') or ''
print(text.strip())
PY
)"

if [[ "$result" != *"NVIDIA_OK"* ]]; then
  echo "ERROR: NVIDIA returned HTTP 200 but test response was unexpected." >&2
  exit 5
fi

echo "NVIDIA_API_KEY_VALID"
echo "Inference test: PASS ($TEST_MODEL)"
echo "Key stored in $ENV_FILE and loaded into launchd (value not displayed)."

openclaw gateway restart >/dev/null
sleep 8
openclaw models status || true
