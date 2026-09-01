#!/usr/bin/env bash
set -u -o pipefail

# Read-only lineage audit for the real WhatsApp runtime.
# Designed for Hostinger Recovery with ROOT_PREFIX=/mnt/sdb1.
ROOT_PREFIX="${ROOT_PREFIX:-/}"
root="${ROOT_PREFIX%/}"; [[ -n "$root" ]] || root=/

p(){ if [[ "$root" == / ]]; then printf '/%s' "${1#/}"; else printf '%s/%s' "$root" "${1#/}"; fi; }
redact(){
  sed -E \
    -e 's/((token|secret|password|pass|api[_-]?key|private[_-]?key|access[_-]?token|authorization|cookie)[A-Za-z0-9_-]*[[:space:]]*[:=][[:space:]]*)([^[:space:]]+)/\1<redacted>/Ig' \
    -e 's/(Bearer[[:space:]]+)[A-Za-z0-9._~+\/-]+/\1<redacted>/Ig' \
    -e 's#(https?://)[^/@[:space:]]+:[^/@[:space:]]+@#\1<redacted>@#g' \
    -e 's/[A-Za-z0-9+\/_=-]{48,}/<redacted-long-value>/g'
}
stat_safe(){ stat -c '%n|type=%F|size=%s|mtime=%y|mode=%a|uid=%u|gid=%g' "$1" 2>/dev/null || true; }
section(){ printf '\n=== %s ===\n' "$1"; }

section 'ROOT'
echo "ROOT_PREFIX=$root"
grep -E '^(PRETTY_NAME|VERSION|VERSION_ID)=' "$(p /etc/os-release)" 2>/dev/null || true

section 'CANONICAL STATE DIRECTORIES'
for d in /root/.hermes /root/.openclaw /root/.config/openclaw /root/.config/hermes /var/lib/openclaw /var/lib/docker /var/lib/containerd /opt/openclaw /opt/hermes /srv/openclaw /srv/hermes; do
  f="$(p "$d")"
  [[ -e "$f" ]] || continue
  stat_safe "$f"
  [[ -d "$f" ]] && echo "$f|entries_depth3=$(find "$f" -mindepth 1 -maxdepth 3 -print 2>/dev/null | wc -l | tr -d ' ')"
done

section 'HERMES / OPENCLAW CONFIG METADATA'
for base in "$(p /root/.hermes)" "$(p /root/.openclaw)" "$(p /root/.config)" "$(p /etc)" "$(p /opt)" "$(p /srv)"; do
  [[ -d "$base" ]] || continue
  find "$base" -xdev -maxdepth 7 -type f \
    \( -iname '*whatsapp*' -o -iname '*openclaw*' -o -iname '*hermes*' -o -name 'creds.json' -o -name 'config.json' -o -name 'settings.json' -o -name 'auth.json' \) \
    ! -path '*/node_modules/*' ! -path '*/.cache/*' ! -path '*/sessions/session_*' \
    -print 2>/dev/null | sort -u | head -n 240 | while read -r f; do
      stat_safe "$f"
      [[ -f "$f" ]] && echo "$f|sha256=$(sha256sum "$f" 2>/dev/null | awk '{print $1}')"
    done
done

section 'SAFE JSON KEY PATHS'
# Print schema/key names only, never values. Limit to small likely config/auth files.
for f in \
  "$(p /root/.hermes/auth.json)" \
  "$(p /root/.hermes/config.json)" \
  "$(p /root/.hermes/settings.json)" \
  "$(p /root/.openclaw/config.json)" \
  "$(p /root/.openclaw/creds.json)"; do
  [[ -f "$f" ]] || continue
  size="$(stat -c %s "$f" 2>/dev/null || echo 9999999)"
  (( size <= 262144 )) || { echo "$f|schema_skipped=size_$size"; continue; }
  echo "--- $f"
  if command -v jq >/dev/null 2>&1; then
    jq -r 'paths(scalars) | map(tostring) | join(".")' "$f" 2>/dev/null | sort -u | head -n 160 | redact || echo schema_unavailable
  else
    echo jq_unavailable
  fi
done

section 'WHATSAPP AUTH DIRECTORY CANDIDATES'
for base in "$(p /root/.hermes)" "$(p /root/.openclaw)" "$(p /root/.config)" "$(p /var/lib)"; do
  [[ -d "$base" ]] || continue
  find "$base" -xdev -maxdepth 8 \
    \( -type d \( -iname '*whatsapp*' -o -iname '*baileys*' -o -iname '*auth*state*' -o -iname '*linked*device*' \) \
       -o -type f \( -name 'creds.json' -o -iname '*whatsapp*.json' -o -iname '*baileys*.json' \) \) \
    ! -path '*/node_modules/*' ! -path '*/.cache/*' -print 2>/dev/null | sort -u | head -n 240 | while read -r f; do stat_safe "$f"; done
done

section 'SYSTEMD UNIT DEFINITIONS'
for dir in "$(p /etc/systemd/system)" "$(p /usr/lib/systemd/system)" "$(p /lib/systemd/system)"; do
  [[ -d "$dir" ]] || continue
  { grep -RIlE --include='*.service' --include='*.timer' --include='*.socket' 'openclaw|hermes|whatsapp|claw' "$dir" 2>/dev/null || true; } \
    | sort -u | head -n 160 | while read -r f; do
        echo "--- $f"
        { grep -E '^(Description|User|Group|WorkingDirectory|ExecStart|ExecStartPre|ExecStartPost|EnvironmentFile|Restart|RestartSec|WantedBy|OnBootSec|OnUnitActiveSec)=' "$f" 2>/dev/null || true; } | redact
      done
done

section 'SYSTEMD ENABLEMENT LINKS'
find "$(p /etc/systemd/system)" -maxdepth 4 -type l -printf '%p -> %l\n' 2>/dev/null \
  | grep -Ei 'openclaw|hermes|whatsapp|claw|docker|containerd' | head -n 180 | redact || true

section 'CRON / RC LOCAL REFERENCES'
for f in "$(p /etc/crontab)" "$(p /etc/rc.local)"; do
  [[ -f "$f" ]] || continue
  echo "--- $f"
  { grep -nEi 'openclaw|hermes|whatsapp|claw|docker|containerd' "$f" 2>/dev/null || true; } | redact
done
for dir in "$(p /etc/cron.d)" "$(p /etc/cron.hourly)" "$(p /etc/cron.daily)"; do
  [[ -d "$dir" ]] || continue
  { grep -RInE 'openclaw|hermes|whatsapp|claw' "$dir" 2>/dev/null || true; } | head -n 100 | redact
done

section 'INSTALLED BINARIES'
for path in /usr/bin/docker /usr/bin/containerd /usr/bin/node /usr/bin/npm /usr/bin/python3 /usr/local/bin/openclaw /usr/bin/openclaw /usr/local/bin/hermes /usr/bin/hermes; do
  f="$(p "$path")"; [[ -e "$f" ]] && stat_safe "$f"
done

section 'PACKAGE STATE'
if [[ "$root" != / && -x "$(p /usr/bin/dpkg-query)" ]]; then
  chroot "$root" /usr/bin/dpkg-query -W -f='${Package}|${Status}|${Version}\n' 2>/dev/null \
    | grep -Ei '^(docker|docker.io|containerd|nodejs|npm|podman|python3)' | head -n 120 || true
fi

section 'RECENT BOOT LIST'
jdir="$(p /var/log/journal)"
if [[ -d "$jdir" ]]; then
  journalctl --directory="$jdir" --list-boots --no-pager 2>/dev/null | tail -n 12 || true
fi

section 'PREVIOUS BOOT RUNTIME LIFECYCLE'
if [[ -d "$jdir" ]]; then
  # Lifecycle-only messages; sensitive-looking long values are redacted.
  for boot in -1 -2; do
    echo "--- boot=$boot"
    { journalctl --directory="$jdir" -b "$boot" --no-pager -o short-iso 2>/dev/null || true; } \
      | grep -Ei 'openclaw|hermes|whatsapp|docker\.service|containerd\.service|docker daemon|containerd|gateway|sahjony-whatsapp' \
      | grep -Ei 'start|stop|active|inactive|failed|failure|ready|connected|disconnect|listening|launch|exec|service|timer|gateway|channel|whatsapp|docker|containerd' \
      | tail -n 500 | redact || true
  done
fi

section 'UNIT-SCOPED PREVIOUS BOOT LOGS'
if [[ -d "$jdir" ]]; then
  # Identify candidate units from journal metadata, then print only unit names/counts.
  for boot in -1 -2; do
    echo "--- boot=$boot units"
    { journalctl --directory="$jdir" -b "$boot" -o json --no-pager 2>/dev/null || true; } \
      | jq -r 'select(((._SYSTEMD_UNIT // "")|test("openclaw|hermes|whatsapp|docker|containerd";"i")) or ((.SYSLOG_IDENTIFIER // "")|test("openclaw|hermes|whatsapp|docker|containerd";"i"))) | [._SYSTEMD_UNIT // "-", .SYSLOG_IDENTIFIER // "-"] | @tsv' 2>/dev/null \
      | sort | uniq -c | sort -nr | head -n 100 || true
  done
fi

section 'DOCKER CURRENT METADATA AGE'
for d in "$(p /var/lib/docker)" "$(p /var/lib/containerd)"; do [[ -e "$d" ]] && stat_safe "$d"; done

section 'AUDIT RESULT'
echo HOSTINGER_RUNTIME_LINEAGE_AUDIT_COMPLETE=1
exit 0
