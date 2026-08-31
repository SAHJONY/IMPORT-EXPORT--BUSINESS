#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This repair is intended for the macOS OpenClaw gateway host." >&2
  exit 1
fi

for cmd in openclaw python3 find sort tail; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd" >&2; exit 1; }
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCHER="${SCRIPT_DIR}/patch-openclaw-dispatch.py"

if [[ ! -f "$PATCHER" ]]; then
  echo "Missing patch helper: $PATCHER" >&2
  exit 1
fi

echo "OpenClaw core: $(openclaw --version)"
echo "Updating WhatsApp plugin..."
openclaw plugins update whatsapp || true

openclaw gateway restart
sleep 3
openclaw plugins inspect whatsapp --runtime --json || true
openclaw channels status --probe || true

DIST_DIR="$(find "$HOME/.openclaw/tools" -type d -path '*/lib/node_modules/openclaw/dist' -print 2>/dev/null | sort | tail -1)"
if [[ -z "$DIST_DIR" || ! -d "$DIST_DIR" ]]; then
  echo "Could not locate the isolated OpenClaw dist directory." >&2
  exit 2
fi

echo "OpenClaw dist: $DIST_DIR"

set +e
PATCH_RESULT="$(python3 "$PATCHER" "$DIST_DIR")"
PATCH_STATUS=$?
set -e

echo "$PATCH_RESULT"

if [[ "$PATCH_RESULT" == PATCHED:* || "$PATCH_RESULT" == ALREADY_PATCHED:* ]]; then
  echo "Restarting gateway with dispatch compatibility workaround."
  openclaw gateway restart
  sleep 3
  openclaw gateway status --deep --require-rpc || true
  openclaw channels status --probe || true
elif [[ "$PATCH_RESULT" == "SIGNATURE_NOT_FOUND" ]]; then
  echo "The exact lifecycle assertion was not found. No OpenClaw core file was modified."
  exit 4
else
  echo "Patch helper failed with status $PATCH_STATUS: $PATCH_RESULT" >&2
  exit "$PATCH_STATUS"
fi

echo "Repair complete. Send one fresh WhatsApp DM from another number, then run:"
echo "openclaw channels logs --channel whatsapp --lines 120"
