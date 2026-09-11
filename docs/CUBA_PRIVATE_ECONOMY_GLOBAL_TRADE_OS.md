# SAHJONY Cuba Private Economy & Global Trade OS

## Purpose

Extend the existing SAHJONY import/export application so private-sector participants in Cuba can be governed through the same trade operating system used for RFQs, sourcing, pricing, payments, logistics, documents, and compliance.

The module supports these participant types:

- PERSON
- TCP
- MIPYME
- COOPERATIVE
- PRIVATE_COMPANY
- FOREIGN_BUYER
- FOREIGN_SUPPLIER

## Governed corridors

### CU-CU
Private-sector trade within Cuba. Controls include identity/KYC-KYB, beneficial ownership where applicable, private-sector eligibility, business-activity review, invoice/tax evidence, sanctions screening evidence, and audit evidence.

### CU-WORLD
Private-sector exports from Cuba to non-U.S. destinations. Controls add counterparty-country requirements, HS classification, customs, banking-route review, logistics, and Cuba trade-authority review.

### WORLD-CU
Imports and global sourcing for the Cuban private sector. Controls add supplier/country requirements, HS classification, customs, banking, logistics, landed-cost evidence, and Cuban trade-authority review.

### CU-US
Any Cuba transaction involving the United States or a material U.S. nexus. This is a special-review corridor. The engine requires enhanced U.S.-nexus/product-control review and does not infer authorization from private-sector status alone.

## Decision model

The corridor classifier is intentionally fail-closed:

- SANCTIONS BLOCKED => PROHIBITED / BLOCK
- SANCTIONS PENDING, REVIEW, or ERROR => HIGH / HOLD
- missing KYC/KYB => HOLD
- missing beneficial-ownership evidence for business entities => HOLD
- fraud or structuring indicator => HOLD
- CU-US without completed product-control review => HOLD

A stable, recurring family-remittance pattern is a favorable behavioral signal only. It may reduce anomaly weighting, but it can never override sanctions, KYC/KYB, fraud, structuring, product controls, or mandatory review.

## API

Production-routed namespace:

- `GET /cuba-private-sector/health`
- `GET /cuba-private-sector/leads/private-economy/overview`
- `GET /cuba-private-sector/leads/private-economy/corridors`
- `POST /cuba-private-sector/leads/private-economy/classify`

Canonical aliases also exist inside the FastAPI app under `/cuba-private-sector/private-economy/*`; the `leads/private-economy` aliases are used in production because the current Vercel route gate explicitly permits `leads.*`.

## UI

`public/cuba-private-economy.html` provides a five-language workspace:

- Spanish
- English
- French
- Portuguese
- Arabic / RTL

It includes corridor cards, workflow explanation, links to the existing MIPYME RFQ portal, Global Sourcing and Marketplace, plus an interactive fail-closed corridor classifier.

Until a dedicated pretty route is added to `vercel.json`, the static workspace is available by its filesystem path `/cuba-private-economy.html` after deployment.

## Compliance boundary

This module is workflow and evidence infrastructure, not an automatic legal determination engine. It does not claim that a live sanctions provider is configured. Production release of a trade or payment must rely on current authoritative evidence and authorized review appropriate to the jurisdictions involved.