#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CONFIG_DIR="$HERMES_HOME"
CONFIG_FILE="$CONFIG_DIR/config.yaml"
mkdir -p "$CONFIG_DIR"

if [ -f "$CONFIG_FILE" ]; then
  cp "$CONFIG_FILE" "$CONFIG_FILE.bak.$(date +%Y%m%d%H%M%S)"
fi

cat > "$CONFIG_FILE" <<'YAML'
web:
  search_backend: "ddgs"
  extract_backend: "firecrawl"
YAML

if command -v hermes >/dev/null 2>&1; then
  hermes doctor || true
fi

printf 'Configured Sofía Hermes web tools in %s\n' "$CONFIG_FILE"
printf 'web_search backend: ddgs (keyless)\n'
printf 'web_extract backend: firecrawl (keyless where supported; FIRECRAWL_API_KEY optional)\n'
