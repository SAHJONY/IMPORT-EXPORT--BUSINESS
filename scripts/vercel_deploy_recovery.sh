#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${VERCEL_PROJECT_ID:-prj_XmlR9SuaYKEE9siBC7lrsjLzYjb9}"
ORG_ID="${VERCEL_ORG_ID:-team_Me3fB0D0J6He10CgJlJ44Xaq}"
PROD_URL="${PRODUCTION_URL:-https://import-export-business.vercel.app}"

if [[ -z "${VERCEL_TOKEN:-}" ]]; then
  echo "ERROR: VERCEL_TOKEN is required. Store it as a GitHub Actions secret; never commit it."
  exit 78
fi

export VERCEL_PROJECT_ID="$PROJECT_ID"
export VERCEL_ORG_ID="$ORG_ID"

npx --yes vercel@latest pull --yes --environment=production --token="$VERCEL_TOKEN"
npx --yes vercel@latest build --prod --token="$VERCEL_TOKEN"

DEPLOY_OUTPUT="$(npx --yes vercel@latest deploy --prebuilt --prod --archive=tgz --token="$VERCEL_TOKEN")"
echo "$DEPLOY_OUTPUT"
DEPLOY_URL="$(printf '%s\n' "$DEPLOY_OUTPUT" | grep -Eo 'https://[^ ]+\.vercel\.app' | tail -1 || true)"

if [[ -z "$DEPLOY_URL" ]]; then
  echo "ERROR: Vercel CLI did not return a deployment URL."
  exit 1
fi

# Verify immutable deployment first.
for path in / /client /owner /health /voice/health; do
  code="$(curl -L -sS -o /tmp/vercel-check.out -w '%{http_code}' "${DEPLOY_URL}${path}")"
  if [[ "$code" -lt 200 || "$code" -ge 400 ]]; then
    echo "ERROR: ${DEPLOY_URL}${path} returned HTTP ${code}"
    cat /tmp/vercel-check.out || true
    exit 1
  fi
  echo "PASS ${path} -> ${code}"
done

# Production alias should follow the --prod deployment. Verify canonical URL too.
for path in / /client /owner /health /voice/health; do
  code="$(curl -L -sS -o /tmp/vercel-prod-check.out -w '%{http_code}' "${PROD_URL}${path}")"
  if [[ "$code" -lt 200 || "$code" -ge 400 ]]; then
    echo "ERROR: ${PROD_URL}${path} returned HTTP ${code}"
    cat /tmp/vercel-prod-check.out || true
    exit 1
  fi
  echo "PASS canonical ${path} -> ${code}"
done

echo "DEPLOYMENT_URL=${DEPLOY_URL}"
echo "PRODUCTION_URL=${PROD_URL}"
echo "GITHUB_SHA=${GITHUB_SHA:-unknown}"
