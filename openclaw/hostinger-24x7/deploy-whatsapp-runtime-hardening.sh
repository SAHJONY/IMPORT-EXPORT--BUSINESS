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
BACKUP="$STATE/openclaw.json.pre-whatsapp-hardening.$(date -u +%Y%m%dT%H%M%SZ)"
SIDECAR_BACKUP=/usr/local/sbin/sahjony-openclaw-health-sidecar.pre-hardening
ROTATION_BACKUP=/usr/local/sbin/sahjony-nvidia-nim-rotation.pre-hardening

cleanup(){ rm -rf "$TMP" "$ARCHIVE" "$ROTATION" "$NVIDIA_KEY" /root/deploy-whatsapp-runtime-hardening.sh; }
rollback(){
  rc=$?
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
  systemctl daemon-reload || true
  systemctl restart openclaw-gateway.service >/dev/null 2>&1 || true
  systemctl start sahjony-openclaw-health-sidecar.service >/dev/null 2>&1 || true
  echo WHATSAPP_HARDENING_ROLLBACK=1 >&2
  cleanup
  exit "$rc"
}
trap rollback ERR INT TERM
trap cleanup EXIT

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
entries=plugins.setdefault('entries', {})
entries.setdefault('sahjony-whatsapp-output-guard', {})['enabled']=True
rescue=entries.setdefault('sahjony-whatsapp-reply-rescue', {})
rescue['enabled']=True
cfg=rescue.setdefault('config', {})
cfg.setdefault('accountId','default')
cfg.setdefault('businessNumber','+12816628581')
cfg['rescueDelayMs']=12000
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

grep -Fq 'Something went wrong while processing your request' "$STATE/extensions/sahjony-whatsapp-output-guard/index.js"
grep -Fq 'openai/gpt-oss-120b' "$STATE/extensions/sahjony-whatsapp-reply-rescue/index.js"
grep -Fq 'canonicalConfigPath' "$STATE/extensions/sahjony-app-bridge/index.js"
grep -Fq 'canonical_openclaw_config' /usr/local/sbin/sahjony-openclaw-health-sidecar
grep -Fq 'moonshotai/kimi-k2.6' /usr/local/sbin/sahjony-nvidia-nim-rotation && { echo INVALID_KIMI_FALLBACK_STILL_IN_ROTATION=1 >&2; exit 30; } || true

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
systemctl is-active --quiet openclaw-gateway.service || { echo OPENCLAW_GATEWAY_RESTART_FAILED=1 >&2; exit 31; }

pid="$(systemctl show openclaw-gateway.service -p MainPID --value)"
[[ "$pid" =~ ^[1-9][0-9]*$ ]] || { echo OPENCLAW_MAINPID_INVALID=1 >&2; exit 32; }
tr '\0' '\n' < "/proc/$pid/environ" | grep -q '^NVIDIA_API_KEY=' || { echo NVIDIA_KEY_NOT_BOUND_TO_GATEWAY=1 >&2; exit 33; }

after="$(oc config get agents.defaults.model.primary 2>/dev/null || true)"
[[ "$after" == "$TARGET_MODEL" ]] || { echo "SOFIA_PRIMARY_MODEL_POST_RESTART=$after" >&2; exit 34; }
scope_after="$(oc config get session.dmScope 2>/dev/null || true)"
[[ "$scope_after" == "$TARGET_DM_SCOPE" ]] || { echo "WHATSAPP_DM_SCOPE_POST_RESTART=$scope_after" >&2; exit 35; }

systemctl start sahjony-openclaw-health-sidecar.service
for attempt in 1 2 3 4 5 6 7 8; do
  if ! systemctl is-active --quiet sahjony-openclaw-health-sidecar.service; then break; fi
  sleep 2
done

probe="$(oc channels status --channel whatsapp --probe 2>&1 || oc channels status --probe 2>&1 || true)"
printf '%s' "$probe" | grep -Eiq 'whatsapp.*(connected|linked.*running)' || { echo WHATSAPP_CHANNEL_PROBE_NOT_CONNECTED=1 >&2; printf '%s\n' "$probe" | tail -n 30 >&2; exit 36; }

health=''
for attempt in 1 2 3 4 5 6; do
  health="$(curl -fsS --connect-timeout 10 --max-time 30 https://www.sahjony.com/whatsapp/health 2>/dev/null || true)"
  if HEALTH="$health" TARGET="$TARGET_MODEL" python3 - <<'PY'
import json, os, sys
try: h=json.loads(os.environ.get('HEALTH') or '{}')
except Exception: raise SystemExit(1)
n=h.get('hostinger_openclaw') or {}
ok=(h.get('status')=='ok' and h.get('send_ready') is True and h.get('webhook_ready') is True and n.get('connected') is True and n.get('heartbeat_fresh') is True and n.get('gateway_id')=='hostinger-vps' and n.get('model')==os.environ['TARGET'])
raise SystemExit(0 if ok else 1)
PY
  then
    break
  fi
  systemctl start sahjony-openclaw-health-sidecar.service >/dev/null 2>&1 || true
  sleep 8
done

HEALTH="$health" TARGET="$TARGET_MODEL" python3 - <<'PY'
import json, os
h=json.loads(os.environ.get('HEALTH') or '{}')
n=h.get('hostinger_openclaw') or {}
assert h.get('status')=='ok', 'WHATSAPP_HEALTH_NOT_OK'
assert h.get('send_ready') is True, 'WHATSAPP_SEND_NOT_READY'
assert h.get('webhook_ready') is True, 'WHATSAPP_WEBHOOK_NOT_READY'
assert n.get('connected') is True, 'HOSTINGER_OPENCLAW_NOT_CONNECTED'
assert n.get('heartbeat_fresh') is True, 'HOSTINGER_HEARTBEAT_STALE'
assert n.get('gateway_id')=='hostinger-vps', 'WRONG_WHATSAPP_AUTHORITY'
assert n.get('model')==os.environ['TARGET'], f"HEARTBEAT_MODEL_MISMATCH={n.get('model')}"
PY

trap - ERR INT TERM
rm -f "$SIDECAR_BACKUP" "$ROTATION_BACKUP"

echo SOFIA_PRIMARY_PROVIDER=NVIDIA
echo "SOFIA_PRIMARY_MODEL=$after"
echo "WHATSAPP_DM_SCOPE=$scope_after"
echo WHATSAPP_SESSION_COLLISION_GUARD=ACTIVE
echo NVIDIA_INVALID_FALLBACKS_REMOVED=1
echo WHATSAPP_OUTPUT_GUARD_RUNTIME_ERROR_SUPPRESSION=ACTIVE
echo WHATSAPP_REPLY_RESCUE_GPT_OSS_120B=ACTIVE
echo WHATSAPP_HEALTH_SIDECAR_CANONICAL_MODEL=ACTIVE
echo OPENCLAW_GATEWAY_ACTIVE=1
echo WHATSAPP_CONNECTED=1
echo WHATSAPP_SEND_READY=1
echo WHATSAPP_WEBHOOK_READY=1
echo WHATSAPP_RUNTIME_HARDENING=SUCCESS
