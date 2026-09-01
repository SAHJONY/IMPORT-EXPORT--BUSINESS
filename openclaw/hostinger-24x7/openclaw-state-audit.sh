#!/usr/bin/env bash
set -euo pipefail

# Redacted, non-mutating OpenClaw/WhatsApp state inventory.
# ROOT_PREFIX=/mnt/sdb1 when run from Hostinger Recovery, / when run live.
ROOT_PREFIX="${ROOT_PREFIX:-/}"
root="${ROOT_PREFIX%/}"
[[ -n "$root" ]] || root=/

p(){
  if [[ "$root" == / ]]; then printf '/%s' "${1#/}"; else printf '%s/%s' "$root" "${1#/}"; fi
}

say(){ printf '[openclaw-state-audit] %s\n' "$*"; }

safe_stat(){
  local f="$1"
  stat -c '%n|type=%F|size=%s|mtime=%y|mode=%a|uid=%u|gid=%g' "$f" 2>/dev/null || true
}

hash_file(){
  local f="$1"
  if [[ -f "$f" ]]; then printf '%s|sha256=%s\n' "$f" "$(sha256sum "$f" | awk '{print $1}')"; fi
}

redact(){
  sed -E \
    -e 's/((TOKEN|SECRET|PASSWORD|PASS|API[_-]?KEY|PRIVATE[_-]?KEY|ACCESS[_-]?TOKEN|AUTH)[A-Za-z0-9_-]*[[:space:]]*[:=][[:space:]]*)([^[:space:]]+)/\1<redacted>/Ig' \
    -e 's/(Bearer[[:space:]]+)[A-Za-z0-9._~+\/-]+/\1<redacted>/Ig' \
    -e 's#(https?://)[^/@[:space:]]+:[^/@[:space:]]+@#\1<redacted>@#g' \
    -e 's/(--env|-e)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*=[^[:space:]]+/\1 <redacted-env>/g'
}

# Deliberately bounded discovery. `head` closing early can SIGPIPE find/sort/grep;
# that is expected and must never abort a read-only audit under global pipefail.
bounded_lines(){
  local limit="$1"
  set +o pipefail
  head -n "$limit" || true
  set -o pipefail
}

bounded_find_sorted(){
  local base="$1" depth="$2" limit="$3"; shift 3
  set +o pipefail
  find "$base" -xdev -maxdepth "$depth" "$@" -print 2>/dev/null | sort -u | head -n "$limit" || true
  set -o pipefail
}

say "ROOT_PREFIX=$root"
if [[ -f "$(p /etc/os-release)" ]]; then
  grep -E '^(PRETTY_NAME|NAME|VERSION|VERSION_ID)=' "$(p /etc/os-release)" | redact || true
fi

echo '=== RUNTIME STATE DIRECTORIES ==='
for d in /var/lib/docker /var/lib/containerd /root/.openclaw /root/.config/openclaw /opt/openclaw /srv/openclaw /var/lib/openclaw /var/lib/sahjony-whatsapp-guardian; do
  f="$(p "$d")"
  if [[ -e "$f" ]]; then
    safe_stat "$f"
    if [[ -d "$f" ]]; then
      count="$(find "$f" -mindepth 1 -maxdepth 2 -print 2>/dev/null | wc -l | tr -d ' ')"
      echo "$f|entries_depth2=$count"
    fi
  fi
done

echo '=== DEPLOYMENT / COMPOSE ARTIFACTS ==='
for base in "$(p /root)" "$(p /opt)" "$(p /srv)" "$(p /etc)"; do
  [[ -d "$base" ]] || continue
  while read -r f; do
    [[ -n "$f" ]] || continue
    safe_stat "$f"
    hash_file "$f"
  done < <(bounded_find_sorted "$base" 7 240 -type f \( -iname '*openclaw*.sh' -o -iname '*openclaw*.service' -o -iname '*openclaw*.env' -o -name 'docker-compose.yml' -o -name 'compose.yml' -o -name 'compose.yaml' \))
done

echo '=== OPENCLAW DEPLOY SCRIPT STRUCTURE (REDACTED) ==='
for f in "$(p /root/openclaw-deploy.sh)" "$(p /opt/openclaw-deploy.sh)" "$(p /srv/openclaw-deploy.sh)"; do
  [[ -f "$f" ]] || continue
  echo "--- $f"
  set +o pipefail
  grep -nEi 'docker|compose|openclaw|whatsapp|node|npm|systemctl|mkdir|install|volume|mount|restart|image|container' "$f" 2>/dev/null | head -n 260 | redact || true
  set -o pipefail
done

echo '=== COMPOSE STRUCTURE (NO ENV VALUES) ==='
for base in "$(p /root)" "$(p /opt)" "$(p /srv)"; do
  [[ -d "$base" ]] || continue
  while read -r f; do
    [[ -n "$f" ]] || continue
    if grep -Eqi 'openclaw|whatsapp|claw' "$f"; then
      echo "--- $f"
      set +o pipefail
      grep -nE '^[[:space:]]*(image:|container_name:|restart:|volumes:|ports:|network_mode:|working_dir:|command:|entrypoint:|env_file:|-[[:space:]]+[^=]+:[^=]+)' "$f" 2>/dev/null | head -n 220 | redact || true
      set -o pipefail
    fi
  done < <(bounded_find_sorted "$base" 7 160 -type f \( -name 'docker-compose.yml' -o -name 'compose.yml' -o -name 'compose.yaml' \))
done

echo '=== WHATSAPP / SESSION CANDIDATE FILE METADATA ONLY ==='
for base in "$(p /root)" "$(p /opt)" "$(p /srv)" "$(p /var/lib)"; do
  [[ -d "$base" ]] || continue
  while read -r f; do
    [[ -n "$f" ]] || continue
    safe_stat "$f"
    hash_file "$f"
  done < <(bounded_find_sorted "$base" 9 320 -type f \( -iname '*whatsapp*' -o -iname '*baileys*' -o -iname 'creds.json' -o -iname '*session*.json' -o -iname '*auth*.json' -o -iname '*device*.json' \))
done

echo '=== OPENCLAW / WHATSAPP BACKUP CANDIDATES ==='
for base in "$(p /root)" "$(p /opt)" "$(p /srv)" "$(p /var/backups)"; do
  [[ -d "$base" ]] || continue
  while read -r f; do
    [[ -n "$f" ]] || continue
    safe_stat "$f"
    hash_file "$f"
  done < <(bounded_find_sorted "$base" 8 240 -type f \( -iname '*openclaw*.tar' -o -iname '*openclaw*.tar.gz' -o -iname '*openclaw*.tgz' -o -iname '*openclaw*.zip' -o -iname '*whatsapp*.tar' -o -iname '*whatsapp*.tar.gz' -o -iname '*whatsapp*.tgz' -o -iname '*whatsapp*.zip' -o -iname '*openclaw*backup*' -o -iname '*whatsapp*backup*' \))
done

echo '=== SYSTEMD OPENCLAW REFERENCES (REDACTED) ==='
for dir in "$(p /etc/systemd/system)" "$(p /usr/lib/systemd/system)" "$(p /lib/systemd/system)"; do
  [[ -d "$dir" ]] || continue
  set +o pipefail
  refs="$(grep -RIlE 'openclaw|whatsapp|claw' "$dir" 2>/dev/null | head -n 120 || true)"
  set -o pipefail
  while read -r f; do
    [[ -n "$f" ]] || continue
    echo "--- $f"
    grep -E '^(Description|User|Group|WorkingDirectory|ExecStart|ExecStartPre|EnvironmentFile|Restart|RestartSec)=' "$f" 2>/dev/null | redact || true
  done <<<"$refs"
done

echo '=== PACKAGE / BINARY PRESENCE ==='
for bin in docker containerd podman openclaw node npm npx; do
  f="$(p "/usr/bin/$bin")"; [[ -x "$f" ]] && echo "$bin=$f" || true
  f="$(p "/usr/local/bin/$bin")"; [[ -x "$f" ]] && echo "$bin=$f" || true
done

if [[ -x "$(p /usr/bin/dpkg-query)" ]]; then
  set +o pipefail
  chroot "$root" /usr/bin/dpkg-query -W -f='${Package}|${Status}|${Version}\n' 2>/dev/null | grep -Ei 'docker|containerd|nodejs|npm|podman' | head -n 120 || true
  set -o pipefail
fi

echo OPENCLAW_STATE_AUDIT_COMPLETE=1
