#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${OPENCLAW_DOMAIN:-}"
EMAIL="${LETSENCRYPT_EMAIL:-}"
INSTALL_ROOT="${SAHJONY_OPENCLAW_ROOT:-/opt/sahjony-openclaw}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo OPENCLAW_DOMAIN=openclaw.example.com LETSENCRYPT_EMAIL=you@example.com bash $0" >&2
  exit 1
fi
if [[ -z "${DOMAIN}" || -z "${EMAIL}" ]]; then
  echo "OPENCLAW_DOMAIN and LETSENCRYPT_EMAIL are required." >&2
  exit 1
fi
command -v docker >/dev/null || { echo "Docker missing" >&2; exit 1; }

CID="$(docker ps --format '{{.ID}} {{.Names}} {{.Image}}' | awk 'tolower($0) ~ /openclaw/ {print $1; exit}')"
[[ -n "${CID}" ]] || { echo "No running OpenClaw container found" >&2; exit 1; }
PORT="$(docker port "${CID}" 2>/dev/null | awk -F: 'NF>=2 {print $NF; exit}' | tr -d '[:space:]')"
[[ -n "${PORT}" ]] || { echo "Could not detect OpenClaw published port" >&2; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y nginx certbot python3-certbot-nginx

cat >/etc/nginx/sites-available/sahjony-openclaw <<EOF
map \$http_upgrade \$connection_upgrade {
  default upgrade;
  '' close;
}
server {
  listen 80;
  listen [::]:80;
  server_name ${DOMAIN};
  location / {
    proxy_pass http://127.0.0.1:${PORT};
    proxy_http_version 1.1;
    proxy_set_header Upgrade \$http_upgrade;
    proxy_set_header Connection \$connection_upgrade;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_read_timeout 3600;
    proxy_send_timeout 3600;
  }
}
EOF
ln -sf /etc/nginx/sites-available/sahjony-openclaw /etc/nginx/sites-enabled/sahjony-openclaw
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m "${EMAIL}" --redirect

mkdir -p "${INSTALL_ROOT}"
printf 'https://%s\n' "${DOMAIN}" >"${INSTALL_ROOT}/dashboard-url"
chmod 600 "${INSTALL_ROOT}/dashboard-url"

echo "OPENCLAW_HTTPS_READY=1"
echo "Dashboard: https://${DOMAIN}"
echo "Keep the OpenClaw gateway token private; HTTPS does not replace gateway authentication."
