#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Run this on the macOS OpenClaw gateway host." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Install the current SAHJONY bridge runtime from this checkout.
openclaw plugins install "${SCRIPT_DIR}" --force --acknowledge-install-policy-warning
openclaw plugins enable sahjony-app-bridge

# OpenClaw 2026.8 gates conversation-turn hooks for non-bundled plugins.
openclaw config set plugins.entries.sahjony-app-bridge.hooks.allowConversationAccess true --strict-json
openclaw config set plugins.entries.sahjony-app-bridge.enabled true --strict-json
openclaw config set channels.whatsapp.accounts.default.pluginHooks.messageReceived true --strict-json || true

openclaw config validate
openclaw gateway restart
sleep 3

openclaw plugins inspect sahjony-app-bridge --runtime --json
openclaw channels status --probe

echo "Inbound bridge repair installed. Send one fresh WhatsApp DM from another number now."
echo "Then inspect: openclaw channels logs --channel whatsapp --lines 100"
