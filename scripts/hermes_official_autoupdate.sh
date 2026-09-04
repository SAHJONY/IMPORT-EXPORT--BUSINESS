#!/usr/bin/env bash
set -euo pipefail

# SAHJONY Sofía Hermes official-release updater.
# Trust source: NousResearch/hermes-agent official GitHub releases only.
# Stable releases only; drafts/prereleases are ignored.

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
REPO_DIR="${HERMES_HOME}/hermes-agent"
STATE_DIR="${HERMES_HOME}/sahjony-update-state"
LOG_DIR="${HERMES_HOME}/logs"
mkdir -p "$STATE_DIR" "$LOG_DIR"

LOCK_FILE="$STATE_DIR/hermes-update.lock"
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG_DIR/hermes-autoupdate.log"; }

if ! command -v hermes >/dev/null 2>&1; then
  log "Hermes CLI not installed; refusing autonomous update."
  exit 2
fi

if ! command -v curl >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
  log "curl/python3 required; refusing autonomous update."
  exit 2
fi

release_json="$(curl -fsSL --retry 3 --connect-timeout 10 https://api.github.com/repos/NousResearch/hermes-agent/releases/latest)"
read -r tag prerelease draft <<EOF
$(python3 - <<'PY' "$release_json"
import json,sys
r=json.loads(sys.argv[1])
print(r.get('tag_name',''), str(bool(r.get('prerelease'))).lower(), str(bool(r.get('draft'))).lower())
PY
)
EOF

if [[ -z "$tag" || "$prerelease" == "true" || "$draft" == "true" ]]; then
  log "No eligible stable official release found."
  exit 0
fi

if [[ ! "$tag" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  log "Release tag '$tag' is not stable semver; refusing update."
  exit 3
fi

current="$(hermes --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
latest="${tag#v}"
if [[ "$current" == "$latest" ]]; then
  log "Already current: $latest"
  exit 0
fi

log "Official stable Hermes release detected: current=${current:-unknown} latest=$latest"

snapshot="$STATE_DIR/pre-update-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -czf "$snapshot" -C "$HERMES_HOME" --exclude='hermes-agent/.git' --exclude='logs' . || {
  log "Snapshot failed; refusing update."
  exit 4
}

pre_head=""
if [[ -d "$REPO_DIR/.git" ]]; then
  pre_head="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || true)"
fi

if ! hermes update </dev/null >>"$LOG_DIR/hermes-autoupdate.log" 2>&1; then
  log "hermes update failed. Manual recovery may use snapshot: $snapshot"
  exit 5
fi

if ! hermes doctor >>"$LOG_DIR/hermes-autoupdate.log" 2>&1; then
  log "Post-update doctor failed; attempting rollback."
  if [[ -n "$pre_head" && -d "$REPO_DIR/.git" ]]; then
    git -C "$REPO_DIR" reset --hard "$pre_head" >>"$LOG_DIR/hermes-autoupdate.log" 2>&1 || true
    if command -v uv >/dev/null 2>&1; then
      (cd "$REPO_DIR" && uv pip install -e '.[all]' >>"$LOG_DIR/hermes-autoupdate.log" 2>&1) || true
    fi
  fi
  log "Rollback attempted. Snapshot retained: $snapshot"
  exit 6
fi

installed="$(hermes --version 2>/dev/null | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
if [[ "$installed" != "$latest" ]]; then
  log "Update completed but installed version '$installed' != official latest '$latest'; refusing success."
  exit 7
fi

printf '%s\n' "$latest" > "$STATE_DIR/last-good-version"
printf '%s\n' "$tag" > "$STATE_DIR/last-good-tag"
log "Hermes autonomous update successful: $latest"
