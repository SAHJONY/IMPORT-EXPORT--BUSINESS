#!/usr/bin/env bash
set -euo pipefail

STATE_DIR="${SAHJONY_GUARDIAN_STATE_DIR:-/var/lib/sahjony-openclaw-guardian}"
LOG="${SAHJONY_GUARDIAN_LOG:-/var/log/sahjony-openclaw-guardian.log}"
INTERVAL="${SAHJONY_GUARDIAN_INTERVAL:-30}"
FAIL_THRESHOLD="${SAHJONY_GUARDIAN_FAIL_THRESHOLD:-3}"
COOLDOWN="${SAHJONY_GUARDIAN_RESTART_COOLDOWN:-45}"
PORT="${OPENCLAW_PORT:-18789}"
NATIVE_HOME="${OPENCLAW_NATIVE_HOME:-/home/node}"
NATIVE_STATE_DIR="${OPENCLAW_NATIVE_STATE_DIR:-/var/lib/sahjony-openclaw-state}"
NATIVE_CONFIG_PATH="${OPENCLAW_NATIVE_CONFIG_PATH:-${NATIVE_STATE_DIR}/openclaw.json}"

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
touch "$LOG"
chmod 600 "$LOG"

log(){ printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG"; }
now_epoch(){ date +%s; }

find_container(){
  command -v docker >/dev/null 2>&1 || return 1
  docker ps -aq 2>/dev/null | while read -r id; do
    [[ -n "$id" ]] || continue
    meta="$(docker inspect "$id" --format '{{.Name}}|{{.Config.Image}}' 2>/dev/null || true)"
    if grep -Eqi 'openclaw|open[-_ ]?claw|claw' <<<"$meta"; then
      printf '%s\n' "$id"
      return 0
    fi
  done
}

native_present(){
  command -v openclaw >/dev/null 2>&1 || return 1
  systemctl cat openclaw-gateway.service >/dev/null 2>&1 || return 1
}

runtime_mode(){
  # Once a native service is installed it is the sole lifecycle owner.
  # Never resurrect the Docker standby merely because systemd is transiently down.
  if native_present; then
    printf native
    return 0
  fi
  local cid
  cid="$(find_container | head -n1 || true)"
  if [[ -n "$cid" ]]; then
    printf docker
    return 0
  fi
  printf none
}

oc_native(){
  env HOME="$NATIVE_HOME" \
      OPENCLAW_HOME="$NATIVE_HOME" \
      OPENCLAW_STATE_DIR="$NATIVE_STATE_DIR" \
      OPENCLAW_CONFIG_PATH="$NATIVE_CONFIG_PATH" \
      openclaw "$@"
}

healthy_native(){
  systemctl is-active --quiet openclaw-gateway.service || return 1
  oc_native gateway status --deep >/dev/null 2>&1 && return 0
  curl -fsS --connect-timeout 3 --max-time 5 "http://127.0.0.1:${PORT}/" >/dev/null 2>&1
}

healthy_docker(){
  local cid="$1"
  [[ -n "$cid" ]] || return 1
  [[ "$(docker inspect "$cid" --format '{{.State.Running}}' 2>/dev/null || true)" == true ]] || return 1
  docker exec "$cid" sh -lc 'openclaw gateway status --deep >/dev/null 2>&1' && return 0
  local health
  health="$(docker inspect "$cid" --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' 2>/dev/null || true)"
  [[ -n "$health" && "$health" == healthy ]]
}

repair_native(){
  systemctl reset-failed openclaw-gateway.service >/dev/null 2>&1 || true
  systemctl restart openclaw-gateway.service
}

repair_docker(){
  local cid="$1"
  systemctl start docker.service >/dev/null 2>&1 || true
  docker update --restart unless-stopped "$cid" >/dev/null 2>&1 || true
  if [[ "$(docker inspect "$cid" --format '{{.State.Running}}' 2>/dev/null || true)" == true ]]; then
    docker restart "$cid" >/dev/null
  else
    docker start "$cid" >/dev/null
  fi
}

write_status(){
  local mode="$1" healthy="$2" failures="$3" repairs="$4" detail="$5"
  MODE="$mode" HEALTHY="$healthy" FAILURES="$failures" REPAIRS="$repairs" DETAIL="$detail" python3 - <<'PY' > "$STATE_DIR/status.json.tmp"
import datetime, json, os
print(json.dumps({
  "status": "ready" if os.environ["HEALTHY"] == "true" else "degraded",
  "runtime": os.environ["MODE"],
  "healthy": os.environ["HEALTHY"] == "true",
  "consecutive_failures": int(os.environ["FAILURES"]),
  "repair_count": int(os.environ["REPAIRS"]),
  "detail": os.environ["DETAIL"],
  "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, separators=(",", ":")))
PY
  mv "$STATE_DIR/status.json.tmp" "$STATE_DIR/status.json"
  chmod 600 "$STATE_DIR/status.json"
}

failures=0
repairs=0
last_repair=0
log "SAHJONY_RUNTIME_GUARDIAN=START interval=${INTERVAL}s threshold=$FAIL_THRESHOLD cooldown=${COOLDOWN}s"

while true; do
  mode="$(runtime_mode)"
  ok=false
  detail=""
  cid=""

  case "$mode" in
    native)
      if healthy_native; then ok=true; detail="native_gateway_healthy"; else detail="native_gateway_unhealthy"; fi
      ;;
    docker)
      cid="$(find_container | head -n1 || true)"
      if healthy_docker "$cid"; then ok=true; detail="docker_gateway_healthy"; else detail="docker_gateway_unhealthy"; fi
      ;;
    *) detail="openclaw_runtime_not_found" ;;
  esac

  if [[ "$ok" == true ]]; then
    failures=0
    write_status "$mode" true "$failures" "$repairs" "$detail"
  else
    failures=$((failures + 1))
    write_status "$mode" false "$failures" "$repairs" "$detail"
    log "SAHJONY_RUNTIME_GUARDIAN=DEGRADED runtime=$mode failures=$failures detail=$detail"

    if (( failures >= FAIL_THRESHOLD )); then
      now="$(now_epoch)"
      if (( now - last_repair >= COOLDOWN )); then
        case "$mode" in
          native) repair_native || true ;;
          docker) [[ -n "$cid" ]] && repair_docker "$cid" || true ;;
          *) systemctl start docker.service >/dev/null 2>&1 || true ;;
        esac
        repairs=$((repairs + 1))
        last_repair="$now"
        failures=0
        log "SAHJONY_RUNTIME_GUARDIAN=REPAIR runtime=$mode repair_count=$repairs"
      fi
    fi
  fi

  sleep "$INTERVAL"
done
