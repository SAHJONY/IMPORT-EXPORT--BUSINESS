# Cuba Direct Import Regulatory Register — 2026

Last reviewed: 2026-09-06

## Operating principle

SAHJONY does not assume a transitaria is the mandatory commercial intermediary for every Cuba shipment. The first gate is whether the Cuban entity has verified authority from MINCEX to conduct foreign-trade operations directly and whether the proposed merchandise falls within its approved import nomenclature or applicable permit.

A transitaria, customs agent, terminal operator, warehouse or last-mile provider may still be required for a specific operational function. Their use is determined by law, customs procedure and shipment needs—not by an automatic commercial-intermediary assumption.

## Verified regulatory register

### Transformación 129 — direct foreign trade
Status: POLICY_VERIFIED

Granma reported on 11 July 2026 that Transformation 129 authorizes state, private and cooperative enterprises to conduct foreign-trade operations directly, subject to prior approval by the Ministry of Foreign Trade and Foreign Investment (MINCEX). This means direct import authority is not automatic for every MIPYME.

Source: https://www.granma.cu/cuba/2026-07-11/amplian-las-operaciones-directas-de-comercio-exterior-en-cuba-10-07-2026-21-07-05

### Resolución MINCEX 126/2026
Status: VERIFIED

Gaceta Oficial No. 73, published 3 September 2026, lists MINCEX Resolution 126/2026: “Procedimiento para la concesión de facultades y el otorgamiento, modificación y cancelación de nomenclaturas de mercancías de importación y exportación y para el otorgamiento de permisos eventuales” (GOC-2026-487-O73).

This is the core procedural reference for granting foreign-trade faculties, merchandise nomenclatures and eventual permits. SAHJONY must verify the actual authority and nomenclature of each Cuban importer before marking it DIRECT IMPORT ELIGIBLE.

Sources:
- https://cuba.vlex.com/vid/diario-oficial-republica-cuba-1133233710
- https://cuba.vlex.com/source/13127/issue/2026/09/03

### Decreto-Ley 108 “De Aduanas” / Decreto 134
Status: VERIFIED

Published in Gaceta Oficial No. 7 on 21 January 2026. These establish the current customs framework, including customs regimes, formalization, authorization, clearance, control and representation. Direct foreign-trade authority does not remove customs formalities.

Source: https://www.directoriocubano.com/servicios/gaceta-oficial/2026/ordinaria/7/

### Decreto 160/2026
Status: VERIFIED

Updates activities that are unauthorized or conditioned for private companies, MIPYMES, non-agricultural cooperatives and self-employed workers. Product/business eligibility must be checked against this framework and against the importer’s approved nomenclature.

Source: https://www.granma.cu/cuba/2026-07-29/flexibilizan-el-ejercicio-de-actividades-para-los-actores-economicos-no-estatales-28-07-2026-20-07-45

### Decretos 167 and 168/2026 — domestic commerce
Status: VERIFIED

Update the framework for wholesale/retail domestic commerce and the Central Commercial Registry. Relevant after importation for sale and distribution inside Cuba.

Source: https://www.directoriocubano.com/servicios/gaceta-oficial/2026/ordinaria/69/

## SAHJONY route model

### DIRECT
Supplier → SAHJONY → Carrier → Authorized Cuban importer → Customs clearance → Delivery

Use only when MINCEX authority and applicable nomenclature/permit are verified.

### DIRECT + LOGISTICS
Supplier → SAHJONY → Carrier → Authorized Cuban importer → Customs/handling provider → Last mile

Use when the importer has direct authority but needs customs representation, terminal handling, warehousing, refrigerated handling, container extraction or national delivery.

### MANAGED IMPORT
Supplier → SAHJONY → Carrier → Authorized intermediary/import structure → Buyer

Fallback when the Cuban customer lacks verified direct-import authority or when the transaction requires another authorized structure.

## Direct Import Eligibility record

Required evidence fields:
1. Legal entity name and registration.
2. MINCEX foreign-trade authority.
3. Approved import nomenclature.
4. Eventual/special permit if applicable.
5. Customs/importer registration.
6. Authorized representative or customs agent.
7. Product/commodity eligibility.
8. Ownership and sanctions screening.
9. U.S. export-control classification.
10. End-user and end-use verification.
11. Payment/banking route.
12. Cuba point of entry.
13. Warehouse/handling plan.
14. Last-mile plan.
15. Authority effective/expiry dates.
16. Source evidence and verification date.

## U.S. compliance gate

Cuban permission and U.S. permission are independent.

`CUBA IMPORT AUTHORIZED + U.S. EXPORT AUTHORIZED = SHIPMENT ELIGIBLE`

For shipments originating from the United States, SAHJONY must perform transaction-specific review of the product, EAR/BIS authorization, end-user/end-use and applicable OFAC restrictions before release.

## Pricing isolation

Provider/transitaria/carrier rate request and storage: USD/kg.

Internal conversion: `supplier USD/kg ÷ 2.20462 = supplier cost USD/lb`.

Customer-facing SAHJONY pricing: USD/lb.

Supplier net costs, internal landed cost logic, markup and margin remain confidential.

## Transitaria policy

Transitarias are retained as potential service providers rather than presumed mandatory commercial intermediaries. Evaluate them for customs/representation where legally authorized, terminal handling, warehousing, refrigerated handling, container extraction/return, national distribution, proof of delivery, tracking and claims.

Routing should optimize verified landed cost, SLA, capacity, coverage, compliance, tracking, claims performance and protected SAHJONY economics.

## Evidence rule

Do not mark a Cuban business DIRECT IMPORT ELIGIBLE because it is merely registered as a MIPYME/private company. Require documentary evidence of the relevant MINCEX authority and merchandise nomenclature/permit. Legal/compliance determinations remain transaction-specific.