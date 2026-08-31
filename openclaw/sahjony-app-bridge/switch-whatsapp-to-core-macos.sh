#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_BIN="${OPENCLAW_BIN:-$HOME/.openclaw/bin/openclaw}"
EXT_DIR="$HOME/.openclaw/extensions/whatsapp"
BACKUP_ROOT="$HOME/.openclaw/plugin-backups"
STAMP="$(date +%Y%m%d%H%M%S)"
BACKUP_DIR="$BACKUP_ROOT/whatsapp-clawhub-$STAMP"

if [[ ! -x "$OPENCLAW_BIN" ]]; then
  echo "ERROR: OpenClaw binary not executable: $OPENCLAW_BIN" >&2
  exit 2
fi

CORE_VERSION="$($OPENCLAW_BIN --version | awk '{print $2}' | head -1)"
if [[ -z "$CORE_VERSION" ]]; then
  echo "ERROR: could not determine OpenClaw core version" >&2
  exit 2
fi

echo "OpenClaw core version: $CORE_VERSION"
mkdir -p "$BACKUP_ROOT"

CONFIG_BACKUP="$HOME/.openclaw/openclaw.json.pre-whatsapp-core-switch.$STAMP"
cp "$HOME/.openclaw/openclaw.json" "$CONFIG_BACKUP"
echo "Config backup: $CONFIG_BACKUP"

moved=0
rollback() {
  set +e
  if [[ "$moved" == "1" && -d "$BACKUP_DIR" ]]; then
    rm -rf "$EXT_DIR"
    mv "$BACKUP_DIR" "$EXT_DIR"
  fi
  cp "$CONFIG_BACKUP" "$HOME/.openclaw/openclaw.json" 2>/dev/null || true
  "$OPENCLAW_BIN" gateway restart >/dev/null 2>&1 || true
  echo "ROLLBACK_COMPLETE"
}
trap 'echo "ERROR: switch failed; restoring external WhatsApp plugin" >&2; rollback' ERR

if [[ -d "$EXT_DIR" ]]; then
  mv "$EXT_DIR" "$BACKUP_DIR"
  moved=1
  echo "External WhatsApp plugin moved to: $BACKUP_DIR"
else
  echo "No external WhatsApp extension directory found; probing core plugin directly."
fi

"$OPENCLAW_BIN" gateway restart
sleep 12

INSPECT_JSON="$(mktemp)"
if ! "$OPENCLAW_BIN" plugins inspect whatsapp --runtime --json >"$INSPECT_JSON" 2>/tmp/sahjony-whatsapp-core-switch.err; then
  echo "Core WhatsApp inspect failed:" >&2
  cat /tmp/sahjony-whatsapp-core-switch.err >&2 || true
  false
fi

python3 - "$INSPECT_JSON" "$CORE_VERSION" <<'PY'
import json, sys
p, expected = sys.argv[1:]
data = json.load(open(p))
plugin = data.get("plugin") or {}
status = str(plugin.get("status") or "")
version = str(plugin.get("packageVersion") or plugin.get("version") or "")
source = str(plugin.get("source") or "")
origin = str(plugin.get("origin") or "")
print(json.dumps({"status": status, "version": version, "source": source, "origin": origin}, indent=2))
if status != "loaded":
    raise SystemExit("WhatsApp core plugin is not loaded")
if version != expected:
    raise SystemExit(f"WhatsApp version {version!r} does not match core {expected!r}")
if "/.openclaw/extensions/whatsapp/" in source:
    raise SystemExit("External WhatsApp extension is still shadowing core plugin")
PY

rm -f "$INSPECT_JSON"

STATUS_OUT="$($OPENCLAW_BIN channels status --probe 2>&1 || true)"
echo "$STATUS_OUT"
if ! printf '%s\n' "$STATUS_OUT" | grep -Eiq 'WhatsApp .*connected.*health:healthy'; then
  echo "ERROR: core WhatsApp plugin loaded but channel did not become connected/healthy" >&2
  false
fi

trap - ERR

echo "SWITCH_OK"
echo "Using WhatsApp plugin matching OpenClaw core $CORE_VERSION."
if [[ "$moved" == "1" ]]; then
  echo "Rollback backup retained at: $BACKUP_DIR"
fi
