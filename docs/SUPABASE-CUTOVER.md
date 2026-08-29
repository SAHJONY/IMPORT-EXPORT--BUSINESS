# Supabase production cutover

SAHJONY Global Trade is migrating its canonical PostgreSQL persistence from Neon to Supabase.

Production database policy:
- `DATABASE_URL` remains the canonical runtime variable.
- Vercel/serverless should use the Supabase transaction pooler URI.
- Direct database credentials and passwords must never be committed to this repository.
- The existing production schema bootstrap remains provider-neutral and applies against the active `DATABASE_URL`.
- Neon-specific IPv4 handling is conditional on `.neon.tech` hosts and is inert for Supabase hosts.

Target Supabase project ref: `qprlbmcoksrpuvodxjtt`.

Cutover gates:
1. Production deployment loads the new `DATABASE_URL`.
2. `/activation/health` applies/verifies the canonical schema and RLS.
3. CRM reads and writes succeed.
4. Cuba order/RFQ intake persists successfully.
5. Existing durable records are reconciled before Neon is retired.
6. Neon remains rollback-only until data reconciliation is complete.
