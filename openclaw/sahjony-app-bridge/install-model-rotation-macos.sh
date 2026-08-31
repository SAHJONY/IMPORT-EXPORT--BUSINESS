#!/usr/bin/env bash
set -euo pipefail

# SAHJONY LLC — OpenClaw autonomous model failover/rotation installer (macOS)
#
# Uses OpenClaw's native model fallback chain. Auth/key rotation occurs inside
# each provider first; OpenClaw then advances to the next fallback model.
#
# Default route:
#   1. openai/gpt-5.6-sol
#   2. nvidia/nvidia/nemotron-3-super-120b-a12b
#   3. nvidia/nvidia/nemotron-3-nano-30b-a3b
#   4. nvidia/deepseek-ai/deepseek-v4-flash-0731
#   5. openai/gpt-5.4
#
# The NVIDIA API key is never printed. If NVIDIA_API_KEY is not already in the
# environment or ~/.openclaw/.env, this script prompts securely for it.

OPENCLAW_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
CONFIG="$OPENCLAW_HOME/openclaw.json"
ENV_FILE="$OPENCLAW_HOME/.env"
BACKUP_DIR="$OPENCLAW_HOME/backups/model-rotation"

PRIMARY_MODEL="${SAHJONY_PRIMARY_MODEL:-openai/gpt-5.6-sol}"
NVIDIA_SUPER="${SAHJONY_NVIDIA_SUPER:-nvidia/nvidia/nemotron-3-super-120b-a12b}"
NVIDIA_NANO="${SAHJONY_NVIDIA_NANO:-nvidia/nvidia/nemotron-3-nano-30b-a3b}"
NVIDIA_FLASH="${SAHJONY_NVIDIA_FLASH:-nvidia/deepseek-ai/deepseek-v4-flash-0731}"
OPENAI_FALLBACK="${SAHJONY_OPENAI_FALLBACK:-openai/gpt-5.4}"

mkdir -p "$BACKUP_DIR"

if [[ ! -f "$CONFIG" ]]; then
  echo "ERROR: OpenClaw config not found: $CONFIG" >&2
  exit 1
fi

stamp="$(date +%Y%m%d%H%M%S)"
cp "$CONFIG" "$BACKUP_DIR/openclaw.json.$stamp"
[[ -f "$ENV_FILE" ]] && cp "$ENV_FILE" "$BACKUP_DIR/.env.$stamp"

echo "Backup created: $BACKUP_DIR/openclaw.json.$stamp"

# Resolve NVIDIA_API_KEY without exposing it.
if [[ -z "${NVIDIA_API_KEY:-}" && -f "$ENV_FILE" ]]; then
  NVIDIA_API_KEY="$(python3 - "$ENV_FILE" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
for raw in p.read_text().splitlines():
    line = raw.strip()
    if line.startswith('NVIDIA_API_KEY='):
        print(line.split('=', 1)[1].strip().strip('"').strip("'"))
        break
PY
)"
fi

if [[ -z "${NVIDIA_API_KEY:-}" ]]; then
  if [[ ! -t 0 ]]; then
    echo "ERROR: NVIDIA_API_KEY is required. Export it or add it to ~/.openclaw/.env first." >&2
    exit 2
  fi
  read -r -s -p "NVIDIA API key (nvapi-...): " NVIDIA_API_KEY
  echo
fi

if [[ -z "$NVIDIA_API_KEY" ]]; then
  echo "ERROR: NVIDIA_API_KEY is empty." >&2
  exit 2
fi

# Persist key in the local OpenClaw env file only; never echo the value.
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"
python3 - "$ENV_FILE" "$NVIDIA_API_KEY" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
value = sys.argv[2]
lines = p.read_text().splitlines() if p.exists() else []
out = []
replaced = False
for line in lines:
    if line.strip().startswith('NVIDIA_API_KEY='):
        if not replaced:
            out.append('NVIDIA_API_KEY=' + value)
            replaced = True
    else:
        out.append(line)
if not replaced:
    out.append('NVIDIA_API_KEY=' + value)
p.write_text('\n'.join(out).rstrip() + '\n')
PY
chmod 600 "$ENV_FILE"

# Make the key visible to the macOS LaunchAgent environment for the current
# login session. The key is not printed.
launchctl setenv NVIDIA_API_KEY "$NVIDIA_API_KEY"
export NVIDIA_API_KEY

# Configure native provider-independent failover. Keep explicit model catalog
# entries so the models are selectable without restricting unrelated models.
python3 - "$CONFIG" "$PRIMARY_MODEL" "$NVIDIA_SUPER" "$NVIDIA_NANO" "$NVIDIA_FLASH" "$OPENAI_FALLBACK" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
primary, super_model, nano_model, flash_model, openai_fallback = sys.argv[2:]
d = json.loads(config_path.read_text())

defaults = d.setdefault('agents', {}).setdefault('defaults', {})
defaults['model'] = {
    'primary': primary,
    'fallbacks': [super_model, nano_model, flash_model, openai_fallback],
}

# Force the OpenAI models through embedded OpenClaw, not an agent harness.
models = defaults.setdefault('models', {})
for ref in [primary, openai_fallback]:
    cfg = models.setdefault(ref, {})
    cfg['agentRuntime'] = {'id': 'openclaw'}

# Add NVIDIA model rows to the local selectable catalog. Provider ownership
# and live availability are still resolved by the NVIDIA provider plugin.
for ref in [super_model, nano_model, flash_model]:
    models.setdefault(ref, {})

config_path.write_text(json.dumps(d, indent=2) + '\n')
print('Configured autonomous model route:')
print('  primary :', primary)
for idx, ref in enumerate([super_model, nano_model, flash_model, openai_fallback], 1):
    print(f'  fallback {idx}: {ref}')
PY

# Validate before touching the running gateway. Roll back config automatically
# if validation fails.
if ! openclaw config validate; then
  echo "Validation failed; restoring previous config." >&2
  cp "$BACKUP_DIR/openclaw.json.$stamp" "$CONFIG"
  exit 3
fi

openclaw gateway restart
sleep 10

# Verify the route and channel. These are read-only checks.
echo
echo "=== Model route ==="
openclaw models status || true

echo
echo "=== Fallback chain ==="
openclaw models fallbacks list || true

echo
echo "=== WhatsApp transport ==="
openclaw channels status --probe || true

echo
echo "AUTONOMOUS_MODEL_ROTATION_CONFIGURED"
echo "Primary: $PRIMARY_MODEL"
echo "Fallbacks:"
echo "  - $NVIDIA_SUPER"
echo "  - $NVIDIA_NANO"
echo "  - $NVIDIA_FLASH"
echo "  - $OPENAI_FALLBACK"
echo "NVIDIA key persisted locally in $ENV_FILE (value not displayed)."
