#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-.}"
failures=0

fail(){ printf '[hostinger-policy] FAIL: %s\n' "$*" >&2; failures=$((failures+1)); }
pass(){ printf '[hostinger-policy] PASS: %s\n' "$*"; }

shopt -s nullglob
workflows=("$ROOT"/.github/workflows/hostinger*.yml "$ROOT"/.github/workflows/hostinger*.yaml)

for f in "${workflows[@]}"; do
  base="$(basename "$f")"
  content="$(cat "$f")"

  # Retired workflows may be dispatch-only no-ops. The active controller is dispatch-only.
  if grep -Eq '^  schedule:|^  push:' "$f"; then
    if [[ "$base" == hostinger-runtime-recovery-v11.yml ]]; then
      pass "$base is the temporary one-shot runtime recovery allowlist"
    else
      fail "$base contains automatic Hostinger mutation trigger (push/schedule)"
    fi
  fi

  if grep -Eq 'cat .*sahjony-sshd\.service|tee .*sahjony-sshd\.service|systemctl .*sahjony-sshd' "$f"; then
    fail "$base may create/operate a duplicate SSH daemon"
  fi

  if grep -Eqi 'docker-manager|/docker/(containers|projects|stacks)|Docker Manager API' "$f"; then
    fail "$base depends on Hostinger Docker Manager; Kali must use normal SSH + local Docker"
  fi

  if grep -Eqi 'openclaw gateway restart' "$f"; then
    fail "$base uses application-level gateway restart as infrastructure recovery"
  fi

done

# Source scripts must never create the duplicate daemon either.
if grep -RInE --include='*.sh' 'cat .*sahjony-sshd\.service|tee .*sahjony-sshd\.service' "$ROOT/openclaw/hostinger-24x7" 2>/dev/null; then
  fail 'hostinger scripts contain duplicate sahjony-sshd.service creation logic'
fi

# Canonical invariants must exist.
[[ -f "$ROOT/openclaw/hostinger-24x7/hostinger-recovery-controller.sh" ]] || fail 'recovery controller missing'
[[ -f "$ROOT/openclaw/hostinger-24x7/hostinger-runtime-bootstrap.sh" ]] || fail 'runtime bootstrap missing'
[[ -f "$ROOT/openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh" ]] || fail 'Hostinger-only guardian missing'
[[ -f "$ROOT/openclaw/skills/hostinger-recovery-controller/SKILL.md" ]] || fail 'recovery controller skill missing'

if (( failures > 0 )); then
  echo "HOSTINGER_RECOVERY_POLICY=FAIL failures=$failures" >&2
  exit 1
fi

echo HOSTINGER_RECOVERY_POLICY=PASS
