#!/usr/bin/env bash
#
# SAHJONY VPS fallback host — setup script (idempotent, safe to re-run)
#
# Installs a HOT STANDBY of both business applications on the Hostinger VPS
# (69.62.68.67) so traffic can fail over here if Vercel ever goes down again:
#
#   App 1: SAHJONY import/export  (sahjony.com, www.sahjony.com)
#          static pages via nginx + Python FastAPI backends via uvicorn
#   App 2: MY CUBA CASH           (mycubacash.com, www.mycubacash.com)
#          Next.js via `next start` behind nginx
#
# What this script NEVER touches:
#   - /root/.hermes, /opt/sahjony-hermes (the live WhatsApp gateway)
#   - any existing systemd service it did not create (sahjony-fallback-*)
#   - ports 80/443 if something other than our nginx owns them (aborts instead)
#
# Run on the VPS as root (Hostinger web terminal):
#   curl -sSL https://raw.githubusercontent.com/SAHJONY/IMPORT-EXPORT--BUSINESS/ops/vps-fallback-host/ops/vps-fallback/setup.sh | bash
#
set -euo pipefail

FALLBACK_ROOT=/opt/sahjony-fallback
IE_DIR=$FALLBACK_ROOT/import-export
CC_DIR=$FALLBACK_ROOT/cubacash
VENV=$FALLBACK_ROOT/venv
ENV_DIR=/etc/sahjony-fallback
VPS_IP=69.62.68.67

step()  { echo "==> $*"; }
pass()  { echo "    PASS: $*"; }
warn()  { echo "    WARN: $*"; }
fail()  { echo "    FAIL: $*" >&2; }

# ---------------------------------------------------------------- preflight
step "Preflight"
[[ "$(id -u)" == 0 ]] || { fail "must run as root"; exit 1; }
[[ -f /etc/debian_version ]] || { fail "Debian/Ubuntu-based OS required"; exit 1; }
pass "running as root on Debian-based OS"

free -m | awk '/^Mem:/{print "    RAM: "$2" MB total"}'
df -h / | awk 'NR==2{print "    Disk: "$4" free on /"}'

# Never disturb the live WhatsApp gateway
for d in /root/.hermes /opt/sahjony-hermes; do
  [[ -e "$d" ]] && echo "    Hermes present at $d — will not touch"
done

# Ports 80/443: only proceed if free or owned by our nginx
for p in 80 443; do
  owner="$(ss -ltnp 2>/dev/null | awk -v port=":$p " '$4 ~ port {print}' | grep -o 'users:(("[^"]*"' | head -1 || true)"
  if [[ -z "$owner" ]]; then
    echo "    Port $p free"
  elif grep -q nginx <<<"$owner"; then
    echo "    Port $p owned by nginx (ours) — ok"
  else
    fail "port $p is owned by something else ($owner) — aborting to protect live services"
    exit 1
  fi
done
pass "preflight ok"

# ---------------------------------------------------------------- packages
step "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx python3-venv python3-pip git curl
pass "nginx, certbot, python3-venv, git installed"

# Node 22 for the Next.js app (MY CUBA CASH requires node >= 22)
if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | cut -d. -f1 | tr -dc 0-9)" -lt 22 ]]; then
  step "Installing Node.js 22"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
  apt-get install -y -qq nodejs
fi
pass "node $(node -v) available"

# ---------------------------------------------------------------- code
step "Fetching application code"
mkdir -p "$FALLBACK_ROOT" "$ENV_DIR"
chmod 700 "$ENV_DIR"

if [[ -d "$IE_DIR/.git" ]]; then (cd "$IE_DIR" && git pull -q); else git clone -q --depth 1 https://github.com/SAHJONY/IMPORT-EXPORT--BUSINESS.git "$IE_DIR"; fi
if [[ -d "$CC_DIR/.git" ]]; then (cd "$CC_DIR" && git pull -q); else git clone -q --depth 1 https://github.com/SAHJONY/CUBACASH.git "$CC_DIR"; fi
pass "repos present at $IE_DIR and $CC_DIR"

# ---------------------------------------------------------------- import/export frontend
step "Building import/export frontend"
(cd "$IE_DIR" && npm ci --no-audit --no-fund >/dev/null 2>&1 || npm install --no-audit --no-fund >/dev/null 2>&1) || warn "npm install had issues, continuing"
if (cd "$IE_DIR" && npm run build >/dev/null 2>&1); then
  pass "vite build ok"
else
  warn "vite build failed — static public/ pages will still be served"
fi

# ---------------------------------------------------------------- python backends
step "Python API backends"
[[ -d "$VENV" ]] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip >/dev/null 2>&1 || true
"$VENV/bin/pip" install -q fastapi "uvicorn[standard]" >/dev/null 2>&1 || warn "fastapi/uvicorn install had issues"
(cd "$IE_DIR" && "$VENV/bin/pip" install -q -r requirements.txt >/dev/null 2>&1) || warn "requirements.txt partially failed — core endpoints still wired"

# Optional secrets template (empty = backends run in degraded/public-only mode)
[[ -f "$ENV_DIR/import-export.env" ]] || {
  cat > "$ENV_DIR/import-export.env" <<'EOF'
# Optional secrets for the import/export Python backends.
# Leave empty: public endpoints work, private ones report unconfigured.
# SUPABASE_SERVICE_ROLE_KEY=
# META_WHATSAPP_VERIFY_TOKEN=
EOF
  chmod 600 "$ENV_DIR/import-export.env"
}

# systemd units for the FastAPI apps
for svc in unified:8101:unified_api whatsapp:8102:whatsapp_cloud_primary_api; do
  name="${svc%%:*}"; rest="${svc#*:}"; port="${rest%%:*}"; module="${rest##*:}"
  cat > "/etc/systemd/system/sahjony-fallback-$name.service" <<EOF
[Unit]
Description=SAHJONY fallback $module (port $port)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$IE_DIR
EnvironmentFile=-$ENV_DIR/import-export.env
ExecStart=$VENV/bin/uvicorn $module:app --host 127.0.0.1 --port $port --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
done
pass "systemd units written (sahjony-fallback-unified, sahjony-fallback-whatsapp)"

# ---------------------------------------------------------------- my cuba cash (next.js)
step "MY CUBA CASH (Next.js)"
(cd "$CC_DIR" && npm ci --no-audit --no-fund >/dev/null 2>&1 || npm install --no-audit --no-fund >/dev/null 2>&1) || warn "npm install had issues, continuing"

# Env template from the exact Vercel production var names (values stay with Juan)
if [[ ! -f "$ENV_DIR/cubacash.env" ]]; then
  cat > "$ENV_DIR/cubacash.env" <<'EOF'
# MY CUBA CASH production secrets — copy VALUES from the Vercel dashboard
# (project cubacash -> Settings -> Environment Variables). File is chmod 600.
SOFIA_SECRET=
SUPABASE_SERVICE_ROLE_KEY=
SOFIA_INGEST_SECRET=
TELEGRAM_CHANNEL_ID=
TELEGRAM_BOT_TOKEN=
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=
SANCTIONS_PROVIDER=
APP_ENV=production
EOF
  chmod 600 "$ENV_DIR/cubacash.env"
fi

# Validate every required key so missing values surface instead of failing silently
CC_REQUIRED="SOFIA_SECRET SUPABASE_SERVICE_ROLE_KEY SOFIA_INGEST_SECRET TELEGRAM_CHANNEL_ID TELEGRAM_BOT_TOKEN NEXT_PUBLIC_SUPABASE_URL NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY SANCTIONS_PROVIDER"
CC_MISSING=""
for k in $CC_REQUIRED; do
  if ! grep -q "^${k}=[^[:space:]]" "$ENV_DIR/cubacash.env" 2>/dev/null; then
    CC_MISSING="$CC_MISSING $k"
  fi
done
if [[ -n "$CC_MISSING" ]]; then
  warn "cubacash.env missing values:$CC_MISSING"
  warn "  -> Telegram features off without TELEGRAM_*; privileged intake ops limited"
  warn "     without SUPABASE_SERVICE_ROLE_KEY; Sofia auth uses fallback-only secrets"
  warn "     unless SOFIA_SECRET / SOFIA_INGEST_SECRET match production."
fi

# NEXT_PUBLIC_* vars are inlined at build time — only build when they are set
if grep -q "^NEXT_PUBLIC_SUPABASE_URL=$" "$ENV_DIR/cubacash.env"; then
  warn "cubacash.env secrets not filled yet — Next.js build skipped."
  warn "Fill $ENV_DIR/cubacash.env (values from Vercel dashboard), then re-run this script."
  CC_BUILD_READY=0
else
  set -a; . "$ENV_DIR/cubacash.env"; set +a
  if (cd "$CC_DIR" && npm run build >/dev/null 2>&1); then pass "next build ok"; CC_BUILD_READY=1
  else warn "next build failed — check $ENV_DIR/cubacash.env values"; CC_BUILD_READY=0; fi
fi

cat > /etc/systemd/system/sahjony-fallback-cubacash.service <<EOF
[Unit]
Description=SAHJONY fallback MY CUBA CASH (port 8103)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$CC_DIR
EnvironmentFile=$ENV_DIR/cubacash.env
ExecStart=/usr/bin/npm run start -- -p 8103
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
pass "systemd unit written (sahjony-fallback-cubacash)"

# ---------------------------------------------------------------- nginx
step "nginx (both domains)"
cat > /etc/nginx/sites-available/sahjony-fallback <<EOF
# SAHJONY VPS fallback — hot standby. DNS points here only during a failover.
# TLS is issued at failover time: certbot --nginx -d sahjony.com -d www.sahjony.com -d mycubacash.com -d www.mycubacash.com

upstream ie_unified  { server 127.0.0.1:8101; }
upstream ie_whatsapp { server 127.0.0.1:8102; }
upstream cubacash    { server 127.0.0.1:8103; }

# ---- App 1: SAHJONY import/export ----
server {
    listen 80;
    server_name sahjony.com www.sahjony.com;
    root $IE_DIR/public;

    location /assets/ { alias $IE_DIR/dist/assets/; expires 7d; }

    location /api/ {
        proxy_pass http://ie_unified;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    location /whatsapp/ {
        proxy_pass http://ie_whatsapp;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location = /fallback-health { alias $FALLBACK_ROOT/health.json; default_type application/json; }

    location / { try_files \$uri \$uri.html /index.html; }
}

# ---- App 2: MY CUBA CASH ----
server {
    listen 80;
    server_name mycubacash.com www.mycubacash.com;

    location = /fallback-health { alias $FALLBACK_ROOT/health.json; default_type application/json; }

    location / {
        proxy_pass http://cubacash;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
ln -sf /etc/nginx/sites-available/sahjony-fallback /etc/nginx/sites-enabled/sahjony-fallback
# Keep the default site only if nothing else serves port 80; our server_names are explicit so it can stay.
nginx -t || { fail "nginx config invalid"; exit 1; }
pass "nginx config valid"

# Health file served at /fallback-health on both domains
cat > "$FALLBACK_ROOT/health.json" <<EOF
{"fallback":"sahjony-vps","apps":["import-export","mycubacash"],"updated":"$(date -u +%FT%TZ)"}
EOF

# ---------------------------------------------------------------- start everything
step "Starting services"
systemctl daemon-reload
systemctl enable -q sahjony-fallback-unified sahjony-fallback-whatsapp >/dev/null 2>&1 || true
systemctl restart sahjony-fallback-unified sahjony-fallback-whatsapp
pass "import/export API backends started (ports 8101, 8102)"

if [[ "${CC_BUILD_READY:-0}" == 1 ]]; then
  systemctl enable -q sahjony-fallback-cubacash >/dev/null 2>&1 || true
  systemctl restart sahjony-fallback-cubacash
  pass "MY CUBA CASH started (port 8103)"
else
  warn "MY CUBA CASH not started (needs $ENV_DIR/cubacash.env values first)"
fi

systemctl reload nginx 2>/dev/null || systemctl restart nginx
pass "nginx reloaded"

# Firewall: allow web traffic if ufw is active
ufw status 2>/dev/null | grep -q "Status: active" && { ufw allow 80/tcp >/dev/null 2>&1; ufw allow 443/tcp >/dev/null 2>&1; echo "    ufw: opened 80/443"; } || true

# ---------------------------------------------------------------- nightly sync
step "Nightly sync (keeps fallback fresh from main)"
cp "$(dirname "$0")/sync.sh" "$FALLBACK_ROOT/sync.sh" 2>/dev/null || curl -fsSL -o "$FALLBACK_ROOT/sync.sh" https://raw.githubusercontent.com/SAHJONY/IMPORT-EXPORT--BUSINESS/main/ops/vps-fallback/sync.sh
chmod +x "$FALLBACK_ROOT/sync.sh"
{ crontab -l 2>/dev/null | grep -v "sahjony-fallback/sync.sh" || true; echo "0 4 * * * $FALLBACK_ROOT/sync.sh >> /var/log/sahjony-fallback-sync.log 2>&1"; } | crontab -
pass "sync cron installed (daily 04:00)"

# ---------------------------------------------------------------- verify
step "Verification"
sleep 3
check() { # check <label> <url>
  code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -H "Host: $3" "http://127.0.0.1:$2$4" 2>/dev/null || echo 000)"
  echo "    [$code] $1"
}
check "import/export API (unified)"  8101 www.sahjony.com "/health"
check "import/export API (whatsapp)" 8102 www.sahjony.com "/whatsapp/health"
check "MY CUBA CASH"                 8103 mycubacash.com "/api/health"
check "nginx static (sahjony)"       80   www.sahjony.com "/suppliers-es.html"

echo ""
echo "=============================================================="
echo " Fallback host setup complete."
echo " Test locally on the VPS: curl -H 'Host: www.sahjony.com' http://127.0.0.1/fallback-health"
echo " Public traffic arrives only after DNS failover — see FAILOVER.md"
echo "=============================================================="
