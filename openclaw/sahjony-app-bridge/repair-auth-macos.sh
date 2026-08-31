#!/usr/bin/env bash
set -euo pipefail

APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
VERCEL_SCOPE="${VERCEL_SCOPE:-juan-gonzalezs-projects-94b6dfe9}"
VERCEL_PROJECT="${VERCEL_PROJECT:-import-export-business}"
PRODUCTION_DEPLOYMENT="${PRODUCTION_DEPLOYMENT:-https://import-export-business.vercel.app}"
OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-${HOME}/.openclaw}"
OPENCLAW_ENV_FILE="${OPENCLAW_STATE_DIR}/.env"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This repair script must run on the macOS host that runs the OpenClaw gateway." >&2
  exit 1
fi

for command_name in curl openclaw openssl npx launchctl; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Missing required command: ${command_name}" >&2
    exit 1
  fi
done

mkdir -p "${OPENCLAW_STATE_DIR}"
chmod 700 "${OPENCLAW_STATE_DIR}"

BRIDGE_SECRET="$(openssl rand -hex 32)"
TMP_ENV="$(mktemp "${TMPDIR:-/tmp}/sahjony-openclaw-auth.XXXXXX")"
cleanup() {
  rm -f "${TMP_ENV}"
  unset BRIDGE_SECRET
}
trap cleanup EXIT

if [[ -f "${OPENCLAW_ENV_FILE}" ]]; then
  cp "${OPENCLAW_ENV_FILE}" "${OPENCLAW_ENV_FILE}.backup.$(date +%Y%m%d%H%M%S)"
  awk '!/^SAHJONY_APP_URL=|^SAHJONY_APP_BRIDGE_SECRET=/' "${OPENCLAW_ENV_FILE}" >"${TMP_ENV}"
fi

{
  cat "${TMP_ENV}"
  printf 'SAHJONY_APP_URL=%s\n' "${APP_URL}"
  printf 'SAHJONY_APP_BRIDGE_SECRET=%s\n' "${BRIDGE_SECRET}"
} >"${OPENCLAW_ENV_FILE}"
chmod 600 "${OPENCLAW_ENV_FILE}"

# The OpenClaw gateway is installed as a macOS launchd service. Explicitly
# publish the rotated secret into the launchd user environment so a restart
# cannot keep using a stale value inherited by the service process.
launchctl setenv SAHJONY_APP_URL "${APP_URL}"
launchctl setenv SAHJONY_APP_BRIDGE_SECRET "${BRIDGE_SECRET}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}"

npx --yes vercel@59.10.0 link \
  --yes \
  --project "${VERCEL_PROJECT}" \
  --scope "${VERCEL_SCOPE}"

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

# Wait for production to advertise the bridge as configured.
for attempt in {1..24}; do
  HEALTH="$(curl --silent --show-error --fail "${APP_URL}/whatsapp/health" || true)"
  if [[ "${HEALTH}" == *'"bridge_configured":true'* ]]; then
    break
  fi
  sleep 5
done

# Prove that the freshly rotated secret is accepted by production before
# restarting the gateway. GET requests have an empty raw body.
TIMESTAMP="$(date +%s)"
SIGNATURE="sha256=$(printf '%s.' "${TIMESTAMP}" | openssl dgst -sha256 -hmac "${BRIDGE_SECRET}" -hex | awk '{print $2}')"
AUTH_STATUS="$(curl --silent --show-error \
  --output /tmp/sahjony-openclaw-auth-check.json \
  --write-out '%{http_code}' \
  -H "Accept: application/json" \
  -H "X-SAHJONY-Timestamp: ${TIMESTAMP}" \
  -H "X-SAHJONY-Signature: ${SIGNATURE}" \
  "${APP_URL}/whatsapp/openclaw/outbox?limit=1")"

if [[ "${AUTH_STATUS}" != "200" ]]; then
  echo "Production rejected the rotated bridge secret with HTTP ${AUTH_STATUS}." >&2
  cat /tmp/sahjony-openclaw-auth-check.json >&2 || true
  exit 1
fi
rm -f /tmp/sahjony-openclaw-auth-check.json

echo "Production accepted the rotated OpenClaw HMAC secret. Restarting gateway."
openclaw gateway install --force
openclaw gateway restart

for attempt in {1..24}; do
  HEALTH="$(curl --silent --show-error --fail "${APP_URL}/whatsapp/health" || true)"
  if [[ "${HEALTH}" == *'"gateway_connected":true'* && "${HEALTH}" == *'"heartbeat_fresh":true'* && "${HEALTH}" == *'"send_ready":true'* ]]; then
    printf '%s\n' "${HEALTH}"
    echo "SAHJONY WhatsApp OpenClaw bridge is authenticated and send-ready."
    exit 0
  fi
  sleep 5
done

printf '%s\n' "${HEALTH:-}"
echo "Authentication is synchronized, but the gateway did not report connected/send-ready." >&2
openclaw gateway status --deep --require-rpc || true
openclaw channels status --probe || true
exit 1
