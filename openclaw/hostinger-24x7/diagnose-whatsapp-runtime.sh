#!/usr/bin/env bash
set -euo pipefail
# diagnostics/final-repair trigger: 2026-09-02T19:09Z

STATE=/var/lib/sahjony-openclaw-state
CONFIG="$STATE/openclaw.json"

redact() {
  sed -E \
    -e 's/(nvapi-[A-Za-z0-9._-]+)/[REDACTED_NVIDIA_KEY]/g' \
    -e 's/(sk-[A-Za-z0-9._-]+)/[REDACTED_API_KEY]/g' \
    -e 's/([Tt]oken[=: ]+)[^ ,;]+/\1[REDACTED]/g' \
    -e 's/([Pp]assword[=: ]+)[^ ,;]+/\1[REDACTED]/g' \
    -e 's/(Authorization: Bearer )[A-Za-z0-9._-]+/\1[REDACTED]/g'
}

echo '=== CANONICAL OPENCLAW ==='
python3 - "$CONFIG" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p,encoding='utf-8'))
    print('config='+p)
    print('primary='+str((((d.get('agents') or {}).get('defaults') or {}).get('model') or {}).get('primary')))
    print('fallbacks='+str((((d.get('agents') or {}).get('defaults') or {}).get('model') or {}).get('fallbacks')))
except Exception as e:
    print('config_error='+type(e).__name__+':'+str(e))
PY
systemctl is-active openclaw-gateway.service || true
systemctl show openclaw-gateway.service -p MainPID -p FragmentPath -p DropInPaths --no-pager | redact

echo '=== POSSIBLE HEALTH REPORTERS ==='
systemctl list-units --all --type=service --no-legend --no-pager | grep -Ei 'openclaw|sahjony|sidecar|health' | redact || true
systemctl list-timers --all --no-legend --no-pager | grep -Ei 'openclaw|sahjony|sidecar|health' | redact || true
ps -eo pid,ppid,lstart,args | grep -Ei 'health-sidecar|sahjony.*health|openclaw.*heartbeat' | grep -v grep | redact || true

for root in /etc/systemd/system /usr/local /opt /var/lib/sahjony-openclaw-state /root /home/node; do
  [[ -e "$root" ]] || continue
  find "$root" -maxdepth 5 -type f \( -name '*health*sidecar*' -o -name 'health-sidecar.py' -o -name '*openclaw*health*' \) -print 2>/dev/null | head -n 100
done

echo '=== UNIT CONTENT REFERENCES ==='
grep -RIlE 'health-sidecar\.py|SAHJONY_REASONING_MODEL|/whatsapp/openclaw/heartbeat' /etc/systemd/system /usr/local /opt /var/lib/sahjony-openclaw-state 2>/dev/null | head -n 100 || true

echo '=== RECENT GATEWAY ERRORS (SANITIZED) ==='
journalctl -u openclaw-gateway.service --since '3 hours ago' --no-pager -o short-iso 2>/dev/null \
  | grep -Ei 'error|failed|failure|exception|timeout|provider|nvidia|gpt-oss|something went wrong|session|context|reply rescue|output guard' \
  | tail -n 300 \
  | redact || true

echo '=== RECENT SIDECAR/SAHJONY ERRORS (SANITIZED) ==='
for unit in $(systemctl list-units --all --type=service --no-legend --no-pager | awk '{print $1}' | grep -Ei 'sahjony|sidecar|health' || true); do
  echo "--- unit=$unit ---"
  journalctl -u "$unit" --since '3 hours ago' --no-pager -o short-iso 2>/dev/null \
    | grep -Ei 'error|failed|failure|exception|timeout|heartbeat|model|openclaw' \
    | tail -n 120 \
    | redact || true
done
