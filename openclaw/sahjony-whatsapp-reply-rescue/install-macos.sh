#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/IMPORT-EXPORT--BUSINESS"
OPENCLAW_HOME="${HOME}/.openclaw"
CONFIG="${OPENCLAW_HOME}/openclaw.json"
BACKUP_DIR="${OPENCLAW_HOME}/backups/reply-rescue"
PLUGIN_DIR="${ROOT}/openclaw/sahjony-whatsapp-reply-rescue"

cd "$ROOT"
mkdir -p "$BACKUP_DIR"
stamp="$(date +%Y%m%d%H%M%S)"
backup="$BACKUP_DIR/openclaw.json.$stamp"
cp "$CONFIG" "$backup"

restore_config() {
  cp "$backup" "$CONFIG"
}

trap 'rc=$?; if [[ $rc -ne 0 ]]; then echo "Installer failed; restoring OpenClaw config backup." >&2; restore_config; fi; exit $rc' EXIT

echo "Repairing messaging tool policy and reply-rescue configuration..."
python3 - "$CONFIG" <<'PY'
import json, sys
from pathlib import Path
p=Path(sys.argv[1])
d=json.loads(p.read_text())
required=["exec","process","read","write","edit"]

# OpenClaw 2026.8.1 validates `tools` at the top level. Do not write
# agents.defaults.tools: that schema path is invalid in this release.
tools=d.setdefault("tools",{})
if not isinstance(tools, dict):
    raise SystemExit("top-level tools config is not an object")
current=tools.get("alsoAllow") or []
if not isinstance(current, list):
    current=[]
for name in required:
    if name not in current:
        current.append(name)
tools["alsoAllow"]=current

plugins=d.setdefault("plugins",{})
entries=plugins.setdefault("entries",{})
rescue=entries.setdefault("sahjony-whatsapp-reply-rescue",{})
rescue["enabled"]=True
rescue["config"]={
    "accountId":"default",
    "businessNumber":"+12816628581",
    "rescueDelayMs":15000
}
rescue.setdefault("hooks",{})["allowConversationAccess"]=True

allow=plugins.get("allow") or []
if not isinstance(allow, list):
    allow=[]
for pid in ["whatsapp","sahjony-app-bridge","sahjony-agent-diagnostics","sahjony-whatsapp-reply-rescue"]:
    if pid not in allow:
        allow.append(pid)
plugins["allow"]=allow

p.write_text(json.dumps(d, indent=2)+"\n")
print("top-level tools.alsoAllow:", tools.get("alsoAllow"))
print("reply rescue enabled: true")
print("plugins.allow:", plugins.get("allow"))
PY

if ! openclaw config validate; then
  echo "Config validation failed; restoring backup." >&2
  restore_config
  exit 2
fi

openclaw plugins install "$PLUGIN_DIR" \
  --force \
  --acknowledge-install-policy-warning
openclaw plugins enable sahjony-whatsapp-reply-rescue

# Local plugin installation may refresh the entry, so restore only the
# plugin-specific runtime settings and never touch agents.defaults.tools.
python3 - "$CONFIG" <<'PY'
import json, sys
from pathlib import Path
p=Path(sys.argv[1]); d=json.loads(p.read_text())
e=d.setdefault("plugins",{}).setdefault("entries",{}).setdefault("sahjony-whatsapp-reply-rescue",{})
e["enabled"]=True
e["config"]={"accountId":"default","businessNumber":"+12816628581","rescueDelayMs":15000}
e.setdefault("hooks",{})["allowConversationAccess"]=True
p.write_text(json.dumps(d, indent=2)+"\n")
PY

if ! openclaw config validate; then
  echo "Post-install config validation failed; restoring backup." >&2
  restore_config
  exit 3
fi

openclaw gateway restart
sleep 10

echo
echo "=== Reply rescue plugin ==="
openclaw plugins inspect sahjony-whatsapp-reply-rescue --runtime --json || true

echo
echo "=== WhatsApp ==="
openclaw channels status --probe

echo
echo "SAHJONY_WHATSAPP_REPLY_RESCUE_INSTALLED"
echo "Normal OpenClaw replies win. NVIDIA rescue activates only when no visible reply is queued within 15 seconds."

trap - EXIT
