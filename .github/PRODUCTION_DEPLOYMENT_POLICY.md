# Production Deployment Policy

Canonical production source: `main`.

Rules:
- Production deployments must originate from the latest tested commit on `main`.
- Feature branches and pull-request previews are non-production and must not be promoted directly.
- A feature branch must be merged into `main` before production promotion.
- Production health must be verified after deployment before declaring success.
- Runtime secrets remain in the deployment secret store and must never be committed to Git.
- If production and `main` drift, restore `main` as the canonical source before advancing further feature work.

Deployment source-of-record marker: canonical `main` deployment retriggered on 2026-09-04 after feature-branch production drift was detected.

This policy exists to prevent stale preview SHAs from becoming the production source of record.
