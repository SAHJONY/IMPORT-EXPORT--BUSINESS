# SAHJONY Global Trade — Operational Activation Registry

Date: 2026-08-22

This registry separates software capability from real-world authority. Nothing moves from CANDIDATE to APPROVED without actual evidence. No readiness flag is turned on from a dry run.

## Status vocabulary

- BUILT: code/workflow exists.
- CONFIG_REQUIRED: external credential/account must be connected.
- CANDIDATE: third-party provider identified; no commercial relationship yet.
- OUTREACH_SENT: non-binding onboarding inquiry sent.
- DUE_DILIGENCE: provider documents/capabilities under review.
- CONTRACT_REQUIRED: signature, KYC/KYB, payment method or account acceptance required.
- E2E_REQUIRED: live/sandbox provider workflow still must be tested.
- APPROVED: owner-approved after evidence and contract.
- LIVE_CERTIFIED: proved in a real completed transaction.

## Activation matrix

| Capability | Current status | Evidence already in platform | Remaining external evidence |
|---|---|---|---|
| OpenAI AI engine | BUILT / CONFIG_REQUIRED | Governed AI Brain, GPT routing, audit and authority boundary | Production API key, provider call E2E |
| Anthropic AI engine | BUILT / CONFIG_REQUIRED | Fable/Opus routing, consensus mode, audit | Production API key, provider call E2E |
| InsForge persistence | BUILT / CONFIG_REQUIRED | SQL schemas and backend adapter | Live project credentials, schema application, RLS and restore evidence |
| OFAC screening | BUILT | Direct Treasury OFAC SLS SDN and consolidated list connector | Production network reachability + E2E evidence |
| U.S. HTS research | BUILT | Direct official USITC HTS REST connector | Production reachability + classification review procedure |
| Global supplier sourcing | BUILT / E2E_REQUIRED | Candidate scoring, corridor controls, owner selection | One permitted-corridor E2E and real supplier DD |
| Customs broker | CANDIDATE | Operating partner governance schema | Capability confirmation, license evidence, contract, owner approval |
| Freight forwarder/carrier | CANDIDATE | Shipping workflow; carrier adapter | Cuba commercial-route confirmation, account/contract, E2E tracking |
| Cargo insurance | CANDIDATE | Insurance cost/evidence controls | Broker/carrier approval, policy/binder, Cuba/corridor eligibility |
| Banking/payment rails | CONFIG_REQUIRED | Airwallex adapter + beneficiary maker-checker | KYC-approved account/credentials; each Cuba payment route separately supported by provider/bank |
| Accounting/tax | CANDIDATE | Double-entry ledger/reconciliation workflow | Engagement letter, chart-of-accounts/tax policy review, monthly close procedure |
| Customer/intermediary agreements | BUILT / CONTRACT_REQUIRED | Engagement/economics/role-assignment governance | Attorney/accountant review as appropriate, actual signatures |
| Cuban private-sector customer acquisition | BUILT | Spanish lead funnel and controlled KYB promotion | Real prospect submission and eligibility review |
| First controlled trade | E2E_REQUIRED | 14-stage managed-trade workflow + certification | Actual customer, supplier, authorization basis, payment, shipment, delivery, reconciliation |
| Backups/monitoring | BUILT / E2E_REQUIRED | Backup and Vercel monitoring gates | InsForge restore drill; alert delivery verification |

## Candidate operating partners — not approved

### Cuba ocean / logistics
- Crowley Logistics / Cuba service — candidate for commercial LCL/FCL and Cuba corridor logistics. Current published services show U.S.–Cuba routes and commercial LCL/FCL contact through 1-800-CROWLEY. Source: https://www.crowley.com/locations/
- Cuba Express contact path may be used only to reach/reroute to the correct commercial team; consumer/parcel capability is not automatically proof of B2B export authority for a SAHJONY transaction.

### Customs brokerage / forwarding
- K Carlton International — candidate customs broker/freight forwarder, Fort Lauderdale, Florida. New commercial relationship forms are published at https://kcarlton.com/tools/ and directed to imports@kcarlton.com / exports@kcarlton.com.
- D Manganelli Logistics — alternate candidate customs brokerage and forwarding provider in Doral, Florida; must independently confirm Cuba corridor capability before approval.

### Cargo insurance
- Abbey USA — candidate cargo insurance broker, Miami. Published cargo insurance program: https://www.abbey-usa.com/our-services/cargo-insurance ; contact info@Abbey-USA.com.
- Anker Cargo Insurance — alternate candidate; corridor and Cuba exclusions must be checked before use.

### Accounting / tax
- IM Tax Advisors — candidate international tax/accounting firm in South Miami with stated import/export and international-tax experience. Source: https://www.imtaxadvisors.com/ ; contact info@imtaxadvisors.com.

## Non-negotiable Cuba controls

1. Private-sector eligibility is not transaction authorization.
2. Product/ECCN/EAR99 and end use/user must be assessed per transaction.
3. OFAC/BIS and any other applicable authority must be matched to the exact facts.
4. Payment provider/bank must support the exact lawful route; no assumption that Airwallex or any bank supports Cuba merely because an account exists.
5. Importer/exporter of record and customs responsibility must be explicit.
6. No payment, supplier commitment or shipment release solely from AI output.
7. Every provider and counterparty remains fail-closed until required evidence is recorded.

## First-live-trade definition of done

A trade is LIVE_CERTIFIED only after a real customer request is qualified, customer/counterparty KYB is complete, supplier due diligence passes, product and authorization basis are documented, roles are assigned, payment beneficiary/path is verified, required documents/logistics/insurance are ready, compliance and owner releases are recorded, shipment is delivered, supplier/freight/duties/fees are reconciled, SAHJONY revenue is collected, incidents are closed, and the final audit is complete.
