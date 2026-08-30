#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${VERCEL_PROJECT_ID:-prj_XmlR9SuaYKEE9siBC7lrsjLzYjb9}"
ORG_ID="${VERCEL_ORG_ID:-team_Me3fB0D0J6He10CgJlJ44Xaq}"
PROD_URL="${PRODUCTION_URL:-https://www.sahjony.com}"
VERCEL_CLI_VERSION="${VERCEL_CLI_VERSION:-59.3.0}"
MODE="${1:-deploy}"

if [[ "$MODE" != "deploy" && "$MODE" != "--check" ]]; then
  echo "Usage: $0 [deploy|--check]"
  exit 64
fi

for required_file in package.json vercel.json; do
  if [[ ! -f "$required_file" ]]; then
    echo "ERROR: required file missing: $required_file"
    exit 66
  fi
done

if [[ -n "${GITHUB_REF_NAME:-}" && "$GITHUB_REF_NAME" != "main" ]]; then
  echo "ERROR: production recovery is restricted to the main branch."
  exit 77
fi

if [[ "$MODE" == "--check" ]]; then
  echo "PASS recovery configuration"
  echo "VERCEL_PROJECT_ID=$PROJECT_ID"
  echo "VERCEL_ORG_ID=$ORG_ID"
  echo "PRODUCTION_URL=$PROD_URL"
  echo "VERCEL_CLI_VERSION=$VERCEL_CLI_VERSION"
  exit 0
fi

if [[ -z "${VERCEL_TOKEN:-}" ]]; then
  echo "ERROR: VERCEL_TOKEN is required. Store it as a GitHub Actions secret; never commit it."
  exit 78
fi

export VERCEL_PROJECT_ID="$PROJECT_ID"
export VERCEL_ORG_ID="$ORG_ID"

npx --yes "vercel@${VERCEL_CLI_VERSION}" pull --yes --environment=production --token="$VERCEL_TOKEN"
npx --yes "vercel@${VERCEL_CLI_VERSION}" build --prod --token="$VERCEL_TOKEN"

if ! DEPLOY_OUTPUT="$(npx --yes "vercel@${VERCEL_CLI_VERSION}" deploy --prebuilt --archive=tgz --token="$VERCEL_TOKEN" 2>&1)"; then
  echo "$DEPLOY_OUTPUT"
  exit 1
fi
echo "$DEPLOY_OUTPUT"
DEPLOY_URL="$(printf '%s\n' "$DEPLOY_OUTPUT" | grep -Eo 'https://[^ ]+\.vercel\.app' | tail -1 || true)"

if [[ -z "$DEPLOY_URL" ]]; then
  echo "ERROR: Vercel CLI did not return a deployment URL."
  exit 1
fi

# Verify immutable deployment first.
for path in / /supabase-login.html /health; do
  code="$(curl -L -sS -o /tmp/vercel-check.out -w '%{http_code}' "${DEPLOY_URL}${path}")"
  if [[ "$code" -lt 200 || "$code" -ge 400 ]]; then
    echo "ERROR: ${DEPLOY_URL}${path} returned HTTP ${code}"
    cat /tmp/vercel-check.out || true
    exit 1
  fi
  echo "PASS ${path} -> ${code}"
done

npx --yes "vercel@${VERCEL_CLI_VERSION}" promote "$DEPLOY_URL" --yes --token="$VERCEL_TOKEN"

# Verify the production alias only after the immutable deployment passes.
for path in / /supabase-login.html /health; do
  code="$(curl -L -sS -o /tmp/vercel-prod-check.out -w '%{http_code}' "${PROD_URL}${path}")"
  if [[ "$code" -lt 200 || "$code" -ge 400 ]]; then
    echo "ERROR: ${PROD_URL}${path} returned HTTP ${code}"
    cat /tmp/vercel-prod-check.out || true
    exit 1
  fi
  echo "PASS canonical ${path} -> ${code}"
done

if ! curl -LfsS "${PROD_URL}/supabase-login.html" | grep -Fq '/global-language.js'; then
  echo "ERROR: production Supabase login is missing the global language runtime."
  exit 1
fi
echo "PASS canonical language runtime"

echo "DEPLOYMENT_URL=${DEPLOY_URL}"
echo "PRODUCTION_URL=${PROD_URL}"
echo "GITHUB_SHA=${GITHUB_SHA:-unknown}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "deployment_url=${DEPLOY_URL}" >> "$GITHUB_OUTPUT"
fi

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "## Vercel production deployment"
    echo "- Deployment: ${DEPLOY_URL}"
    echo "- Production: ${PROD_URL}"
    echo "- Commit: ${GITHUB_SHA:-unknown}"
    echo "- Smoke tests: passed"
  } >> "$GITHUB_STEP_SUMMARY"
fi
