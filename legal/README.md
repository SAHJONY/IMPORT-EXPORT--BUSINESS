# legal/ — Deal-advisory intake store (import/export business only)

Owner-only intake records for pre-commitment legal review by the AI agentic
law firm (departamento legal de SAHJONY). Files here are created by the
`/legal/intake` endpoint (see `legal_intake_api.py`).

- One `intake-<UTC>-<slug>.json` file per deal submitted from the
  "Firma Legal" owner page (`owner-firma-legal.html`).
- Local files only: never sent anywhere, no external calls, no filings.
- Business separation: import/export ONLY. Never cross-file with MY CUBA CASH.
- Label: **AI LEGAL RESEARCH — NOT LEGAL ADVICE** (Investigación legal con
  IA — no es asesoría legal). Intake does not create an attorney-client
  relationship.
