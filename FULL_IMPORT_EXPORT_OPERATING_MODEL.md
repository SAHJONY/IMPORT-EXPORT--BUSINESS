# SAHJONY Global Trade — Full Import/Export Operating Model

## Canonical trade lifecycle
Opportunity -> Buyer -> Quote -> Contract -> Supplier -> Purchase Order -> Treasury -> Production/QC -> Compliance -> Documents -> Shipment -> Customs -> Delivery -> Collection -> Profit Reconciliation -> Repeat Order.

## Operating domains
1. Supplier OS — legal entity, contacts, bank verification, MOQ, lead time, payment terms, certifications, quality/compliance performance.
2. Buyer CRM — buyer verification, credit status, quotes, sales orders, payment terms, collections, profitability.
3. Product Trade Passport — SKU, HTS, Schedule B, ECCN/EAR99, origin, marking, PGA profile, dangerous-goods status, target landed cost, sell price and margin floor.
4. Corridor Master — origin/destination, Incoterm, broker, forwarder, transit assumptions and customs notes.
5. Quote Engine — supplier cost + freight + duty + insurance + finance + other costs -> landed cost -> margin -> owner approval.
6. Sales Orders — accepted customer commitment, deposits, payment terms and fulfillment status.
7. Purchase Orders — supplier commitment, deposits, production dates and owner approval.
8. Quality Control — sample, in-process, pre-shipment and receiving inspections; defects and evidence.
9. Treasury — payables, receivables, beneficiary verification, maker-checker approvals, FX and settlement evidence.
10. Inventory / 3PL — lot/location stock, reservations, damage and fulfillment.
11. Communications — one case-linked timeline for messages, actions, approvals, documents, shipping and exceptions.
12. Documents — controlled movement and release of invoices, packing lists, transport/customs documents, certificates and payment evidence.
13. Shipping — booking through final delivery, carrier milestones, ETA changes and exceptions.
14. Compliance — KYC, sanctions, HTS/ECCN, origin, valuation, importer/exporter responsibilities, bonds/entry, AES/EEI, licenses, forced labor, PGA, FCPA/antiboycott, insurance and records.
15. Claims / Exceptions — holds, exams, damage, demurrage/detention, missed sailings, supplier delay, documentation error, denied-party match, rejected entry, nonpayment and insurance claim.
16. Profit Ledger — final landed cost, revenue, gross profit, margin and reconciliation by case/product/supplier/buyer/corridor.

## First Live Trade Ready gate
A trade is not operationally live until all applicable controls are PASS or an owner-authorized, evidence-backed waiver exists:
- supplier_verified
- buyer_verified
- product_passport
- corridor_approved
- quote_approved
- sales_order
- purchase_order
- funds_ready
- quality_passed
- compliance_released
- documents_ready
- shipping_booked
- insurance_active
- delivery_completed
- receivable_collected
- profit_reconciled

## Role boundaries
Owner: pricing/margin approval, treasury authority, compliance release, major exceptions, waivers and final profitability.
Employee: sourcing, buyer operations, quoting preparation, procurement, QC coordination, documents, logistics and collections within approved authority.
Customer/participant: only customer-scoped messages, approved documents, shipment visibility, compliance status and action requests. No supplier economics, internal margin, treasury controls or owner-only approvals.

## Fail-closed rules
- No trade release with unresolved required compliance controls.
- No employee override of owner-only release/waiver controls.
- No customer access to internal supplier, margin or treasury data.
- No beneficiary change without verification evidence.
- No external notification channel without approved provider, verified contact and consent.
- No carrier sync using guessed endpoints or unapproved credentials.
- No claim of full live-business readiness without a successful end-to-end pilot trade and reconciliation.
