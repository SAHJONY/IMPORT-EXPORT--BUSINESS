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

if ! openclaw plugins install --help 2>&1 | grep -Fq -- "--acknowledge-install-policy-warning"; then
  if node -e '
    const [major, minor, patch] = process.versions.node.split(".").map(Number);
    const supported =
      (major === 22 && (minor > 22 || (minor === 22 && patch >= 3))) ||
      (major === 24 && minor >= 15) ||
      (major === 25 && minor >= 9);
    process.exit(supported ? 0 : 1);
  '; then
    echo "Updating OpenClaw to a stable release with granular install-policy acknowledgements."
    openclaw update --channel stable --yes --timeout 1800 || true
  fi
fi

if ! openclaw plugins install --help 2>&1 | grep -Fq -- "--acknowledge-install-policy-warning"; then
  echo "Installing the official isolated OpenClaw runtime with a supported Node release."
  OPENCLAW_CLI_INSTALLER="$(mktemp "${TMPDIR:-/tmp}/openclaw-install-cli.XXXXXX")"
  curl --fail --silent --show-error --location \
    --proto '=https' \
    --tlsv1.2 \
    "https://openclaw.ai/install-cli.sh" \
    --output "${OPENCLAW_CLI_INSTALLER}"
  bash -n "${OPENCLAW_CLI_INSTALLER}"
  bash "${OPENCLAW_CLI_INSTALLER}" \
    --prefix "${HOME}/.openclaw" \
    --version latest \
    --no-onboard
  rm -f "${OPENCLAW_CLI_INSTALLER}"
  export PATH="${HOME}/.openclaw/bin:${PATH}"
  hash -r
fi

if ! openclaw plugins install --help 2>&1 | grep -Fq -- "--acknowledge-install-policy-warning"; then
  echo "The installed OpenClaw release still lacks granular install-policy acknowledgements." >&2
  echo "The official isolated OpenClaw installation did not provide the required policy support." >&2
  exit 1
fi

echo "Administrator approval is required to keep this Mac awake while connected to power."
sudo -v
sudo pmset -c sleep 0 displaysleep 10
sudo pmset -a autorestart 1 || true
sudo pmset -c womp 1 tcpkeepalive 1 powernap 1 || true

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
  --scope "${VERCEL_SCOPE}"

openclaw plugins install @openclaw/codex --force
openclaw plugins enable codex --accept-capabilities
openclaw plugins install clawhub:@openclaw/whatsapp --force
openclaw plugins enable whatsapp --accept-capabilities
openclaw plugins install "${SCRIPT_DIR}" \
  --force \
  --acknowledge-install-policy-warning
openclaw plugins enable sahjony-app-bridge
openclaw config set commands.ownerAllowFrom \
  '["whatsapp:+12816628581"]' \
  --strict-json
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

openclaw gateway install --force
openclaw gateway restart

GATEWAY_READY=0
for attempt in {1..12}; do
  if openclaw gateway status --deep --require-rpc; then
    GATEWAY_READY=1
    break
  fi
  sleep 5
done
if [[ "${GATEWAY_READY}" -ne 1 ]]; then
  echo "OpenClaw gateway did not become RPC-ready within 60 seconds." >&2
  exit 1
fi

openclaw plugins inspect sahjony-app-bridge --runtime --json
openclaw channels status --probe || true

BRIDGE_READY=0
for attempt in {1..12}; do
  HEALTH_RESPONSE="$(curl --fail --silent --show-error "${APP_URL}/whatsapp/health" || true)"
  if [[ -n "${HEALTH_RESPONSE}" ]]; then
    printf '%s\n' "${HEALTH_RESPONSE}"
  fi
  if [[ "${HEALTH_RESPONSE}" == *'"gateway_connected":true'* ]]; then
    BRIDGE_READY=1
    break
  fi
  sleep 5
done
if [[ "${BRIDGE_READY}" -ne 1 ]]; then
  echo "The SAHJONY application did not receive a connected gateway heartbeat within 60 seconds." >&2
  exit 1
fi

pmset -g custom

echo "SAHJONY OpenClaw bridge installed. Vercel is redeploying with the rotated secret."
echo "Verify after deployment: ${APP_URL}/whatsapp/health"
echo "Keep a MacBook connected to power with its lid open, or use a supported clamshell setup."
