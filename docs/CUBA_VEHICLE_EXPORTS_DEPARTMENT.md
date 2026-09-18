# SAHJONY Cuba Vehicle Export Department

## Scope

This department handles only lawful vehicle-export opportunities from the United States to Cuba. It owns intake, compliance preflight, logistics qualification, documentation readiness, carrier coordination, and shipment case management for automobiles and light vehicles.

It does **not** create government licenses, customs clearance, legal opinions, carrier acceptance, financial commitments, or binding customer promises. Those remain subject to evidence and Chairman governance.

## Corrected regulatory model

1. **BIS / EAR is the primary export-control gate for the vehicle itself.** Cuba is subject to broad EAR licensing requirements. A shipment may proceed without an individual BIS license only when a valid license exception or exclusion applies to the exact item, end user, and end use. License Exception SCP must never be assumed merely because the transaction supports the private sector.
2. **OFAC / CACR is a separate sanctions gate.** OFAC authorization and BIS authorization are independent. A general license does not enlarge the scope of the CACR or substitute for BIS requirements.
3. **Used self-propelled vehicle exports require CBP export controls.** Ownership/title documentation and EEI/AES filing must be completed, and the applicable port presentation timing requirements must be satisfied before export.
4. **EV/PHEV/hybrid vehicles are not automatically prohibited.** Battery and dangerous-goods acceptance must be reviewed with the carrier and forwarder before booking.
5. **Cuban-side importer eligibility must be verified for the exact transaction.** The department must confirm the importer/consignee is legally able to receive the vehicles and that Cuban customs requirements are satisfied before the shipment is represented as executable.
6. **Incoterms are commercial allocations of cost/risk, not compliance shortcuts.** CIF means the seller arranges and pays cost, insurance, and freight to the named destination port under the applicable Incoterms rule; it does not transfer export-control responsibility or automatically make the Cuban agent responsible for freight.
7. **Do not quote invented government-license fees.** Government filing fees, if any, and professional-service fees must be separated and verified before they are presented to a customer.

## Mandatory case intake

For every vehicle capture:

- VIN
- year / make / model
- condition: new or used
- powertrain: gasoline / diesel / hybrid / PHEV / EV / other
- purchase/value basis
- title state and title number
- ownership-document verification
- U.S. pickup city/state
- proposed U.S. export port
- proposed Cuba port
- Cuban importer/consignee
- ultimate end user and end use
- BIS classification / EAR99 determination
- BIS authorization basis
- OFAC/CACR authorization basis
- restricted-party screening result
- AES/EEI ITN
- carrier acceptance
- dangerous-goods review when applicable
- Cuba customs/import-readiness evidence

## Fail-closed gates

A case remains **HOLD** until each applicable gate is PASS or NOT_APPLICABLE:

1. Vehicle identity and title
2. Used-vehicle CBP export requirements
3. AES / EEI / ITN
4. EAR classification
5. BIS authorization basis
6. OFAC / CACR authorization basis
7. Restricted-party screening
8. Cuban importer eligibility
9. End-user and end-use eligibility
10. Carrier acceptance
11. Dangerous-goods review
12. Commercial documents
13. Cuba customs/import readiness

Even when all gates are complete, the API returns **READY_FOR_OWNER_REVIEW**, not an automatic shipment release.

## Operating workflow

`LEAD -> VEHICLE INTAKE -> TITLE/VIN CHECK -> EXPORT CLASSIFICATION -> SANCTIONS SCREEN -> CUBAN IMPORTER CHECK -> CARRIER/RATE REQUEST -> AES/EEI -> DOCUMENT PACK -> OWNER REVIEW -> BOOKING -> PORT DELIVERY -> OCEAN MOVEMENT -> CUBA CLEARANCE -> FINAL DELIVERY -> CLOSEOUT`

## Commercial quoting rule

Do not issue a firm customer quote until all of the following are known:

- inland pickup cost
- port/terminal handling
- export filing/document fees
- ocean freight
- insurance basis
- vehicle-specific dangerous-goods surcharge, if any
- Cuban destination charges
- customs/tax/agent charges, where the customer is responsible
- final-mile delivery cost
- SAHJONY service fee / margin
- exclusions and validity period

Until then, customer pricing must be labeled **indicative / subject to compliance and carrier confirmation**.

## Chairman governance

The department may research, preflight, organize documents, compare carriers, prepare RFQs, and produce nonbinding quotations autonomously. It may not move money, sign documents, make binding commitments, waive compliance gates, or release a shipment without the required approval and evidence trail.
