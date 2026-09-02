#!/usr/bin/env bash
set -euo pipefail
# Registered final-repair trigger: 2026-09-02T19:07Z

STATE="${OPENCLAW_STATE_DIR:-/var/lib/sahjony-openclaw-state}"
CONFIG="${OPENCLAW_CONFIG_PATH:-$STATE/openclaw.json}"
KEY_FILE="${NVIDIA_KEY_FILE:-/root/sofia-gptoss-nvidia-key}"
TARGET_NVIDIA_MODEL="openai/gpt-oss-120b"
TARGET_OPENCLAW_MODEL="nvidia/openai/gpt-oss-120b"
BACKUP="$STATE/openclaw.json.pre-gpt-oss-120b.$(date -u +%Y%m%dT%H%M%SZ)"
SMOKE="/tmp/sofia-gptoss-smoke.json"
MUTATED=0

cleanup() { rm -f "$KEY_FILE" "$SMOKE"; }
rollback() {
  rc=$?
  set +e
  if [[ "$MUTATED" == 1 && -s "$BACKUP" ]]; then
    cp -f "$BACKUP" "$CONFIG"
    systemctl restart openclaw-gateway.service >/dev/null 2>&1 || true
    echo SOFIA_GPT_OSS_ROLLBACK=1 >&2
  fi
  cleanup
  exit "$rc"
}
trap rollback ERR INT TERM
trap cleanup EXIT

[[ -s "$CONFIG" ]] || { echo OPENCLAW_CONFIG_MISSING=1 >&2; exit 20; }
[[ -s "$KEY_FILE" ]] || { echo NVIDIA_KEY_TRANSFER_MISSING=1 >&2; exit 21; }
command -v openclaw >/dev/null 2>&1 || { echo OPENCLAW_CLI_MISSING=1 >&2; exit 22; }
command -v curl >/dev/null 2>&1 || { echo CURL_MISSING=1 >&2; exit 23; }
systemctl is-active --quiet openclaw-gateway.service || { echo OPENCLAW_GATEWAY_INACTIVE=1 >&2; exit 24; }

oc() {
  env HOME=/home/node OPENCLAW_HOME=/home/node OPENCLAW_STATE_DIR="$STATE" OPENCLAW_CONFIG_PATH="$CONFIG" openclaw "$@"
}

cp -a "$CONFIG" "$BACKUP"
chmod 600 "$BACKUP"
oc plugins enable nvidia >/dev/null 2>&1 || true
cat "$KEY_FILE" | oc models auth paste-api-key --provider nvidia --profile-id nvidia:nim >/dev/null
oc models auth order set --provider nvidia nvidia:nim >/dev/null
oc config set models.providers.nvidia '{"baseUrl":"https://integrate.api.nvidia.com/v1","api":"openai-completions"}' --strict-json --merge >/dev/null
oc config validate >/dev/null

nkey="$(tr -d '\r\n' <"$KEY_FILE")"
http_code="$(curl -sS -o "$SMOKE" -w '%{http_code}' --connect-timeout 10 --max-time 150 \
  -H "Authorization: Bearer $nkey" -H 'Content-Type: application/json' \
  -d "{\"model\":\"$TARGET_NVIDIA_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply exactly SOFIA_GPT_OSS_OK\"}],\"max_tokens\":128,\"temperature\":1,\"top_p\":1}" \
  https://integrate.api.nvidia.com/v1/chat/completions || true)"
[[ "$http_code" == 200 ]] || { echo "NVIDIA_GPT_OSS_SMOKE_HTTP=$http_code" >&2; exit 25; }
python3 -c 'import json,sys; obj=json.load(open(sys.argv[1], encoding="utf-8")); assert obj.get("choices"), "NVIDIA_GPT_OSS_SMOKE_NO_CHOICES"' "$SMOKE"

before="$(oc config get agents.defaults.model.primary 2>/dev/null || true)"
MUTATED=1
oc config set agents.defaults.model.primary "$TARGET_OPENCLAW_MODEL" >/dev/null
oc config validate >/dev/null
configured="$(oc config get agents.defaults.model.primary 2>/dev/null || true)"
[[ "$configured" == "$TARGET_OPENCLAW_MODEL" ]] || { echo "SOFIA_MODEL_CONFIG_MISMATCH=$configured" >&2; exit 26; }
systemctl restart openclaw-gateway.service
sleep 12
systemctl is-active --quiet openclaw-gateway.service || { echo OPENCLAW_GATEWAY_RESTART_FAILED=1 >&2; exit 27; }
configured_after="$(oc config get agents.defaults.model.primary 2>/dev/null || true)"
[[ "$configured_after" == "$TARGET_OPENCLAW_MODEL" ]] || { echo "SOFIA_MODEL_POST_RESTART_MISMATCH=$configured_after" >&2; exit 28; }

wa=''
for attempt in 1 2 3 4 5 6 7 8; do
  wa="$(curl -fsS --connect-timeout 10 --max-time 30 https://www.sahjony.com/whatsapp/health 2>/dev/null || true)"
  if HEALTH="$wa" python3 -c 'import json,os,sys; h=json.loads(os.environ.get("HEALTH") or "{}"); n=h.get("hostinger_openclaw") or {}; ok=(h.get("status")=="ok" and h.get("send_ready") is True and h.get("webhook_ready") is True and n.get("gateway_id")=="hostinger-vps" and n.get("connected") is True and n.get("heartbeat_fresh") is True); sys.exit(0 if ok else 1)'; then break; fi
  sleep 10
done
HEALTH="$wa" python3 -c 'import json,os; h=json.loads(os.environ.get("HEALTH") or "{}"); n=h.get("hostinger_openclaw") or {}; assert h.get("status")=="ok"; assert h.get("send_ready") is True; assert h.get("webhook_ready") is True; assert n.get("gateway_id")=="hostinger-vps"; assert n.get("connected") is True; assert n.get("heartbeat_fresh") is True'

MUTATED=0
trap - ERR INT TERM
echo "SOFIA_MODEL_BEFORE=$before"
echo SOFIA_PRIMARY_PROVIDER=NVIDIA
echo "SOFIA_PRIMARY_MODEL=$configured_after"
echo "NVIDIA_MODEL_ID=$TARGET_NVIDIA_MODEL"
echo OPENCLAW_GATEWAY_ACTIVE=1
echo WHATSAPP_CONNECTED=1
echo WHATSAPP_SEND_READY=1
echo WHATSAPP_WEBHOOK_READY=1
echo SOFIA_GPT_OSS_120B_CUTOVER=SUCCESS
