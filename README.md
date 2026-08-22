# SAHJONY Global Trade Intelligence OS

An AI-agentic operating system for import/export businesses: sourcing, buyer intelligence, landed-cost analysis, compliance, counterparty risk, logistics, documentation, shipment monitoring, treasury and executive decision support.

## Architecture

The platform uses a **deterministic release policy** around AI agents. LLMs may research, summarize, rank and recommend, but they cannot override mandatory compliance, classification or counterparty-risk gates.

Core layers:

- **FastAPI control plane** — owner API, workflows, health and readiness.
- **Agentic Trade OS** — landed cost, compliance, counterparty, logistics and margin policy engines.
- **13-agent registry** — sourcing, buyers, classification, compliance, documents, logistics, treasury, monitoring and executive copilot.
- **InsForge backend** — Postgres, Auth, Storage, Edge Functions, Realtime and AI/model infrastructure.
- **Audit trail** — trade cases, agent runs, decisions, checks, documents and events.

## InsForge

Set server-only credentials through environment variables. Never commit project-admin credentials to Git.

```bash
cp .env.example .env
```

Required for the current server adapter:

```text
OWNER_TOKEN=<long-random-owner-token>
INSFORGE_BASE_URL=https://<project>.<region>.insforge.app
INSFORGE_API_KEY=<project-admin-key>
INSFORGE_ANON_KEY=<public-anon-key>
```

Apply the database schema in:

```text
insforge/migrations/001_trade_os.sql
```

The schema creates trade cases, counterparties, shipments, documents, compliance checks, agent runs, auditable trade decisions and event history.

## API

Start locally:

```bash
pip install -r requirements.txt
uvicorn fastapi_server:app --reload --port 50001
```

Key endpoints:

- `GET /health` — service and InsForge configuration status.
- `GET /v2/platform/readiness` — production gate and blockers.
- `GET /v2/agents` — agent registry.
- `POST /v2/trade/simulate` — deterministic trade analysis without persistence.
- `POST /v2/trade/analyze` — analysis plus optional InsForge persistence.
- `POST /run/{agent-name}` — governed workflow queue entrypoint.

Example scenario:

```json
{
  "scenario": {
    "mode": "import",
    "origin_country": "Mexico",
    "destination_country": "United States",
    "product": "Fresh avocados",
    "hs_code": "080440",
    "quantity": 1000,
    "unit_cost": 1.0,
    "freight_cost": 250,
    "insurance_cost": 25,
    "duty_rate_pct": 0,
    "broker_fees": 100,
    "inland_cost": 125,
    "target_sale_price_per_unit": 2.5,
    "incoterm": "FOB",
    "supplier_verified": true,
    "buyer_verified": true,
    "documents_complete": true,
    "sanctions_screened": true,
    "product_regulatory_reviewed": true
  },
  "persist": true
}
```

## Release policy

A trade remains `HOLD` when mandatory sanctions/admissibility/classification gates are incomplete. `REVIEW` means owner/human review is required. `READY` is a planning release state, not legal advice, customs clearance, financing approval or a guarantee that a shipment is admissible.

## Security baseline

- `.env` is not tracked.
- Runtime databases are not tracked.
- Participant tokens are stored as hashes in the legacy compatibility layer.
- InsForge project-admin credentials remain server-only.
- CI compiles the Python code and executes policy tests on pushes and pull requests.

## Next production milestones

1. Provision/connect the InsForge project and apply the migration.
2. Replace legacy participant SQLite with InsForge Auth + RLS.
3. Add live customs/tariff, sanctions, carrier, FX and trade-data connectors.
4. Add document storage and OCR/structured extraction through InsForge Storage/Functions.
5. Build the owner command center and real-time shipment/exception dashboard.
6. Add human approval workflows for financial, legal and external actions.
