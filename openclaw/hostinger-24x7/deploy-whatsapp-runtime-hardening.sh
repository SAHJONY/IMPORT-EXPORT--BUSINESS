#!/usr/bin/env bash
set -euo pipefail

STATE=/var/lib/sahjony-openclaw-state
CONFIG="$STATE/openclaw.json"
ARCHIVE=/root/whatsapp-hardening.tgz
ROTATION=/root/nvidia-nim-rotation.sh
NVIDIA_KEY=/root/nvidia-key
TMP=/tmp/sahjony-whatsapp-hardening
TARGET_MODEL=nvidia/openai/gpt-oss-120b
TARGET_DM_SCOPE=per-account-channel-peer
START_EPOCH="$(date -u +%s)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$STATE/openclaw.json.pre-whatsapp-hardening.$STAMP"
SIDECAR_BACKUP=/usr/local/sbin/sahjony-openclaw-health-sidecar.pre-hardening
ROTATION_BACKUP=/usr/local/sbin/sahjony-nvidia-nim-rotation.pre-hardening
PLUGIN_BACKUP="$STATE/.whatsapp-hardening-plugin-backup.$STAMP"

cleanup(){
  rm -rf "$TMP" "$ARCHIVE" "$ROTATION" "$NVIDIA_KEY" /root/deploy-whatsapp-runtime-hardening.sh "$PLUGIN_BACKUP"
}

restore_runtime(){
  set +e
  if [[ -s "$BACKUP" ]]; then
    cp -f "$BACKUP" "$CONFIG"
  fi
  if [[ -s "$SIDECAR_BACKUP" ]]; then
    cp -f "$SIDECAR_BACKUP" /usr/local/sbin/sahjony-openclaw-health-sidecar
    chmod 755 /usr/local/sbin/sahjony-openclaw-health-sidecar
  fi
  if [[ -s "$ROTATION_BACKUP" ]]; then
    cp -f "$ROTATION_BACKUP" /usr/local/sbin/sahjony-nvidia-nim-rotation
    chmod 700 /usr/local/sbin/sahjony-nvidia-nim-rotation
  fi
  for plugin in sahjony-whatsapp-output-guard sahjony-whatsapp-reply-rescue sahjony-app-bridge; do
    dst="$STATE/extensions/$plugin"
    rm -rf "$dst"
    if [[ -d "$PLUGIN_BACKUP/$plugin" ]]; then
      cp -a "$PLUGIN_BACKUP/$plugin" "$dst"
    fi
  done
  systemctl daemon-reload || true
  systemctl restart openclaw-gateway.service >/dev/null 2>&1 || true
  systemctl start sahjony-openclaw-health-sidecar.service >/dev/null 2>&1 || true
  echo WHATSAPP_HARDENING_ROLLBACK=1 >&2
}

on_exit(){
  rc=$?
  trap - EXIT
  if [[ "$rc" -ne 0 ]]; then
    restore_runtime
  fi
  cleanup
  exit "$rc"
}
trap on_exit EXIT
trap 'exit 130' INT TERM

[[ -s "$CONFIG" ]] || { echo OPENCLAW_CONFIG_MISSING=1 >&2; exit 20; }
[[ -s "$ARCHIVE" ]] || { echo HARDENING_ARCHIVE_MISSING=1 >&2; exit 21; }
[[ -s "$ROTATION" ]] || { echo NVIDIA_ROTATION_ASSET_MISSING=1 >&2; exit 22; }
[[ -s "$NVIDIA_KEY" ]] || { echo NVIDIA_KEY_MISSING=1 >&2; exit 23; }
command -v openclaw >/dev/null 2>&1 || { echo OPENCLAW_CLI_MISSING=1 >&2; exit 24; }
systemctl is-active --quiet openclaw-gateway.service || { echo OPENCLAW_GATEWAY_INACTIVE=1 >&2; exit 25; }

oc(){ env HOME=/home/node OPENCLAW_HOME=/home/node OPENCLAW_STATE_DIR="$STATE" OPENCLAW_CONFIG_PATH="$CONFIG" openclaw "$@"; }

cp -a "$CONFIG" "$BACKUP"
chmod 600 "$BACKUP"
[[ ! -e /usr/local/sbin/sahjony-openclaw-health-sidecar ]] || cp -a /usr/local/sbin/sahjony-openclaw-health-sidecar "$SIDECAR_BACKUP"
[[ ! -e /usr/local/sbin/sahjony-nvidia-nim-rotation ]] || cp -a /usr/local/sbin/sahjony-nvidia-nim-rotation "$ROTATION_BACKUP"
install -d -m 700 "$PLUGIN_BACKUP"
for plugin in sahjony-whatsapp-output-guard sahjony-whatsapp-reply-rescue sahjony-app-bridge; do
  dst="$STATE/extensions/$plugin"
  if [[ -d "$dst" ]]; then
    cp -a "$dst" "$PLUGIN_BACKUP/$plugin"
  fi
done

rm -rf "$TMP"
mkdir -p "$TMP"
tar -xzf "$ARCHIVE" -C "$TMP"

for plugin in sahjony-whatsapp-output-guard sahjony-whatsapp-reply-rescue sahjony-app-bridge; do
  src="$TMP/openclaw/$plugin"
  dst="$STATE/extensions/$plugin"
  [[ -s "$src/index.js" ]] || { echo "PLUGIN_ASSET_MISSING=$plugin" >&2; exit 26; }
  rm -rf "$dst"
  install -d -m 755 "$STATE/extensions"
  cp -a "$src" "$dst"
  chown -R 0:0 "$dst"
  find "$dst" -type d -exec chmod 755 {} +
  find "$dst" -type f -exec chmod 644 {} +
done

[[ -s "$TMP/openclaw/sahjony-app-bridge/health-sidecar.py" ]] || { echo HEALTH_SIDECAR_ASSET_MISSING=1 >&2; exit 27; }
install -m 755 "$TMP/openclaw/sahjony-app-bridge/health-sidecar.py" /usr/local/sbin/sahjony-openclaw-health-sidecar
install -m 700 "$ROTATION" /usr/local/sbin/sahjony-nvidia-nim-rotation

umask 077
{ printf 'NVIDIA_API_KEY='; tr -d '\r\n' < "$NVIDIA_KEY"; printf '\n'; } > /etc/openclaw-nvidia.env
chmod 600 /etc/openclaw-nvidia.env
install -d -m 755 /etc/systemd/system/openclaw-gateway.service.d
printf '[Service]\nEnvironmentFile=/etc/openclaw-nvidia.env\n' > /etc/systemd/system/openclaw-gateway.service.d/30-nvidia-auth.conf

CONFIG="$CONFIG" TARGET_DM_SCOPE="$TARGET_DM_SCOPE" python3 - <<'PY'
import json, os
path=os.environ['CONFIG']
with open(path, encoding='utf-8') as f:
    data=json.load(f)
plugins=data.setdefault('plugins', {})
allow=plugins.setdefault('allow', [])
for name in ['sahjony-whatsapp-output-guard','sahjony-whatsapp-reply-rescue','sahjony-app-bridge']:
    if name not in allow:
        allow.append(name)
plugins['allow']=allow
entries=plugins.setdefault('entries', {})
entries.setdefault('sahjony-whatsapp-output-guard', {})['enabled']=True
rescue=entries.setdefault('sahjony-whatsapp-reply-rescue', {})
rescue['enabled']=True
cfg=rescue.setdefault('config', {})
cfg.setdefault('accountId','default')
cfg.setdefault('businessNumber','+12816628581')
# Runtime-error hooks rescue immediately. Silence fallback waits long enough for
# GPT-OSS 120B to finish a legitimate turn and therefore avoids duplicate replies.
cfg['rescueDelayMs']=40000
bridge=entries.setdefault('sahjony-app-bridge', {})
bridge['enabled']=True
bcfg=bridge.setdefault('config', {})
bcfg.setdefault('appUrl','https://www.sahjony.com')
bcfg.setdefault('accountId','default')
bcfg.setdefault('gatewayId','hostinger-vps')
bcfg.setdefault('businessNumber','+12816628581')
bcfg.setdefault('businessName','SAHJONY LLC')
bcfg.setdefault('pollIntervalMs',30000)
session=data.setdefault('session', {})
session['dmScope']=os.environ['TARGET_DM_SCOPE']
with open(path,'w',encoding='utf-8') as f:
    json.dump(data,f,indent=2)
    f.write('\n')
PY

oc config validate >/dev/null
current="$(oc config get agents.defaults.model.primary 2>/dev/null || true)"
[[ "$current" == "$TARGET_MODEL" ]] || { echo "SOFIA_PRIMARY_MODEL_UNEXPECTED=$current" >&2; exit 28; }
scope="$(oc config get session.dmScope 2>/dev/null || true)"
[[ "$scope" == "$TARGET_DM_SCOPE" ]] || { echo "WHATSAPP_DM_SCOPE_MISMATCH=$scope" >&2; exit 29; }
rescue_delay="$(oc config get plugins.entries.sahjony-whatsapp-reply-rescue.config.rescueDelayMs 2>/dev/null || true)"
[[ "$rescue_delay" == "40000" ]] || { echo "WHATSAPP_RESCUE_DELAY_MISMATCH=$rescue_delay" >&2; exit 30; }

grep -Fq 'Something went wrong while processing your request' "$STATE/extensions/sahjony-whatsapp-output-guard/index.js"
grep -Fq 'RESCUE_VERSION = "2.0.0"' "$STATE/extensions/sahjony-whatsapp-reply-rescue/index.js"
grep -Fq 'Never surface reasoning_content' "$STATE/extensions/sahjony-whatsapp-reply-rescue/index.js"
grep -Fq 'openai/gpt-oss-120b' "$STATE/extensions/sahjony-whatsapp-reply-rescue/index.js"
grep -Fq 'canonicalConfigPath' "$STATE/extensions/sahjony-app-bridge/index.js"
grep -Fq 'canonical_openclaw_config' /usr/local/sbin/sahjony-openclaw-health-sidecar
grep -Fq 'moonshotai/kimi-k2.6' /usr/local/sbin/sahjony-nvidia-nim-rotation && { echo INVALID_KIMI_FALLBACK_STILL_IN_ROTATION=1 >&2; exit 31; } || true

/usr/local/sbin/sahjony-nvidia-nim-rotation >/tmp/sahjony-nvidia-rotation-hardening.log 2>&1
fallback_json="$(oc config get agents.defaults.model.fallbacks --json 2>/dev/null || echo '[]')"
FALLBACK_JSON="$fallback_json" python3 - <<'PY'
import json, os
v=json.loads(os.environ.get('FALLBACK_JSON') or '[]')
assert isinstance(v,list), 'FALLBACKS_NOT_LIST'
text='\n'.join(map(str,v))
assert 'moonshotai/kimi-k2.6' not in text, 'INVALID_KIMI_FALLBACK_PRESENT'
assert len(v) >= 1, 'NO_NVIDIA_FALLBACKS'
allowed=(
 'nvidia/nemotron-3.5-lightning-30b-a3b',
 'nvidia/nemotron-3-super-120b-a12b',
 'nvidia/nemotron-3-ultra-550b-a55b',
)
assert all(x in allowed for x in v), f'UNVALIDATED_FALLBACK_PRESENT={v}'
PY

systemctl daemon-reload
systemctl restart openclaw-gateway.service
sleep 12
systemctl is-active --quiet openclaw-gateway.service || { echo OPENCLAW_GATEWAY_RESTART_FAILED=1 >&2; exit 32; }

pid="$(systemctl show openclaw-gateway.service -p MainPID --value)"
[[ "$pid" =~ ^[1-9][0-9]*$ ]] || { echo OPENCLAW_MAINPID_INVALID=1 >&2; exit 33; }
tr '\0' '\n' < "/proc/$pid/environ" | grep -q '^NVIDIA_API_KEY=' || { echo NVIDIA_KEY_NOT_BOUND_TO_GATEWAY=1 >&2; exit 34; }

after="$(oc config get agents.defaults.model.primary 2>/dev/null || true)"
[[ "$after" == "$TARGET_MODEL" ]] || { echo "SOFIA_PRIMARY_MODEL_POST_RESTART=$after" >&2; exit 35; }
scope_after="$(oc config get session.dmScope 2>/dev/null || true)"
[[ "$scope_after" == "$TARGET_DM_SCOPE" ]] || { echo "WHATSAPP_DM_SCOPE_POST_RESTART=$scope_after" >&2; exit 36; }
rescue_delay_after="$(oc config get plugins.entries.sahjony-whatsapp-reply-rescue.config.rescueDelayMs 2>/dev/null || true)"
[[ "$rescue_delay_after" == "40000" ]] || { echo "WHATSAPP_RESCUE_DELAY_POST_RESTART=$rescue_delay_after" >&2; exit 37; }

# Do not use an external `openclaw channels status --probe` here: this runtime
# protects gateway RPC with credentials held by the systemd process. The public
# signed heartbeat is the authority-neutral verification surface and must be
# newer than this deployment before we accept success.
systemctl start sahjony-openclaw-health-sidecar.service >/dev/null 2>&1 || true

health=''
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
  health="$(curl -fsS --connect-timeout 10 --max-time 30 https://www.sahjony.com/whatsapp/health 2>/dev/null || true)"
  if HEALTH="$health" TARGET="$TARGET_MODEL" START_EPOCH="$START_EPOCH" python3 - <<'PY'
import datetime, json, os
try:
    h=json.loads(os.environ.get('HEALTH') or '{}')
    n=h.get('hostinger_openclaw') or {}
    raw=n.get('last_seen_at') or ''
    seen=datetime.datetime.fromisoformat(raw.replace('Z','+00:00')).timestamp()
    start=float(os.environ['START_EPOCH'])
except Exception:
    raise SystemExit(1)
ok=(
    h.get('status')=='ok' and
    h.get('send_ready') is True and
    h.get('webhook_ready') is True and
    n.get('connected') is True and
    n.get('heartbeat_fresh') is True and
    n.get('gateway_id')=='hostinger-vps' and
    n.get('model')==os.environ['TARGET'] and
    seen >= start - 5
)
raise SystemExit(0 if ok else 1)
PY
  then
    break
  fi
  systemctl start sahjony-openclaw-health-sidecar.service >/dev/null 2>&1 || true
  sleep 8
done

HEALTH="$health" TARGET="$TARGET_MODEL" START_EPOCH="$START_EPOCH" python3 - <<'PY'
import datetime, json, os
h=json.loads(os.environ.get('HEALTH') or '{}')
n=h.get('hostinger_openclaw') or {}
raw=n.get('last_seen_at') or ''
seen=datetime.datetime.fromisoformat(raw.replace('Z','+00:00')).timestamp()
start=float(os.environ['START_EPOCH'])
assert h.get('status')=='ok', 'WHATSAPP_HEALTH_NOT_OK'
assert h.get('send_ready') is True, 'WHATSAPP_SEND_NOT_READY'
assert h.get('webhook_ready') is True, 'WHATSAPP_WEBHOOK_NOT_READY'
assert n.get('connected') is True, 'HOSTINGER_OPENCLAW_NOT_CONNECTED'
assert n.get('heartbeat_fresh') is True, 'HOSTINGER_HEARTBEAT_STALE'
assert n.get('gateway_id')=='hostinger-vps', 'WRONG_WHATSAPP_AUTHORITY'
assert n.get('model')==os.environ['TARGET'], f"HEARTBEAT_MODEL_MISMATCH={n.get('model')}"
assert seen >= start - 5, f"POST_RESTART_HEARTBEAT_NOT_OBSERVED={raw}"
PY

rm -f "$SIDECAR_BACKUP" "$ROTATION_BACKUP"

echo SOFIA_PRIMARY_PROVIDER=NVIDIA
echo "SOFIA_PRIMARY_MODEL=$after"
echo "WHATSAPP_DM_SCOPE=$scope_after"
echo "WHATSAPP_RESCUE_DELAY_MS=$rescue_delay_after"
echo WHATSAPP_SESSION_COLLISION_GUARD=ACTIVE
echo NVIDIA_INVALID_FALLBACKS_REMOVED=1
echo WHATSAPP_OUTPUT_GUARD_RUNTIME_ERROR_SUPPRESSION=ACTIVE
echo WHATSAPP_REPLY_RESCUE_CONTEXTUAL_V2=ACTIVE
echo WHATSAPP_REPLY_RESCUE_REASONING_OUTPUT_BLOCKED=1
echo WHATSAPP_POST_RESTART_HEARTBEAT=VERIFIED
echo WHATSAPP_HEALTH_SIDECAR_CANONICAL_MODEL=ACTIVE
echo OPENCLAW_GATEWAY_ACTIVE=1
echo WHATSAPP_CONNECTED=1
echo WHATSAPP_SEND_READY=1
echo WHATSAPP_WEBHOOK_READY=1
echo WHATSAPP_RUNTIME_HARDENING=SUCCESS
