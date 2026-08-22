---
name: sahjony-deployment-doctor
description: Diagnose and prevent blank screens, missing frontend imports, Vercel route collisions, stale production artifacts, broken static aliases, and common deployment failures for SAHJONY Global Trade.
---

# SAHJONY Deployment Doctor

Use this skill whenever production shows a blank page, `{\"detail\":\"Not Found\"}`, a Vite/Rollup build failure, a route serves the wrong application, or Vercel appears to be building a stale commit.

## Mandatory triage order

1. Identify the exact Git commit Vercel is building. Never debug an obsolete deployment as if it were current `main`.
2. Run `npm run doctor` before any deployment attempt.
3. Run `npm run build`; do not push a deployment-triggering commit if the local/CI build is red.
4. Inspect `vercel.json` route order. Exact public routes must appear before broad API matchers that can consume them.
5. For blank screens, preserve visible static HTML and a React error boundary. Browser storage access must be fail-safe.
6. For production verification, run `node tools/deployment-guard.mjs --url=https://import-export-business.vercel.app`.
7. A production route is not considered fixed until the live smoke test returns expected HTML/JSON and does not return `detail: Not Found`.

## Errors this skill prevents

### Missing relative frontend import

Example:

`Could not resolve \"./workflow.css\" from \"src/main.tsx\"`

The Deployment Doctor recursively scans relative imports under `src/` and fails before Vite/Vercel when the referenced file does not exist.

### Vercel route collision

Example:

`/cuba-private-sector` being swallowed by `/cuba(.*)`.

The guard checks the critical public route ordering and rejects the configuration when the exact Cuba public route appears after the broad Cuba API matcher.

### Blank public page

The live smoke mode requires public routes to return substantial HTML. A 200 response with an empty or near-empty body is a failure.

### Backend Not Found masquerading as a page

The smoke test treats `{"detail":"Not Found"}` as a route-collision failure even when the request reaches a healthy FastAPI function.

### Stale deployment

Always compare the Vercel deployment commit SHA with GitHub `main`. If they differ, label the live environment stale and do not claim the source fix is deployed.

## Safe deployment pattern

Prefer one repair branch and one merge instead of many tiny commits to `main`. This reduces Vercel build-rate pressure.

For significant repairs:

1. Create a repair branch.
2. Make all related fixes there.
3. Let Deployment Doctor CI run.
4. Merge only after the guard and Vite build pass.
5. Verify production routes after Vercel reports READY.

Never bypass security, authentication, compliance, or release controls. This skill only bypasses avoidable deployment failure modes by detecting them earlier and routing around namespace collisions safely.
