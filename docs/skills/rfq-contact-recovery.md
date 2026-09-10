# SAHJONY RFQ Contact Recovery Skill

## Objective
Recover safely from failed/delayed RFQ delivery, invalid supplier/buyer contacts, logistics quoting gaps, and Cuba-provider compliance uncertainty without duplicate outreach or invented contact data.

## Trigger conditions
Run when Gmail or another transport reports a permanent failure, temporary delay, DNS/MX error, rejected alias, invalid recipient, or a material RFQ thread becomes unreachable.

## Evidence sources
Use, in order of preference:
1. Official provider/carrier/company website contact pages.
2. Official branch/agency directory pages.
3. Existing signed email thread/footer.
4. Verified CRM contact records.
5. Government/public corporate or licensing records.
6. Public business phone/WhatsApp/web-form only when clearly published by the business.

Never generate guessed email permutations or treat third-party lead databases as verified contact evidence.

## Recovery workflow
1. Classify the delivery state: temporary delay, permanent failure, delivered, or unknown.
2. For temporary delays, let the mail provider retry; do not create duplicate sends.
3. For permanent failures, identify alternate channels from evidence sources and rank verified same-entity, role-relevant contacts first.
4. Check whether another recipient in the same original message may already have received the RFQ. If so, hold duplicate resend unless the failed address was the only operative route.
5. Apply provider KYB/ownership/sanctions screening before recommending a Cuba-side provider for contracting/payment.
6. Prepare a resend only to a verified alternate contact. Sending remains a separate governed action.
7. Persist the failed route in email suppression/contact-health state so Sofía does not reuse it.

## Cuba logistics requirements
Always compare Houston, Miami/South Florida, and when relevant New Orleans/Gulfport.

For Houston, label explicitly:
- direct ocean service; or
- inland/feeder/intermodal/transshipment to Port Everglades, Miami, another U.S. hub, or Caribbean hub.

Keep these cost buckets separate:
- pickup
- inland
- feeder
- ocean
- port/destination
- customs
- warehouse/deconsolidation
- drayage
- final mile

Normalize upstream logistics quotes to USD/kg when quantity/weight makes the conversion defensible. Preserve the original quoted unit. Never combine upstream logistics cost with SAHJONY customer sell price in USD/lb.

### Crowley
Capture Houston pickup/terminal or LCL acceptance, Houston routing structure, Mariel frequency, minimum billable weight, USD/kg equivalent, Cuba-side handling, and last-mile options.

### CMA CGM
Capture Houston/South Florida connectivity to INDIGO/INDIGO3, exact origin/transshipment structure, service/vessel, LCL minimum, USD/kg equivalent, origin/destination charges, frequency, transit, and Cuba eligibility/documentation requirements.

### Seaboard Marine
Treat Cuba as FCL-only unless Seaboard explicitly states otherwise. Compare container economics by actual utilization.

## Cuba-side provider gate
Before treating a provider as commercially usable, verify legal entity, ownership/control, sanctions status, Cuba operating counterparties/subcontractors, customs authority where applicable, and importer authorization prerequisites.

Fail closed on potential involvement by GEMAR, GECOMEX, GAESA, Grupo CAUDAL, AUSA/Almacenes Universales, TRANSCARGO, CUBACONTROL, or any entity 50%+ owned by a blocked person until transaction-specific authorization/review establishes a lawful path.

TRANSCARGO is treated as blocked/high-risk for SAHJONY absent a specific applicable authorization. CUBACONTROL is not a default provider until ownership/sanctions status is confirmed. Prefer a Cuban direct importer's verified Aduana-authorized apoderado where lawful and operationally sufficient.

The software must not treat Cuba GL 1 as expanding CACR authorizations. Agricultural commodities/food, medicine, or medical-device transactions may have relevant humanitarian/CACR pathways, but applicability must be verified for the specific transaction.

## Provider-specific diligence
For Servicios Logísticos LMB, Mobe Caribe, Cárgate/DClick/El Lugar, and comparable Cuba-side providers, capture:
- exact legal entity and personnel
- ownership/control
- customs declaration filer
- current Aduana authorization or named authorized third party
- party obtaining levante
- party extracting LCL/FCL from Terminal de Contenedores de Mariel
- terminal/destination charges
- drayage
- warehousing/deconsolidation
- empty-container return
- Havana/nationwide final-mile delivery
- required documents
- discharge-to-release/extraction time
- pricing units/minimums
- importer authorization prerequisites

For Cárgate, separate software/platform role from operating legal entity, warehouse owner/operator, trucking counterparties, and any mandatory state-owned partner.

For Mobe Caribe, verify the exact Cuba legal entity/personnel and all Cuba-side subcontractors before commercial use.

## Sugar RFQs
For every material sugar reply capture:
- ICUMSA/specification
- origin
- packaging
- MOQ
- FOB/CFR/CIF Mariel price
- quote validity
- payment terms/banking requirements
- Cuba-specific requirements

## Output states
- `WAIT_PROVIDER_RETRY`: temporary mail delay; no duplicate send.
- `RESEARCH_ALTERNATE`: permanent failure and no verified alternate route.
- `PREPARE_RESEND`: permanent failure plus verified alternate route and no duplicate risk.
- `HOLD_COMPLIANCE`: ownership/sanctions/customs gate not cleared.
- `QUOTE_READY`: enough verified rate/route/commercial data exists for a non-binding SAHJONY quote workflow.

## Success metrics
- permanent-failure contacts recovered to a verified route: >= 90%
- guessed/invented contact addresses: 0
- duplicate resend rate: < 1%
- logistics quotes with defensible USD/kg normalization: >= 95% when weight data exists
- Cuba providers recommended before KYB/ownership/sanctions gate: 0
- customer sell price mixed with upstream cost: 0
