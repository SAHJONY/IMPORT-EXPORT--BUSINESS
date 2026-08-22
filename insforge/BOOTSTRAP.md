# InsForge Production Bootstrap

This application treats InsForge as the production backend for persistent trade data, auth, storage, realtime, functions and AI gateway. The legacy SQLite layer is compatibility-only and must not be treated as durable production storage.

## 1. Link the project

Use the official InsForge CLI from a trusted workstation or CI environment:

```bash
npx @insforge/cli link
npx @insforge/cli current
```

For non-interactive CI, use InsForge-supported environment authentication and project/org IDs. Never commit credentials to Git.

## 2. Apply the trade schema

```bash
npx @insforge/cli db import insforge/migrations/001_trade_os.sql
```

Then inspect the actual backend state:

```bash
npx @insforge/cli db tables
npx @insforge/cli db indexes
npx @insforge/cli db policies
npx @insforge/cli diagnose
```

## 3. Required server-side variables

Configure these in the deployment environment, never in browser code:

- `INSFORGE_BASE_URL=https://<project>.insforge.app`
- `INSFORGE_API_KEY=<server/admin token>`
- `OWNER_TOKEN=<long random owner token>`

Optional browser applications should use an InsForge anon/public key plus user JWTs and RLS. The admin key must remain server-only.

## 4. Connectivity verification

The server adapter verifies authenticated InsForge connectivity through:

```text
GET {INSFORGE_BASE_URL}/api/metadata
Authorization: Bearer {INSFORGE_API_KEY}
```

Do not mark the platform production-ready merely because variables exist. A successful authenticated metadata response is required.

## 5. Production migration policy

1. Create/clone an InsForge backend branch.
2. Apply migrations to the branch first.
3. Run schema inspection and diagnostics.
4. Exercise trade-case persistence and compliance release gates.
5. Merge backend branch only after tests pass.
6. Keep deterministic compliance controls outside generative-model authority.

## 6. Target InsForge services

- Postgres + PostgREST: trade cases, counterparties, shipments, decisions and audit events.
- Auth: owner/admin/user identity and sessions.
- Storage: invoices, packing lists, certificates, bills of lading and evidence.
- Realtime: shipment, customs and exception events.
- Edge Functions: trusted integrations and webhook processing.
- Cron Jobs: recurring risk, ETA, sanctions and stale-case checks.
- AI Gateway: governed model routing for research, document extraction and executive copilot workloads.
- Vector: semantic retrieval across documents, supplier evidence and historical cases.

## Release gate

`production_ready` must remain false until InsForge is both configured and reachable, required migrations exist, owner authentication is configured, and deterministic compliance gates pass.
