# SAHJONY Global Trade OS — Customer-First Rebuild

## North Star
Build the application around the customer's successful delivery, not around internal modules.

Primary outcome: qualified customer demand -> compliant, funded, executable trade -> delivered order -> collected gross profit -> repeat customer.

## Customer promise
SAHJONY guides a qualified customer from an initial need through sourcing, supplier comparison, commercial terms, compliance, documentation, logistics, shipment visibility, delivery, and post-delivery support.

Do not promise risk-free trade, guaranteed delivery, guaranteed lowest price, or guaranteed regulatory eligibility.

## Commercial operating constraints
- Target $0 SAHJONY capital at risk on every transaction.
- No inventory speculation as the default model.
- No supplier commitment before the transaction funding structure is approved.
- Protect SAHJONY supplier relationships, proprietary sourcing intelligence, and internal margin data.
- Optimize for collected gross profit, customer value, execution probability, logistics reliability, payment terms, and cycle time — not headline markup alone.

## Customer experience
Replace the module-first customer experience with five customer jobs:

1. **Request** — customer submits product/specification, quantity, destination, required date, and target budget if known.
2. **Compare** — SAHJONY qualifies demand and presents commercially appropriate options without exposing proprietary supplier intelligence.
3. **Secure** — customer sees required compliance, documents, commercial terms, payment milestones, and responsibilities before commitment.
4. **Track** — one Deal Room shows the order timeline, documents, shipment milestones, exceptions, messages, and next action.
5. **Receive** — delivery confirmation, issue resolution, reconciliation, and one-click reorder/repeat RFQ.

## Cuba-first acquisition layer
The public site remains globally credible while prioritizing Spanish-language Cuban private-sector demand.

Primary Cuba CTA: **Solicitar cotización / Enviar RFQ**.

RFQ minimum fields:
- producto y especificación
- cantidad / 20' / 40' / 40HC when applicable
- destino / puerto
- fecha requerida
- formato o empaque
- presupuesto objetivo (optional)
- company/contact and preferred communication channel

High-intent Cuba SEO/content clusters:
- proveedores para MIPYMES Cuba
- importar productos a Cuba
- compras mayoristas Cuba
- contenedores para Cuba
- proveedores Estados Unidos para Cuba
- alimentos por contenedor Cuba
- materiales de construcción Cuba
- equipos y repuestos Cuba
- sourcing internacional Cuba

## Deal Room
Every contracted/qualified trade case receives a customer-facing Deal Room with:
- current stage and percent-to-next-milestone
- next required action and responsible party
- accepted commercial offer
- customer-visible payment milestones/status
- compliance/document checklist
- logistics milestones and available tracking
- customer-visible documents
- communication timeline
- exception/status notices
- delivery confirmation
- reorder action

Internal-only fields must never leak to customer routes: supplier identities where commercially protected, supplier quotes, internal landed-cost model, gross margin, commissions, risk scoring, negotiation notes, owner controls, and proprietary research.

## Pipeline truth
Canonical stages:
RESEARCH_LEAD -> QUALIFIED_DEMAND -> RFQ_COMPLETE -> SOURCING -> FIRM_QUOTE -> COMPLIANCE_PASS -> CONTRACTED -> FUNDED -> IN_TRANSIT -> DELIVERED -> COLLECTED

No stage promotion without evidence. Registry presence alone is not demand. A quote is not revenue. A PO is not collected revenue.

## Profit engine
For each executable option calculate internally:
- supplier price
- inland origin costs
- freight/logistics
- insurance if applicable
- duties/fees where applicable
- payment/FX costs
- contingency
- total landed economics
- customer price
- SAHJONY protected gross profit
- gross margin %
- expected collected gross profit = protected GP x probability of collection/execution
- SAHJONY capital at risk (target: 0)

Rank alternatives primarily by expected collected gross profit subject to customer competitiveness, compliance, reliability, and $0 capital-at-risk gate.

## Sofia
Sofia is the customer's persistent executive account operator, not a generic chatbot.

She should:
- retrieve CRM/deal context before responding
- avoid asking for information already known
- convert conversations into structured RFQs
- explain the next action naturally
- maintain momentum and follow-up
- provide customer-visible status from the Deal Room
- escalate binding/high-impact actions
- never fabricate inventory, pricing, supplier confirmation, shipment status, regulatory clearance, or revenue

## Owner command center
Owner view is exception-driven. Default dashboard should surface:
- collected gross profit
- expected collected gross profit pipeline
- qualified RFQs
- firm quotes awaiting customer action
- deals blocked by compliance/payment/logistics
- capital-at-risk violations (target 0)
- quote cycle time
- supplier response time
- close/collection probability
- repeat customers
- owner decisions required now

Avoid vanity metrics as primary KPIs.

## Measurement
7-day:
- 100% new qualified demand captured through structured RFQ
- >=3 supplier candidates for priority RFQs when market depth permits
- >=2 firm comparable offers for qualified RFQs when obtainable
- 100% executable deals at $0 SAHJONY capital at risk
- customer next-action visible for every active case

30-day:
- improve RFQ-to-firm-quote median cycle time
- improve qualified-demand-to-contract conversion
- increase collected gross profit per active trade case
- establish repeat-order rate
- reduce owner interventions per completed deal

## Release gates
Before production release:
1. customer/employee/owner audience isolation tests pass
2. payment and finance safety doctors pass
3. customer Deal Room exposes no protected internal economics
4. Spanish Cuba RFQ path works end-to-end
5. CRM writes are idempotent and deduplicated
6. WhatsApp/Sofia handoff works
7. build passes
8. production smoke tests pass

This document is the product and operating specification for the customer-first rebuild.