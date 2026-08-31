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
cp "$CONFIG" "$BACKUP_DIR/openclaw.json.$stamp"

echo "Repairing messaging tool policy and reply-rescue configuration..."
python3 - "$CONFIG" <<'PY'
import json, sys
from pathlib import Path
p=Path(sys.argv[1])
d=json.loads(p.read_text())
required=["exec","process","read","write","edit"]

def merge_tools(tools):
    if not isinstance(tools, dict):
        return
    if tools.get("profile") == "messaging" or "exec" in tools or "fs" in tools:
        current=tools.get("alsoAllow") or []
        if not isinstance(current, list): current=[]
        for name in required:
            if name not in current: current.append(name)
        tools["alsoAllow"]=current

agents=d.setdefault("agents",{})
defaults=agents.setdefault("defaults",{})
tools=defaults.setdefault("tools",{})
merge_tools(tools)
# If profile is inherited elsewhere, explicit defaults keep the current profile intact.
current=tools.get("alsoAllow") or []
for name in required:
    if name not in current: current.append(name)
tools["alsoAllow"]=current

# Repair per-agent tool policies without assuming one particular schema shape.
def walk(node, path=()):
    if isinstance(node, dict):
        if "tools" in node and isinstance(node["tools"], dict):
            merge_tools(node["tools"])
        for k,v in node.items():
            walk(v, path+(str(k),))
    elif isinstance(node, list):
        for i,v in enumerate(node): walk(v, path+(str(i),))
walk(agents)

plugins=d.setdefault("plugins",{})
entries=plugins.setdefault("entries",{})
rescue=entries.setdefault("sahjony-whatsapp-reply-rescue",{})
rescue["enabled"]=True
rescue["config"]={
    "accountId":"default",
    "businessNumber":"+12816628581",
    "rescueDelayMs":15000
}
hooks=rescue.setdefault("hooks",{})
hooks["allowConversationAccess"]=True

allow=plugins.get("allow") or []
if not isinstance(allow, list): allow=[]
for pid in ["whatsapp","sahjony-app-bridge","sahjony-agent-diagnostics","sahjony-whatsapp-reply-rescue"]:
    if pid not in allow: allow.append(pid)
plugins["allow"]=allow

p.write_text(json.dumps(d, indent=2)+"\n")
print("tools.alsoAllow:", tools.get("alsoAllow"))
print("reply rescue enabled: true")
print("plugins.allow:", plugins.get("allow"))
PY

if ! openclaw config validate; then
  echo "Config validation failed; restoring backup." >&2
  cp "$BACKUP_DIR/openclaw.json.$stamp" "$CONFIG"
  exit 2
fi

openclaw plugins install "$PLUGIN_DIR" \
  --force \
  --acknowledge-install-policy-warning
openclaw plugins enable sahjony-whatsapp-reply-rescue

# Re-apply capability flag because local plugin installation can refresh its entry.
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

openclaw config validate
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
