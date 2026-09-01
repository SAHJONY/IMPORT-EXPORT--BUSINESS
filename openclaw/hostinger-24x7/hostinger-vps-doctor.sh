#!/usr/bin/env bash
set -uo pipefail

MODE="${1:-audit}"
REPORT="${SAHJONY_VPS_DOCTOR_REPORT:-/tmp/sahjony-hostinger-vps-doctor.json}"
GUARDIAN="${SAHJONY_WHATSAPP_GUARDIAN:-/opt/sahjony-openclaw/whatsapp-hostinger-only-guardian.sh}"
EXPECTED_HOSTNAME="${SAHJONY_EXPECTED_HOSTNAME:-srv767852.hstgr.cloud}"
EXPECTED_IP="${SAHJONY_EXPECTED_IP:-69.62.68.67}"

case "$MODE" in audit|heal) ;; *) echo "usage: $0 [audit|heal]" >&2; exit 64 ;; esac

log(){ printf '[vps-doctor] %s\n' "$*" >&2; }
have(){ command -v "$1" >/dev/null 2>&1; }
bool(){ [[ "$1" == true ]] && printf true || printf false; }
json_string(){
  if have jq; then jq -Rn --arg v "$1" '$v'; else python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$1" 2>/dev/null || printf '"unknown"'; fi
}

if [[ "$(id -u)" -ne 0 ]]; then
  log 'run as root on the authorized Hostinger VPS'
  exit 77
fi

mkdir -p "$(dirname "$REPORT")" 2>/dev/null || true

hostname_now="$(hostname -f 2>/dev/null || hostname 2>/dev/null || echo unknown)"
os_pretty="$(. /etc/os-release 2>/dev/null && printf '%s' "${PRETTY_NAME:-unknown}" || echo unknown)"
uptime_s="$(cut -d. -f1 /proc/uptime 2>/dev/null || echo 0)"
loadavg="$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo unknown)"
mem_available_kb="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
root_used_pct="$(df -P / 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}' || echo 0)"
root_inode_pct="$(df -Pi / 2>/dev/null | awk 'NR==2 {gsub(/%/,"",$5); print $5}' || echo 0)"
default_route="$(ip route show default 2>/dev/null | head -n1 || true)"
primary_ip="$(ip -4 -o addr show scope global 2>/dev/null | awk '{split($4,a,"/"); print a[1]; exit}' || true)"

sshd_unit=none
sshd_active=false
sshd_enabled=false
for unit in ssh.service sshd.service; do
  if systemctl cat "$unit" >/dev/null 2>&1; then
    sshd_unit="$unit"
    systemctl is-active --quiet "$unit" && sshd_active=true || true
    systemctl is-enabled --quiet "$unit" && sshd_enabled=true || true
    break
  fi
done
sshd_config_valid=false
if have sshd && sshd -t >/tmp/sahjony-sshd-doctor.err 2>&1; then sshd_config_valid=true; fi
ssh_listener=false
if have ss && ss -ltn 2>/dev/null | awk 'NR>1 {print $4}' | grep -Eq '(^|:|\])22$'; then ssh_listener=true; fi

firewall_backend=none
firewall_suspect=false
if have nft; then
  firewall_backend=nft
  if nft list ruleset 2>/dev/null | grep -Eiq 'hook input.*policy drop|type filter hook input.*drop'; then firewall_suspect=true; fi
elif have iptables; then
  firewall_backend=iptables
  if iptables -S INPUT 2>/dev/null | head -n1 | grep -q -- '-P INPUT DROP'; then firewall_suspect=true; fi
elif have ufw; then
  firewall_backend=ufw
  if ufw status 2>/dev/null | grep -q '^Status: active' && ! ufw status 2>/dev/null | grep -Eq '(^|[[:space:]])22(/tcp)?[[:space:]]+ALLOW'; then firewall_suspect=true; fi
fi

disk_pressure=false
[[ "$root_used_pct" =~ ^[0-9]+$ && "$root_used_pct" -ge 95 ]] && disk_pressure=true
inode_pressure=false
[[ "$root_inode_pct" =~ ^[0-9]+$ && "$root_inode_pct" -ge 95 ]] && inode_pressure=true

docker_installed=false
docker_active=false
container_id=''
container_name=''
container_running=false
restart_policy=unknown
whatsapp_connected=false
probe_excerpt=''

if have docker; then
  docker_installed=true
  systemctl is-active --quiet docker && docker_active=true || true
fi

if [[ "$MODE" == heal ]]; then
  if [[ "$sshd_config_valid" == true && "$sshd_unit" != none ]]; then
    systemctl enable --now "$sshd_unit" >/dev/null 2>&1 || true
    systemctl is-active --quiet "$sshd_unit" && sshd_active=true || true
  fi
  if [[ "$docker_installed" == true ]]; then
    systemctl enable --now docker >/dev/null 2>&1 || true
    systemctl is-active --quiet docker && docker_active=true || true
  fi
fi

if [[ "$docker_active" == true ]]; then
  line="$(docker ps -a --format '{{.ID}}|{{.Names}}|{{.Image}}' 2>/dev/null | awk -F'|' 'tolower($0) ~ /openclaw|claw/ {print; exit}' || true)"
  if [[ -n "$line" ]]; then
    IFS='|' read -r container_id container_name _image <<<"$line"
    [[ "$(docker inspect "$container_id" --format '{{.State.Running}}' 2>/dev/null || true)" == true ]] && container_running=true || true
    restart_policy="$(docker inspect "$container_id" --format '{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || echo unknown)"

    if [[ "$MODE" == heal ]]; then
      docker update --restart unless-stopped "$container_id" >/dev/null 2>&1 || true
      restart_policy="$(docker inspect "$container_id" --format '{{.HostConfig.RestartPolicy.Name}}' 2>/dev/null || echo unknown)"
      if [[ "$container_running" != true ]]; then
        docker start "$container_id" >/dev/null 2>&1 || true
        sleep 8
        [[ "$(docker inspect "$container_id" --format '{{.State.Running}}' 2>/dev/null || true)" == true ]] && container_running=true || true
      fi
    fi

    if [[ "$container_running" == true ]]; then
      probe="$(docker exec "$container_id" sh -lc 'if command -v openclaw >/dev/null 2>&1; then openclaw channels status --probe; elif [ -x "$HOME/.openclaw/bin/openclaw" ]; then "$HOME/.openclaw/bin/openclaw" channels status --probe; elif [ -x /root/.openclaw/bin/openclaw ]; then /root/.openclaw/bin/openclaw channels status --probe; else echo OPENCLAW_BINARY_NOT_FOUND; exit 127; fi' 2>&1 || true)"
      probe_excerpt="$(printf '%s' "$probe" | tail -n 30 | tr '\n' ' ' | cut -c1-1800)"
      if printf '%s' "$probe" | grep -Eiq 'whatsapp.*(connected|ready|active|healthy)|(connected|ready|active|healthy).*whatsapp|linked,[[:space:]]*running,[[:space:]]*connected'; then
        whatsapp_connected=true
      fi
    fi
  fi
fi

guardian_timer=false
guardian_last_good=''
for timer in sahjony-whatsapp-hostinger.timer sahjony-whatsapp-guardian.timer; do
  if systemctl is-active --quiet "$timer" 2>/dev/null; then guardian_timer=true; break; fi
done
for f in /var/lib/sahjony-whatsapp-guardian/last-good /opt/sahjony-openclaw/hostinger-whatsapp.last-good; do
  [[ -f "$f" ]] && { guardian_last_good="$(stat -c %Y "$f" 2>/dev/null || true)"; break; }
done

if [[ "$MODE" == heal && "$whatsapp_connected" != true ]]; then
  if [[ -x "$GUARDIAN" ]]; then
    log 'delegating bounded WhatsApp recovery to existing guardian; linked session will be preserved'
    "$GUARDIAN" heal >/tmp/sahjony-guardian-heal.log 2>&1 || true
    if [[ -n "$container_id" ]]; then
      probe="$(docker exec "$container_id" sh -lc 'if command -v openclaw >/dev/null 2>&1; then openclaw channels status --probe; elif [ -x "$HOME/.openclaw/bin/openclaw" ]; then "$HOME/.openclaw/bin/openclaw" channels status --probe; elif [ -x /root/.openclaw/bin/openclaw ]; then /root/.openclaw/bin/openclaw channels status --probe; else echo OPENCLAW_BINARY_NOT_FOUND; fi' 2>&1 || true)"
      probe_excerpt="$(printf '%s' "$probe" | tail -n 30 | tr '\n' ' ' | cut -c1-1800)"
      printf '%s' "$probe" | grep -Eiq 'whatsapp.*(connected|ready|active|healthy)|(connected|ready|active|healthy).*whatsapp|linked,[[:space:]]*running,[[:space:]]*connected' && whatsapp_connected=true || true
    fi
  fi
fi

classification=ready
severity=ok
if [[ "$sshd_config_valid" != true ]]; then classification=sshd_config_invalid; severity=critical
elif [[ "$sshd_active" != true || "$ssh_listener" != true ]]; then classification=sshd_not_serving; severity=critical
elif [[ "$firewall_suspect" == true ]]; then classification=guest_firewall_suspect; severity=warning
elif [[ "$disk_pressure" == true || "$inode_pressure" == true ]]; then classification=storage_pressure; severity=critical
elif [[ "$docker_installed" != true ]]; then classification=docker_missing; severity=critical
elif [[ "$docker_active" != true ]]; then classification=docker_inactive; severity=critical
elif [[ -z "$container_id" ]]; then classification=openclaw_container_missing; severity=critical
elif [[ "$container_running" != true ]]; then classification=openclaw_container_stopped; severity=critical
elif [[ "$whatsapp_connected" != true ]]; then classification=whatsapp_channel_unhealthy; severity=critical
elif [[ "$restart_policy" != always && "$restart_policy" != unless-stopped ]]; then classification=restart_policy_weak; severity=warning
elif [[ "$guardian_timer" != true ]]; then classification=guardian_inactive; severity=warning
fi

identity_match=true
if [[ "$hostname_now" != "$EXPECTED_HOSTNAME" && "$hostname_now" != "${EXPECTED_HOSTNAME%%.*}" ]]; then identity_match=false; fi

cat >"$REPORT" <<JSON
{
  "schema_version": 1,
  "mode": $(json_string "$MODE"),
  "classification": $(json_string "$classification"),
  "severity": $(json_string "$severity"),
  "identity": {
    "hostname": $(json_string "$hostname_now"),
    "expected_hostname": $(json_string "$EXPECTED_HOSTNAME"),
    "identity_match": $(bool "$identity_match"),
    "primary_ipv4": $(json_string "$primary_ip"),
    "expected_public_ipv4": $(json_string "$EXPECTED_IP"),
    "os": $(json_string "$os_pretty")
  },
  "system": {
    "uptime_seconds": ${uptime_s:-0},
    "loadavg": $(json_string "$loadavg"),
    "mem_available_kb": ${mem_available_kb:-0},
    "root_used_percent": ${root_used_pct:-0},
    "root_inode_percent": ${root_inode_pct:-0},
    "default_route": $(json_string "$default_route")
  },
  "ssh": {
    "unit": $(json_string "$sshd_unit"),
    "active": $(bool "$sshd_active"),
    "enabled": $(bool "$sshd_enabled"),
    "config_valid": $(bool "$sshd_config_valid"),
    "listener_22": $(bool "$ssh_listener"),
    "firewall_backend": $(json_string "$firewall_backend"),
    "firewall_suspect": $(bool "$firewall_suspect")
  },
  "runtime": {
    "docker_installed": $(bool "$docker_installed"),
    "docker_active": $(bool "$docker_active"),
    "openclaw_container_id": $(json_string "$container_id"),
    "openclaw_container_name": $(json_string "$container_name"),
    "openclaw_container_running": $(bool "$container_running"),
    "restart_policy": $(json_string "$restart_policy"),
    "whatsapp_connected": $(bool "$whatsapp_connected"),
    "guardian_timer": $(bool "$guardian_timer"),
    "guardian_last_good_epoch": $(json_string "$guardian_last_good"),
    "probe_excerpt": $(json_string "$probe_excerpt")
  },
  "safety": {
    "meta_required": false,
    "whatsapp_session_repaired": false,
    "container_recreated": false,
    "firewall_mutated": false
  }
}
JSON

cat "$REPORT"
printf 'SAHJONY_VPS_DOCTOR_CLASSIFICATION=%s\n' "$classification" >&2
printf 'SAHJONY_VPS_DOCTOR_SEVERITY=%s\n' "$severity" >&2

# Audit always returns evidence. Heal fails only when a critical gate remains unresolved.
if [[ "$MODE" == heal && "$severity" == critical ]]; then exit 2; fi
exit 0
