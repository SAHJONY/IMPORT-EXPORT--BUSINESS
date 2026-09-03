#!/usr/bin/env bash
set -euo pipefail

API_BASE="${HOSTINGER_API_BASE:-https://developers.hostinger.com}"
VM_ID="${HOSTINGER_VM_ID:-}"
HOST="${HOSTINGER_HOST:-}"
USER_NAME="${HOSTINGER_USER:-root}"
TOKEN="${HOSTINGER_API_TOKEN:-}"
OPENAI_KEY="${OPENAI_API_KEY:-}"
KEY_DIR="${RUNNER_TEMP:-/tmp}/sahjony-provider-repair"
KEY_PATH="$KEY_DIR/provider-repair"
EPHEMERAL_KEY_ID=""
KEY_ATTACHED=false
SSH_READY=false

log(){ printf '[provider-repair] %s\n' "$*"; }
fail(){ log "FAIL: $*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || fail "missing command: $1"; }
api(){
  local method="$1" path="$2" data="${3:-}"
  local args=(-fsS -X "$method" -H "Authorization: Bearer $TOKEN" -H 'Accept: application/json')
  if [[ -n "$data" ]]; then args+=(-H 'Content-Type: application/json' --data "$data"); fi
  curl "${args[@]}" "$API_BASE$path"
}
ssh_base(){
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=8 -i "$KEY_PATH" "$USER_NAME@$HOST" "$@"
}

cleanup(){
  local rc=$? cleanup_failed=false
  trap - EXIT
  set +e

  if [[ "$KEY_ATTACHED" == true && -f "$KEY_PATH.pub" ]]; then
    local algo body algo_b64 body_b64
    algo="$(awk '{print $1}' "$KEY_PATH.pub")"
    body="$(awk '{print $2}' "$KEY_PATH.pub")"
    algo_b64="$(printf '%s' "$algo" | base64 -w0)"
    body_b64="$(printf '%s' "$body" | base64 -w0)"

    if [[ "$SSH_READY" == true ]]; then
      ssh_base "ALGO_B64='$algo_b64' BODY_B64='$body_b64' bash -s" <<'REMOTE'
set -euo pipefail
algo="$(printf '%s' "$ALGO_B64" | base64 -d)"
body="$(printf '%s' "$BODY_B64" | base64 -d)"
f=/root/.ssh/authorized_keys
if [[ -f "$f" ]]; then
  awk -v a="$algo" -v b="$body" '
    {
      drop=0
      for (i=1; i<NF; i++) if ($i==a && $(i+1)==b) { drop=1; break }
      if (!drop) print
    }
  ' "$f" > "$f.tmp"
  install -m 600 "$f.tmp" "$f"
  rm -f "$f.tmp"
  if awk -v a="$algo" -v b="$body" '{for(i=1;i<NF;i++) if($i==a && $(i+1)==b) found=1} END{exit found?0:1}' "$f"; then
    echo EPHEMERAL_KEY_STILL_PRESENT=1 >&2
    exit 31
  fi
fi
echo EPHEMERAL_KEY_REMOVED_FROM_VPS=1
REMOTE
      [[ $? -eq 0 ]] || cleanup_failed=true
    else
      log 'SECURITY_CLEANUP_UNVERIFIED: attach action succeeded but normal SSH was never established'
      cleanup_failed=true
    fi
  fi

  if [[ -n "$EPHEMERAL_KEY_ID" ]]; then
    api DELETE "/api/vps/v1/public-keys/$EPHEMERAL_KEY_ID" >/dev/null 2>&1 || cleanup_failed=true
  fi

  rm -rf "$KEY_DIR"
  if [[ "$cleanup_failed" == true ]]; then
    log 'SECURITY_CLEANUP_GATE=FAILED'
    exit 32
  fi
  log 'SECURITY_CLEANUP_GATE=PASS'
  exit "$rc"
}
trap cleanup EXIT

[[ -n "$VM_ID" ]] || fail 'HOSTINGER_VM_ID is required'
[[ -n "$HOST" ]] || fail 'HOSTINGER_HOST is required'
[[ -n "$TOKEN" ]] || fail 'HOSTINGER_API_TOKEN is required'
[[ -n "$OPENAI_KEY" ]] || fail 'OPENAI_API_KEY is required'
for c in curl jq ssh ssh-keygen awk base64 sed grep; do need "$c"; done

code="$(curl -sS -o /tmp/openai-preflight.json -w '%{http_code}' -H "Authorization: Bearer $OPENAI_KEY" https://api.openai.com/v1/models || true)"
log "OPENAI_PREFLIGHT_HTTP=$code"
[[ "$code" == 200 ]] || fail 'OpenAI preflight failed'
rm -f /tmp/openai-preflight.json

mkdir -p "$KEY_DIR"
chmod 700 "$KEY_DIR"
# RSA 3072 is intentional: account-level Hostinger key create/delete was proven
# against this API/account with this key type, while the previous ED25519 path failed.
ssh-keygen -q -t rsa -b 3072 -N '' -f "$KEY_PATH" -C "provider-repair-${GITHUB_RUN_ID:-manual}"
pub="$(cat "$KEY_PATH.pub")"
name="sahjony-provider-repair-${GITHUB_RUN_ID:-manual}-$(date +%s)"
create="$(api POST /api/vps/v1/public-keys "$(jq -n --arg name "$name" --arg key "$pub" '{name:$name,key:$key}')")"
EPHEMERAL_KEY_ID="$(jq -r '.id // empty' <<<"$create")"
[[ "$EPHEMERAL_KEY_ID" =~ ^[0-9]+$ ]] || fail 'Hostinger public key id missing'
log 'HOSTINGER_ACCOUNT_PUBLIC_KEY_CREATE=READY'

attach="$(api POST "/api/vps/v1/public-keys/attach/$VM_ID" "$(jq -n --argjson id "$EPHEMERAL_KEY_ID" '{ids:[$id]}')")"
action_id="$(jq -r '.id // empty' <<<"$attach")"
[[ "$action_id" =~ ^[0-9]+$ ]] || fail 'Hostinger SSH-key attach action id missing'

attach_ok=false
for i in $(seq 1 60); do
  action_body="$(api GET "/api/vps/v1/virtual-machines/$VM_ID/actions/$action_id")"
  state="$(jq -r '.state // empty' <<<"$action_body")"
  log "SSH_KEY_ATTACH probe=$i state=${state:-unknown}"
  case "$state" in
    success) attach_ok=true; break ;;
    failed|failure|error|cancelled|canceled) fail 'Hostinger SSH-key attach action failed' ;;
  esac
  sleep 5
done
[[ "$attach_ok" == true ]] || fail 'Hostinger SSH-key attach timed out'

# This Hostinger account returns VPS:2002 Route is not found for the documented
# VM-attached-public-keys GET route. Treat the successful attach action plus real
# SSH authentication as the authoritative materialization proof instead.
KEY_ATTACHED=true
log 'HOSTINGER_KEY_ATTACH_ACTION=SUCCESS'

for i in $(seq 1 36); do
  if ssh_base 'printf SAHJONY_NORMAL_SSH_OK' 2>/dev/null | grep -q SAHJONY_NORMAL_SSH_OK; then
    SSH_READY=true
    break
  fi
  sleep 5
done
[[ "$SSH_READY" == true ]] || fail 'normal SSH did not authenticate after Hostinger key attach'
log 'HOSTINGER_NORMAL_SSH=READY'

OPENAI_B64="$(printf '%s' "$OPENAI_KEY" | base64 -w0)"
ssh_base "OPENAI_B64='$OPENAI_B64' bash -s" <<'REMOTE'
set -euo pipefail
cd /opt/sahjony-openclaw
test -f docker-compose.yml
key="$(printf '%s' "$OPENAI_B64" | base64 -d)"
[[ -n "$key" ]]

touch .env
chmod 600 .env
cp -a .env ".env.backup.$(date -u +%Y%m%dT%H%M%SZ)"
tmp="$(mktemp)"
grep -vE '^(OPENAI_API_KEY|ANTHROPIC_API_KEY)=' .env > "$tmp" || true
printf 'OPENAI_API_KEY=%s\n' "$key" >> "$tmp"
install -m 600 "$tmp" .env
rm -f "$tmp"
! grep -q '^ANTHROPIC_API_KEY=' .env

docker compose up -d --force-recreate openclaw-gateway
cid="$(docker compose ps -q openclaw-gateway)"
[[ -n "$cid" ]]
docker update --restart unless-stopped "$cid" >/dev/null
test "$(docker inspect "$cid" --format '{{.State.Running}}')" = true

env_lines="$(docker inspect "$cid" --format '{{range .Config.Env}}{{println .}}{{end}}')"
env_names="$(printf '%s\n' "$env_lines" | cut -d= -f1)"
grep -qx OPENAI_API_KEY <<<"$env_names"
! grep -qx ANTHROPIC_API_KEY <<<"$env_names"
runtime_key="$(printf '%s\n' "$env_lines" | sed -n 's/^OPENAI_API_KEY=//p' | head -n1)"
[[ -n "$runtime_key" ]]

code="$(curl -sS -o /tmp/openai-runtime.json -w '%{http_code}' \
  -H "Authorization: Bearer $runtime_key" \
  -H 'Content-Type: application/json' \
  --data '{"model":"gpt-4.1-mini","input":"Reply with exactly SAHJONY_RUNTIME_OK","max_output_tokens":16}' \
  https://api.openai.com/v1/responses || true)"
unset runtime_key key OPENAI_B64 env_lines
echo "OPENAI_RUNTIME_INFERENCE_HTTP=$code"
[[ "$code" == 200 ]]
grep -q 'SAHJONY_RUNTIME_OK' /tmp/openai-runtime.json
rm -f /tmp/openai-runtime.json
echo OPENCLAW_PROVIDER_RUNTIME=READY
REMOTE

ready=false
for i in $(seq 1 24); do
  health_body="$(curl -fsS --max-time 20 https://www.sahjony.com/whatsapp/health || true)"
  printf '%s\n' "$health_body" | jq '{status,provider,send_ready,gateway_connected,heartbeat_fresh,recovery_issues,backlog_recovery}' 2>/dev/null || true
  if jq -e '(.provider == "hostinger_openclaw") and ((.gateway_connected // false) == true) and ((.heartbeat_fresh // false) == true) and ((.send_ready // false) == true)' >/dev/null 2>&1 <<<"$health_body"; then
    ready=true
    break
  fi
  sleep 5
done
[[ "$ready" == true ]] || fail 'WhatsApp transaction readiness gate failed'
log 'WHATSAPP_TRANSACTION_READY=1'
