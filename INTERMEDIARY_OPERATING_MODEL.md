# SAHJONY Intermediary Operating Model

## Default commercial role
SAHJONY operates as `BROKER_INTERMEDIARY` or `MANAGED_TRADE_ORCHESTRATOR` unless the owner explicitly configures another role for a specific managed case.

## Core flow
1. Buyer/private business submits a product need.
2. SAHJONY opens an engagement and identifies whom it represents.
3. SAHJONY sources and vets supplier candidates.
4. Owner selects the supplier only after compliance, quality and bank due diligence pass.
5. The managed case records SAHJONY's commercial role.
6. Compensation is recorded as a fixed fee, commission, sourcing fee, management fee, success fee, or buy/sell margin.
7. Compensation disclosure is required for the party responsible for paying it.
8. Seller of record, buyer of record, exporter of record, importer of record and SAHJONY commercial role are explicitly assigned and verified.
9. Product, authorization, screening, payment, documentation, logistics and other applicable trade controls pass.
10. The database release guard refuses `release_allowed=true` unless the intermediary engagement, economics and required legal-role assignments are verified.
11. Owner releases the transaction for execution.
12. Delivery and final financial reconciliation close the managed case.

## Role modes
- `BROKER_INTERMEDIARY`: SAHJONY connects/coordinates parties and earns disclosed compensation. Default: no title to goods, no custody of client funds.
- `SOURCING_AGENT`: SAHJONY acts for the buyer to find and qualify suppliers.
- `BUYING_AGENT`: SAHJONY acts under an engagement for the buyer in purchasing coordination.
- `SELLING_AGENT`: SAHJONY acts under an engagement for the supplier in sales coordination.
- `MANAGED_TRADE_ORCHESTRATOR`: SAHJONY manages the end-to-end transaction workflow while legal record roles remain separately assigned.
- `PRINCIPAL_RESELLER` / `PRINCIPAL`: SAHJONY may take commercial title/risk only when explicitly configured and supported by the transaction documents and applicable requirements.

## Hard controls
- Intermediary/agent modes cannot silently take title to goods.
- Both-sides representation requires explicit disclosure.
- SAHJONY cannot control client funds in intermediary mode unless the active engagement expressly authorizes it and the payment structure is otherwise lawful and operationally approved.
- Compensation must be approved and disclosed to the payer side before release.
- Seller, buyer, exporter, importer and SAHJONY commercial role must be verified before release.
- Importer/exporter-of-record status is never inferred from the word “middleman.”
- Country, product, sanctions, customs, banking and licensing controls remain independent and fail-closed.

## Revenue models
Supported models: fixed fee, percentage commission, sourcing fee, management fee, success fee, and buy/sell margin. The platform records estimated and final compensation separately from supplier cost, customer price and third-party costs.
