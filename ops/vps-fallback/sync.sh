#!/usr/bin/env bash
#
# SAHJONY VPS fallback — nightly sync from main (idempotent)
# Runs daily at 04:00 via cron. Pulls latest code, rebuilds, restarts services.
#
set -euo pipefail

FALLBACK_ROOT=/opt/sahjony-fallback
IE_DIR=$FALLBACK_ROOT/import-export
CC_DIR=$FALLBACK_ROOT/cubacash
VENV=$FALLBACK_ROOT/venv
ENV_DIR=/etc/sahjony-fallback

log() { echo "$(date -u +%FT%TZ) $*"; }
log "sync start"

# ---- import/export ----
(cd "$IE_DIR" && git pull -q)
(cd "$IE_DIR" && npm ci --no-audit --no-fund >/dev/null 2>&1 && npm run build >/dev/null 2>&1) || log "WARN: import/export frontend build failed"
"$VENV/bin/pip" install -q -r "$IE_DIR/requirements.txt" >/dev/null 2>&1 || log "WARN: pip requirements had issues"
systemctl restart sahjony-fallback-unified sahjony-fallback-whatsapp
log "import/export synced"

# ---- my cuba cash ----
(cd "$CC_DIR" && git pull -q)
if ! grep -q "^NEXT_PUBLIC_SUPABASE_URL=$" "$ENV_DIR/cubacash.env" 2>/dev/null; then
  (cd "$CC_DIR" && npm ci --no-audit --no-fund >/dev/null 2>&1 && npm run build >/dev/null 2>&1) || log "WARN: cubacash build failed"
  systemctl restart sahjony-fallback-cubacash
  log "mycubacash synced"
else
  log "mycubacash skipped (env secrets not filled yet)"
fi

systemctl reload nginx
echo "{\"fallback\":\"sahjony-vps\",\"apps\":[\"import-export\",\"mycubacash\"],\"updated\":\"$(date -u +%FT%TZ)\"}" > "$FALLBACK_ROOT/health.json"
log "sync done"
