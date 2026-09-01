#!/usr/bin/env bash
set -euo pipefail

KEY_FILE="${NVIDIA_API_KEY_FILE:-/root/.sahjony-nvidia-api-key}"
BASE_URL="${NVIDIA_NIM_BASE_URL:-https://integrate.api.nvidia.com/v1}"
MODEL="${NVIDIA_NIM_MODEL:-nvidia/nemotron-3-ultra-550b-a55b}"
PROFILE="${NVIDIA_NIM_AUTH_PROFILE:-nvidia:nim}"

fail(){ echo "NVIDIA_NIM_SETUP_FAIL=$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail docker_missing
command -v curl >/dev/null 2>&1 || fail curl_missing
[[ -s "$KEY_FILE" ]] || fail api_key_file_missing

key="$(tr -d '\r\n' < "$KEY_FILE")"
[[ "$key" == nvapi-* ]] || fail api_key_format_invalid

cid="$(docker ps --format '{{.ID}} {{.Names}} {{.Image}}' | awk 'tolower($0) ~ /openclaw/ {print $1; exit}')"
[[ -n "$cid" ]] || fail openclaw_container_not_running

docker exec "$cid" sh -lc 'command -v openclaw >/dev/null 2>&1' || fail openclaw_cli_missing

# Store the NVIDIA key in OpenClaw's auth store through stdin. Never place it in
# command arguments, config JSON, shell history, or repository content.
cat "$KEY_FILE" | docker exec -i "$cid" openclaw models auth paste-api-key \
  --provider nvidia --profile-id "$PROFILE" >/dev/null

docker exec "$cid" openclaw models auth order set --provider nvidia "$PROFILE" >/dev/null

# OpenClaw ships the NVIDIA provider. Pin the official NIM/OpenAI-compatible
# endpoint explicitly so the runtime is deterministic even if defaults change.
docker exec "$cid" openclaw config set models.providers.nvidia \
  "{\"baseUrl\":\"${BASE_URL}\",\"api\":\"openai-completions\"}" \
  --strict-json --merge >/dev/null

# Keep the primary model unchanged. NVIDIA is an ordered failover target only.
docker exec "$cid" openclaw config set agents.defaults.models \
  "{\"nvidia/${MODEL}\":{\"agentRuntime\":{\"id\":\"openclaw\"}}}" \
  --strict-json --merge >/dev/null

fallbacks="$(docker exec "$cid" openclaw models fallbacks list 2>&1 || true)"
if ! grep -Fq "nvidia/${MODEL}" <<<"$fallbacks"; then
  docker exec "$cid" openclaw models fallbacks add "nvidia/${MODEL}" >/dev/null
fi

docker exec "$cid" openclaw config validate >/dev/null

# Validate the NVIDIA credential and hosted NIM endpoint independently of the
# OpenAI primary provider. Do not emit the API key or raw headers.
response="$(curl -fsS --connect-timeout 10 --max-time 120 \
  -H "Authorization: Bearer ${key}" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply exactly SAHJONY_NVIDIA_NIM_OK\"}],\"max_tokens\":32,\"temperature\":0}" \
  "${BASE_URL%/}/chat/completions")" || fail hosted_inference_request_failed

grep -q 'SAHJONY_NVIDIA_NIM_OK' <<<"$response" || fail hosted_inference_reply_unexpected

# Restart once so the gateway reloads auth/provider/fallback state, while keeping
# the retained WhatsApp session volumes untouched.
docker update --restart unless-stopped "$cid" >/dev/null
docker restart "$cid" >/dev/null
sleep 10

docker exec "$cid" openclaw config validate >/dev/null

primary="$(docker exec "$cid" openclaw config get agents.defaults.model --json 2>/dev/null || true)"
configured_fallbacks="$(docker exec "$cid" openclaw models fallbacks list 2>&1 || true)"

printf '%s\n' "$primary"
printf '%s\n' "$configured_fallbacks"
grep -q 'openai/gpt-5.6-sol' <<<"$primary" || fail gpt56_sol_primary_not_preserved
grep -Fq "nvidia/${MODEL}" <<<"$configured_fallbacks" || fail nvidia_fallback_not_persisted

rm -f "$KEY_FILE"
echo "NVIDIA_NIM_BASE_URL=${BASE_URL}"
echo "NVIDIA_NIM_MODEL=${MODEL}"
echo NVIDIA_NIM_HOSTED_INFERENCE=READY
echo NVIDIA_NIM_OPENCLAW_FALLBACK=READY
