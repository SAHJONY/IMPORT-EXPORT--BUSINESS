# SAHJONY GLOBAL TRADE — BUSINESS LAUNCH PACK

Status: CONTROLLED TEMPLATE SET — COUNSEL / TAX / COMPLIANCE REVIEW REQUIRED BEFORE LIVE USE.

This pack defines the minimum real-business documents and SOPs for SAHJONY's managed-trade/intermediary model. It does not itself create legal authority, government authorization, customs status, banking permissions, insurance coverage, or professional advice.

## 1. Intermediary / Managed Trade Engagement

Every client relationship must identify:
- Client legal name and KYB dossier ID.
- SAHJONY commercial role: BROKER_INTERMEDIARY, SOURCING_AGENT, BUYING_AGENT, SELLING_AGENT, or MANAGED_TRADE_ORCHESTRATOR.
- Scope of sourcing, negotiation, documentation, logistics and compliance coordination.
- Whether SAHJONY may bind the client. Default: NO.
- Whether SAHJONY may receive/control client funds. Default: NO unless separately approved.
- Whether SAHJONY takes title to goods. Default: NO in broker/agent modes.
- Compensation type, payer, currency, fee/commission/margin basis and disclosure.
- Term, termination, confidentiality, dispute process and recordkeeping.
- Explicit statement that importer/exporter-of-record and customs/banking roles are separately assigned per transaction.

## 2. Fee Schedule

Supported compensation structures:
- Fixed sourcing fee.
- Percentage commission.
- Transaction management fee.
- Success fee payable only after defined milestone.
- Buy/sell margin only when SAHJONY is explicitly acting as principal/reseller.

No compensation model may be used in production until recorded in `managed_trade_economics`, disclosed as required, and owner-approved.

## 3. Customer / Private Business KYB

Required before activation:
- Legal name and registration evidence.
- Beneficial owners/controllers.
- Identity/registration documents.
- Tax/registration data where applicable.
- Bank/payment-route evidence.
- Restricted-party/sanctions screening.
- Risk rating.
- For Cuba private businesses: private-sector eligibility evidence and current-law transaction authorization controls.

A customer may not be marked ACTIVE while KYB is FAIL, sanctions screening is HIT, or risk rating is PROHIBITED.

## 4. Supplier Onboarding

Required supplier evidence:
- Legal entity and address.
- Authorized contact.
- Product capability/specification evidence.
- Pricing, MOQ, lead time, Incoterms and payment terms.
- Quality/QC evidence.
- Bank-account verification using maker-checker controls.
- Restricted-party screening.
- Export capability and required registrations/licenses where applicable.
- Signed supplier terms or purchase-order terms.

Supplier commitment is owner-controlled after compliance, quality and bank due diligence pass.

## 5. Product Trade Dossier

Each product/corridor requires:
- SKU/product description.
- Origin/destination.
- HTS classification and Schedule B where applicable.
- ECCN or EAR99 determination where applicable.
- Authorization/license/exception basis where required.
- Labeling, permit, safety or product-specific controls.
- Supporting classification evidence.
- Owner approval.

## 6. Operating Partner Registry

Minimum partner categories for live managed trade:
- Customs broker.
- Freight forwarder.
- Cargo insurer.
- Payment provider/bank path.
- Accounting/tax support.

Carrier, warehouse/3PL, inspection/QC, legal counsel and trade-credit insurance are added based on transaction/corridor needs.

A partner is production-usable only when due diligence = PASS, contract = SIGNED, active = true and owner-approved = true.

## 7. Payment / Treasury SOP

Before money movement:
- Buyer/supplier/beneficiary identities verified.
- Beneficiary bank details independently validated.
- Payment purpose and transaction ID recorded.
- Applicable sanctions/compliance gate passed.
- Currency/FX quote and fees captured.
- Deposit/final-payment conditions tied to commercial milestones.
- No employee may change beneficiary data and approve the same change.
- Reconciliation must match invoices, POs, bank settlement and ledger entries.

## 8. Logistics / Customs SOP

Before booking/release:
- Exporter of Record identified.
- Importer of Record identified.
- Customs broker assigned.
- Freight forwarder/carrier assigned.
- Incoterm and title/risk transfer documented.
- Required commercial/export/import documents complete.
- Insurance coverage evidenced where required.
- Compliance release and owner release passed.

## 9. Incident / Claims / Refund SOP

Tracked incident classes include customs holds, documentation errors, cargo damage, supplier delays, missed sailings, payment failures, sanctions hits, demurrage/detention, claims, quality failures and refund disputes.

High/Critical incidents require owner visibility. A first-live-trade certification cannot pass with unresolved incidents.

## 10. Accounting / Reconciliation SOP

Each trade must close with:
- Customer receivable reconciled.
- Supplier payment reconciled.
- Freight/duty/insurance/fees reconciled.
- FX gains/losses recorded where applicable.
- SAHJONY fee/commission/margin recognized according to the approved transaction role.
- Final P&L produced.
- Supporting evidence retained in the audit trail.

## 11. First Controlled Live Trade — Definition of Done

The business is not 100% operational until a real controlled transaction completes:

Customer Need → KYB → Engagement → Supplier Sourcing → Supplier Due Diligence → Quote → Product Classification → Authorization Match → Seller/Buyer/EOR/IOR Assignment → Payment Path → Documents → Logistics → Compliance Release → Owner Release → Shipment → Delivery → Customer Collection → Supplier/Freight/Duty Reconciliation → SAHJONY Fee Collected → Final P&L → Audit Closure.

`FIRST_LIVE_TRADE_CERTIFIED` may become true only after the live certification record shows:
- delivered_at populated;
- reconciled_at populated;
- customer_paid = true;
- supplier_paid = true;
- freight_duty_reconciled = true;
- sahjony_fee_collected = true;
- unresolved_incidents = 0;
- audit_closed = true;
- e2e_status = PASSED;
- owner_certified = true.

Dry runs, demos and simulated transactions do not qualify.
