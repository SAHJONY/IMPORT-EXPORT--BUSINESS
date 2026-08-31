#!/usr/bin/env bash
set -euo pipefail

APP_URL="https://www.sahjony.com"
BUSINESS_NUMBER="+12816628581"
BUSINESS_NAME="SAHJONY LLC"
VERCEL_SCOPE="juan-gonzalezs-projects-94b6dfe9"
VERCEL_PROJECT="import-export-business"
PRODUCTION_DEPLOYMENT="https://import-export-business.vercel.app"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-${HOME}/.openclaw}"
OPENCLAW_ENV_FILE="${OPENCLAW_STATE_DIR}/.env"

for command_name in curl openclaw openssl node npx; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
done

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is intended for the macOS OpenClaw gateway host." >&2
  exit 1
fi

mkdir -p "${OPENCLAW_STATE_DIR}"
chmod 700 "${OPENCLAW_STATE_DIR}"

BRIDGE_SECRET="$(openssl rand -hex 32)"
TEMP_ENV_FILE="$(mktemp "${TMPDIR:-/tmp}/sahjony-openclaw-env.XXXXXX")"
cleanup() {
  rm -f "${TEMP_ENV_FILE}"
  unset BRIDGE_SECRET
}
trap cleanup EXIT

if [[ -f "${OPENCLAW_ENV_FILE}" ]]; then
  cp "${OPENCLAW_ENV_FILE}" "${OPENCLAW_ENV_FILE}.backup.$(date +%Y%m%d%H%M%S)"
  awk '!/^SAHJONY_APP_URL=|^SAHJONY_APP_BRIDGE_SECRET=/' "${OPENCLAW_ENV_FILE}" >"${TEMP_ENV_FILE}"
fi

{
  cat "${TEMP_ENV_FILE}"
  printf 'SAHJONY_APP_URL=%s\n' "${APP_URL}"
  printf 'SAHJONY_APP_BRIDGE_SECRET=%s\n' "${BRIDGE_SECRET}"
} >"${OPENCLAW_ENV_FILE}"
chmod 600 "${OPENCLAW_ENV_FILE}"

cd "${REPO_ROOT}"

npx --yes vercel@59.10.0 link \
  --yes \
  --project "${VERCEL_PROJECT}" \
  --team "${VERCEL_SCOPE}"

openclaw plugins install "${SCRIPT_DIR}" --force
openclaw plugins enable sahjony-app-bridge
openclaw config set channels.whatsapp.accounts.default.pluginHooks.messageReceived true --strict-json
openclaw config set plugins.entries.sahjony-app-bridge.enabled true --strict-json
openclaw config set plugins.entries.sahjony-app-bridge.config \
  "{\"appUrl\":\"${APP_URL}\",\"accountId\":\"default\",\"businessNumber\":\"${BUSINESS_NUMBER}\",\"businessName\":\"${BUSINESS_NAME}\",\"pollIntervalMs\":30000}" \
  --strict-json \
  --merge

openclaw config validate

printf '%s' "${BRIDGE_SECRET}" | npx --yes vercel@59.10.0 env add \
  OPENCLAW_APP_BRIDGE_SECRET production \
  --sensitive \
  --force \
  --yes \
  --scope "${VERCEL_SCOPE}"

npx --yes vercel@59.10.0 redeploy "${PRODUCTION_DEPLOYMENT}" \
  --target production \
  --scope "${VERCEL_SCOPE}" \
  --non-interactive

openclaw gateway restart
openclaw plugins inspect sahjony-app-bridge --runtime --json
openclaw channels status --probe
sleep 5
curl --fail --silent --show-error "${APP_URL}/whatsapp/health"
printf '\n'

echo "SAHJONY OpenClaw bridge installed. Vercel is redeploying with the rotated secret."
echo "Verify after deployment: ${APP_URL}/whatsapp/health"
