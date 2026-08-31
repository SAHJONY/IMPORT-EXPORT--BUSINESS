#!/usr/bin/env bash
set -euo pipefail

APP_URL="${SAHJONY_APP_URL:-https://www.sahjony.com}"
BUSINESS_NUMBER="${SAHJONY_BUSINESS_NUMBER:-+12816628581}"
BUSINESS_NAME="${SAHJONY_BUSINESS_NAME:-SAHJONY LLC}"
REPO_URL="${SAHJONY_REPO_URL:-https://github.com/SAHJONY/IMPORT-EXPORT--BUSINESS.git}"
INSTALL_ROOT="${SAHJONY_OPENCLAW_ROOT:-/opt/sahjony-openclaw}"
REPO_DIR="${INSTALL_ROOT}/repo"
BACKUP_DIR="${INSTALL_ROOT}/backups"
RUNTIME_ENV="${INSTALL_ROOT}/runtime.env"

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run as root: sudo bash $0" >&2
    exit 1
  fi
}

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

find_openclaw_container() {
  local cid
  cid="$(docker ps --format '{{.ID}} {{.Names}} {{.Image}}' | awk 'tolower($0) ~ /openclaw/ {print $1; exit}')"
  if [[ -z "${cid}" ]]; then
    cid="$(docker ps -a --format '{{.ID}} {{.Names}} {{.Image}}' | awk 'tolower($0) ~ /openclaw/ {print $1; exit}')"
  fi
  printf '%s' "${cid}"
}

container_name() {
  docker inspect --format '{{.Name}}' "$1" | sed 's#^/##'
}

published_port() {
  docker port "$1" 2>/dev/null | awk -F: 'NF>=2 {print $NF; exit}' | tr -d '[:space:]'
}

openclaw_home() {
  local cid="$1"
  for path in /root/.openclaw /home/node/.openclaw /home/openclaw/.openclaw; do
    if docker exec "$cid" sh -lc "test -d '$path' || mkdir -p '$path'" >/dev/null 2>&1; then
      printf '%s' "$path"
      return 0
    fi
  done
  printf '/root/.openclaw'
}

sync_repo() {
  mkdir -p "${INSTALL_ROOT}" "${BACKUP_DIR}"
  chmod 700 "${INSTALL_ROOT}" "${BACKUP_DIR}"
  if [[ -d "${REPO_DIR}/.git" ]]; then
    git -C "${REPO_DIR}" fetch origin main
    git -C "${REPO_DIR}" reset --hard origin/main
  else
    rm -rf "${REPO_DIR}"
    git clone --depth 1 --branch main "${REPO_URL}" "${REPO_DIR}"
  fi
}

ensure_bridge_secret() {
  local secret="${SAHJONY_APP_BRIDGE_SECRET:-}"
  if [[ -f "${RUNTIME_ENV}" ]]; then
    # shellcheck disable=SC1090
    source "${RUNTIME_ENV}" || true
    secret="${SAHJONY_APP_BRIDGE_SECRET:-${secret}}"
  fi
  if [[ ! "${secret}" =~ ^[0-9a-fA-F]{64}$ ]]; then
    secret="$(openssl rand -hex 32)"
    echo "Generated a fresh bridge secret locally."
  else
    echo "Reusing existing local bridge secret."
  fi
  umask 077
  cat >"${RUNTIME_ENV}" <<EOF
SAHJONY_APP_URL=${APP_URL}
SAHJONY_APP_BRIDGE_SECRET=${secret}
SAHJONY_BUSINESS_NUMBER=${BUSINESS_NUMBER}
SAHJONY_BUSINESS_NAME=${BUSINESS_NAME}
EOF
  chmod 600 "${RUNTIME_ENV}"
  export SAHJONY_APP_BRIDGE_SECRET="${secret}"
}

sync_secret_to_vercel_if_authorized() {
  if [[ -z "${VERCEL_TOKEN:-}" ]]; then
    echo "VERCEL_TOKEN is not present; Vercel secret sync skipped safely."
    echo "The gateway can still be prepared, but bridge health will remain gated until the same secret is stored in Vercel Production."
    return 0
  fi
  need npx
  printf '%s' "${SAHJONY_APP_BRIDGE_SECRET}" | npx --yes vercel@59.10.0 env add OPENCLAW_APP_BRIDGE_SECRET production \
    --sensitive --force --yes \
    --token "${VERCEL_TOKEN}" \
    --scope "${VERCEL_SCOPE:-juan-gonzalezs-projects-94b6dfe9}" \
    --cwd "${REPO_DIR}" >/dev/null
  echo "Synchronized bridge secret to Vercel Production (value hidden)."
}

install_bridge_into_container() {
  local cid="$1" state_dir="$2"
  docker exec "$cid" sh -lc "mkdir -p '$state_dir' && chmod 700 '$state_dir'"
  docker exec -i "$cid" sh -lc "umask 077; cat > '$state_dir/.env'" <<EOF
SAHJONY_APP_URL=${APP_URL}
SAHJONY_APP_BRIDGE_SECRET=${SAHJONY_APP_BRIDGE_SECRET}
EOF

  docker rm -f sahjony-openclaw-plugin-staging >/dev/null 2>&1 || true
  docker cp "${REPO_DIR}/openclaw/sahjony-app-bridge" "$cid:/tmp/sahjony-app-bridge"

  if docker exec "$cid" sh -lc 'command -v openclaw >/dev/null 2>&1'; then
    docker exec "$cid" openclaw plugins install /tmp/sahjony-app-bridge --force --acknowledge-install-policy-warning || true
    docker exec "$cid" openclaw plugins enable sahjony-app-bridge || true
    docker exec "$cid" openclaw config set commands.ownerAllowFrom "[\"whatsapp:${BUSINESS_NUMBER}\"]" --strict-json || true
    docker exec "$cid" openclaw config set channels.whatsapp.accounts.default.pluginHooks.messageReceived true --strict-json || true
    docker exec "$cid" openclaw config set plugins.entries.sahjony-app-bridge.enabled true --strict-json || true
    docker exec "$cid" openclaw config set plugins.entries.sahjony-app-bridge.config \
      "{\"appUrl\":\"${APP_URL}\",\"accountId\":\"default\",\"businessNumber\":\"${BUSINESS_NUMBER}\",\"businessName\":\"${BUSINESS_NAME}\",\"pollIntervalMs\":30000}" \
      --strict-json --merge || true
    docker exec "$cid" openclaw config validate
  else
    echo "OpenClaw CLI is not exposed inside the container; plugin copy completed but activation must be done through the OpenClaw UI." >&2
  fi
}

install_watchdog() {
  local cname="$1" port="$2"
  cat >"${INSTALL_ROOT}/watchdog.sh" <<EOF
#!/usr/bin/env bash
set -u
CONTAINER='${cname}'
PORT='${port}'
APP_URL='${APP_URL}'
STAMP='${INSTALL_ROOT}/last-restart'
log(){ logger -t sahjony-openclaw-watchdog -- "\$*"; }
if ! docker inspect -f '{{.State.Running}}' "\$CONTAINER" 2>/dev/null | grep -qx true; then
  log 'container not running; starting'
  docker start "\$CONTAINER" >/dev/null 2>&1 || exit 1
  exit 0
fi
if [[ -n "\$PORT" ]]; then
  code="\$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "http://127.0.0.1:\$PORT/" || true)"
  if [[ "\$code" == '000' ]]; then
    now=\$(date +%s); last=0
    [[ -f "\$STAMP" ]] && last=\$(cat "\$STAMP" 2>/dev/null || echo 0)
    if (( now - last > 300 )); then
      log 'local OpenClaw endpoint unreachable; restarting container once'
      echo "\$now" >"\$STAMP"
      docker restart "\$CONTAINER" >/dev/null 2>&1 || true
    fi
  fi
fi
remote="\$(curl -fsS --max-time 10 "\$APP_URL/whatsapp/health" 2>/dev/null || true)"
if [[ -n "\$remote" ]] && ! grep -q '"gateway_connected":true' <<<"\$remote"; then
  log 'SAHJONY app reports gateway not connected; local container left running for diagnosis'
fi
EOF
  chmod 700 "${INSTALL_ROOT}/watchdog.sh"

  cat >/etc/systemd/system/sahjony-openclaw-watchdog.service <<EOF
[Unit]
Description=SAHJONY OpenClaw health watchdog
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
ExecStart=${INSTALL_ROOT}/watchdog.sh
EOF

  cat >/etc/systemd/system/sahjony-openclaw-watchdog.timer <<'EOF'
[Unit]
Description=Run SAHJONY OpenClaw watchdog every two minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
AccuracySec=15s
Persistent=true

[Install]
WantedBy=timers.target
EOF

  systemctl daemon-reload
  systemctl enable --now sahjony-openclaw-watchdog.timer
}

install_backup() {
  local cname="$1" state_dir="$2"
  cat >"${INSTALL_ROOT}/backup.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
OUT='${BACKUP_DIR}/openclaw-state-'"\$(date -u +%Y%m%dT%H%M%SZ)"'.tar.gz'
docker exec '${cname}' sh -lc "tar -C '${state_dir}' -czf - ." >"\$OUT"
chmod 600 "\$OUT"
find '${BACKUP_DIR}' -type f -name 'openclaw-state-*.tar.gz' -mtime +14 -delete
EOF
  chmod 700 "${INSTALL_ROOT}/backup.sh"

  cat >/etc/systemd/system/sahjony-openclaw-backup.service <<EOF
[Unit]
Description=Backup SAHJONY OpenClaw durable state
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=${INSTALL_ROOT}/backup.sh
EOF

  cat >/etc/systemd/system/sahjony-openclaw-backup.timer <<'EOF'
[Unit]
Description=Daily SAHJONY OpenClaw state backup

[Timer]
OnCalendar=*-*-* 03:30:00
RandomizedDelaySec=10m
Persistent=true

[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload
  systemctl enable --now sahjony-openclaw-backup.timer
}

main() {
  require_root
  need docker; need git; need curl; need openssl
  systemctl enable --now docker >/dev/null 2>&1 || true
  local cid cname port state_dir
  cid="$(find_openclaw_container)"
  if [[ -z "${cid}" ]]; then
    echo "No existing OpenClaw Docker container was detected."
    echo "If this is Hostinger Managed OpenClaw, do not install another copy: use Settings → Hostinger Connector and keep the managed instance as the 24/7 host."
    echo "If this is a VPS, deploy OpenClaw once from Hostinger Docker Manager and rerun this bootstrap."
    exit 3
  fi
  cname="$(container_name "$cid")"
  port="$(published_port "$cid")"
  state_dir="$(openclaw_home "$cid")"
  echo "Detected OpenClaw container: ${cname}"
  echo "Detected state directory: ${state_dir}"
  [[ -n "$port" ]] && echo "Detected published dashboard port: ${port}"

  sync_repo
  ensure_bridge_secret
  sync_secret_to_vercel_if_authorized
  install_bridge_into_container "$cid" "$state_dir"
  docker update --restart unless-stopped "$cid" >/dev/null
  install_watchdog "$cname" "$port"
  install_backup "$cname" "$state_dir"
  docker restart "$cid" >/dev/null
  sleep 8

  echo "=== Local container ==="
  docker ps --filter "id=$cid" --format 'name={{.Names}} status={{.Status}} ports={{.Ports}}'
  echo "=== SAHJONY cloud health ==="
  curl -fsS "${APP_URL}/whatsapp/health" || true
  echo
  echo "SAHJONY_HOSTINGER_OPENCLAW_24X7_BOOTSTRAP_READY=1"
  echo "Next: configure HTTPS with configure-https.sh if you have a DNS name for this VPS."
}

main "$@"
