#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/IMPORT-EXPORT--BUSINESS"
cd "$ROOT"

echo "=== Sync main ==="
git pull --ff-only origin main

echo "=== Deploy Production ==="
vercel --prod --yes

echo "=== Wait for Business OS executor 1.1.0 ==="
BASE="https://www.sahjony.com"
for i in $(seq 1 30); do
  health="$(curl -fsS --max-time 15 "$BASE/email-agent/business-os/executor/health" 2>/dev/null || true)"
  if printf '%s' "$health" | python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("version")=="1.1.0" and d.get("status")=="ok" and d.get("durable_department_evidence") is True else 1)' 2>/dev/null; then
    echo "$health" | python3 -m json.tool
    echo "BUSINESS_OS_EXECUTOR_PRODUCTION_READY=1"
    exit 0
  fi
  echo "Waiting for executor 1.1.0... attempt $i/30"
  sleep 10
done

echo "ERROR: Production did not expose Business OS executor 1.1.0 within 5 minutes." >&2
curl -sS "$BASE/email-agent/business-os/health" || true
echo
exit 1
