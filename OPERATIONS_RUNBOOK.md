# Production Operations Runbook

## Release rule

The business is live only when `/v2/platform/readiness` returns `production_ready=true`, `release_gate=READY`, `score=100`, and an empty blocker list. A healthy `/health` response alone is not sufficient.

## Required evidence

1. Production runtime: `/`, `/dashboard`, and `/health` all return expected 2xx responses.
2. InsForge: authenticated metadata/database connectivity verified; migration `insforge/migrations/001_trade_os.sql` applied.
3. Auth: InsForge Auth/JWT + RLS enabled for user-facing sessions. Owner/admin MFA required.
4. Screening: restricted-party screening connected to U.S. government data. Treat matches as review/blocking events; verify underlying official source before release.
5. Classification/tariffs: authoritative HTS/tariff source configured. Classification candidates require human verification before consequential release.
6. Logistics: live quote/tracking provider configured and timestamps/source retained.
7. FX: authoritative rate provider configured; source and effective timestamp retained.
8. Documents: InsForge Storage enabled; document evidence attached to cases.
9. Audit: retain trade decisions, evidence, approvals and overrides for at least 365 days.
10. Backups: database/storage backups enabled and restore procedure tested.
11. Monitoring: production errors and readiness regressions trigger owner/operations alerts.
12. E2E: complete one production-safe trade workflow from case creation through evidence, screening, costing, document pack and final governed decision. Record the evidence before setting `E2E_TRADE_WORKFLOW_VERIFIED=true`.

## Incident severity

- P0: unauthorized access, data loss, incorrect release of a blocked trade, sanctions/compliance control bypass. Disable consequential actions immediately.
- P1: production unavailable, InsForge unavailable, screening/tariff evidence unavailable. Keep release gate HOLD.
- P2: degraded non-critical market/logistics enrichment. Allow research/simulation only when compliance evidence remains valid.

## Fail-closed behavior

No AI agent may override a mandatory compliance gate. If an authoritative dependency is unavailable or evidence is stale/ambiguous, the system must return HOLD/REVIEW rather than fabricate a positive result.

## Backup and restore test

At least monthly: create a backup, restore it into an isolated environment, verify trade cases, decisions, documents and audit events, record duration and integrity results, then delete the isolated restore.

## Change management

Changes go through CI. Production promotion requires passing tests and a verified Vercel deployment. Secrets must be configured through the deployment/backend secret stores and never committed to Git.
