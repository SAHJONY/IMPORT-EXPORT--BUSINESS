#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This repair is intended for the macOS OpenClaw gateway host." >&2
  exit 1
fi

for cmd in openclaw python3; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd" >&2; exit 1; }
done

echo "OpenClaw core: $(openclaw --version)"

echo "Updating WhatsApp plugin to the gateway-compatible release..."
openclaw plugins update whatsapp || {
  echo "Plugin update failed; reinstalling official WhatsApp plugin."
  openclaw plugins install clawhub:@openclaw/whatsapp --force
  openclaw plugins enable whatsapp --accept-capabilities
}

openclaw gateway restart
sleep 3
openclaw plugins inspect whatsapp --runtime --json || true
openclaw channels status --probe || true

DIST_DIR="$(find "$HOME/.openclaw/tools" -type d -path '*/lib/node_modules/openclaw/dist' -print 2>/dev/null | sort | tail -1)"
if [[ -z "$DIST_DIR" || ! -d "$DIST_DIR" ]]; then
  echo "Could not locate the isolated OpenClaw dist directory; plugin alignment completed, kernel workaround not applied." >&2
  exit 2
fi

echo "OpenClaw dist: $DIST_DIR"

PATCH_RESULT="$(python3 - "$DIST_DIR" <<'PY'
from __future__ import annotations
import pathlib
import re
import shutil
import sys
import time

dist = pathlib.Path(sys.argv[1])
files = sorted(dist.glob("kernel-*.js"))
if not files:
    print("NO_KERNEL")
    raise SystemExit(0)

needle = re.compile(
    r'''if\s*\(\s*!lifecycle\s*\)\s*throw\s+new\s+Error\(\s*["']runChannelInboundEvent prepared turns must declare runDispatchLifecycle when creating runDispatch["']\s*\)\s*;?'''
)
marker = "/* SAHJONY_OPENCLAW_DISPATCH_COMPAT */"
patched: list[str] = []
already: list[str] = []

for path in files:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        already.append(path.name)
        continue
    new_text, count = needle.subn(
        "if (!lifecycle) { /* SAHJONY_OPENCLAW_DISPATCH_COMPAT */ return; }",
        text,
        count=1,
    )
    if count:
        backup = path.with_suffix(path.suffix + f".backup.{int(time.time())}")
        shutil.copy2(path, backup)
        path.write_text(new_text, encoding="utf-8")
        patched.append(path.name)

if patched:
    print("PATCHED:" + ",".join(patched))
elif already:
    print("ALREADY_PATCHED:" + ",".join(already))
else:
    print("SIGNATURE_NOT_FOUND")
PY
)"

echo "$PATCH_RESULT"

case "$PATCH_RESULT" in
  PATCHED:*|ALREADY_PATCHED:*)
    echo "Restarting gateway with dispatch compatibility workaround."
    openclaw gateway restart
    sleep 3
    openclaw gateway status --deep --require-rpc || true
    openclaw channels status --probe || true
    ;;
  SIGNATURE_NOT_FOUND)
    echo "The exact upstream lifecycle assertion is not present in this build; no core files were modified."
    ;;
  NO_KERNEL)
    echo "No kernel bundle matched; plugin alignment completed but no core workaround was applied." >&2
    exit 2
    ;;
  *)
    echo "Kernel compatibility patch could not be verified." >&2
    exit 3
    ;;
esac

echo "Repair complete. Send one fresh WhatsApp DM from another number, then run:"
echo "  openclaw channels logs --channel whatsapp --lines 120"
