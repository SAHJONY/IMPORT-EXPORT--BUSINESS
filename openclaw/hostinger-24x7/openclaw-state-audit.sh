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
  find "$base" -xdev -maxdepth 7 -type f \
    \( -iname '*openclaw*.sh' -o -iname '*openclaw*.service' -o -iname '*openclaw*.env' -o -name 'docker-compose.yml' -o -name 'compose.yml' -o -name 'compose.yaml' \) \
    -print 2>/dev/null | sort -u | head -n 240 | while read -r f; do
      safe_stat "$f"
      hash_file "$f"
    done
done

echo '=== OPENCLAW DEPLOY SCRIPT STRUCTURE (REDACTED) ==='
for f in "$(p /root/openclaw-deploy.sh)" "$(p /opt/openclaw-deploy.sh)" "$(p /srv/openclaw-deploy.sh)"; do
  [[ -f "$f" ]] || continue
  echo "--- $f"
  # Only structural lines; environment/credential content is redacted.
  grep -nEi 'docker|compose|openclaw|whatsapp|node|npm|systemctl|mkdir|install|volume|mount|restart|image|container' "$f" 2>/dev/null \
    | head -n 260 | redact || true
done

echo '=== COMPOSE STRUCTURE (NO ENV VALUES) ==='
for base in "$(p /root)" "$(p /opt)" "$(p /srv)"; do
  [[ -d "$base" ]] || continue
  find "$base" -xdev -maxdepth 7 -type f \( -name 'docker-compose.yml' -o -name 'compose.yml' -o -name 'compose.yaml' \) -print 2>/dev/null \
    | sort -u | head -n 160 | while read -r f; do
      if grep -Eqi 'openclaw|whatsapp|claw' "$f"; then
        echo "--- $f"
        grep -nE '^[[:space:]]*(image:|container_name:|restart:|volumes:|ports:|network_mode:|working_dir:|command:|entrypoint:|env_file:|-[[:space:]]+[^=]+:[^=]+)' "$f" 2>/dev/null \
          | head -n 220 | redact || true
      fi
    done
done

echo '=== WHATSAPP / SESSION CANDIDATE FILE METADATA ONLY ==='
for base in "$(p /root)" "$(p /opt)" "$(p /srv)" "$(p /var/lib)"; do
  [[ -d "$base" ]] || continue
  find "$base" -xdev -maxdepth 9 -type f \
    \( -iname '*whatsapp*' -o -iname '*baileys*' -o -iname 'creds.json' -o -iname '*session*.json' -o -iname '*auth*.json' -o -iname '*device*.json' \) \
    -print 2>/dev/null | sort -u | head -n 320 | while read -r f; do
      safe_stat "$f"
      hash_file "$f"
    done
done

echo '=== OPENCLAW / WHATSAPP BACKUP CANDIDATES ==='
for base in "$(p /root)" "$(p /opt)" "$(p /srv)" "$(p /var/backups)"; do
  [[ -d "$base" ]] || continue
  find "$base" -xdev -maxdepth 8 -type f \
    \( -iname '*openclaw*.tar' -o -iname '*openclaw*.tar.gz' -o -iname '*openclaw*.tgz' -o -iname '*openclaw*.zip' -o -iname '*whatsapp*.tar' -o -iname '*whatsapp*.tar.gz' -o -iname '*whatsapp*.tgz' -o -iname '*whatsapp*.zip' -o -iname '*openclaw*backup*' -o -iname '*whatsapp*backup*' \) \
    -print 2>/dev/null | sort -u | head -n 240 | while read -r f; do
      safe_stat "$f"
      hash_file "$f"
    done
done

echo '=== SYSTEMD OPENCLAW REFERENCES (REDACTED) ==='
for dir in "$(p /etc/systemd/system)" "$(p /usr/lib/systemd/system)" "$(p /lib/systemd/system)"; do
  [[ -d "$dir" ]] || continue
  grep -RIlE 'openclaw|whatsapp|claw' "$dir" 2>/dev/null | head -n 120 | while read -r f; do
    echo "--- $f"
    grep -E '^(Description|User|Group|WorkingDirectory|ExecStart|ExecStartPre|EnvironmentFile|Restart|RestartSec)=' "$f" 2>/dev/null | redact || true
  done
done

echo '=== PACKAGE / BINARY PRESENCE ==='
for bin in docker containerd podman openclaw node npm npx; do
  f="$(p "/usr/bin/$bin")"; [[ -x "$f" ]] && echo "$bin=$f" || true
  f="$(p "/usr/local/bin/$bin")"; [[ -x "$f" ]] && echo "$bin=$f" || true
done

if [[ -x "$(p /usr/bin/dpkg-query)" ]]; then
  chroot "$root" /usr/bin/dpkg-query -W -f='${Package}|${Status}|${Version}\n' 2>/dev/null \
    | grep -Ei 'docker|containerd|nodejs|npm|podman' | head -n 120 || true
fi

echo OPENCLAW_STATE_AUDIT_COMPLETE=1
