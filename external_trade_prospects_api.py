from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, Header

from customer_crm_api import identity
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY External Trade Prospects", version="1.4.0", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deal(
    prospect_id: str,
    title: str,
    category: str,
    description: str,
    country: str,
    destination: str,
    stage: str,
    risk: str,
    score: int,
    confidence: int,
    *,
    buyer_name: str | None = None,
    buyer_company: str | None = None,
    quantity: float | None = None,
    unit: str | None = None,
    incoterm: str | None = None,
    payment_terms: str | None = None,
    verification_status: str = "research_only",
    evidence_summary: str = "",
    next_action: str = "Independently verify identity, authority, commercial need and payment capability before promotion.",
    source_url: str | None = None,
    evidence_urls: list[str] | None = None,
    supplier_outreach: list[dict] | None = None,
    created_at: str | None = None,
    extra: dict | None = None,
) -> dict:
    row = {
        "prospect_id": prospect_id,
        "organization_id": ORG_ID,
        "opportunity_title": title,
        "product_category": category,
        "product_description": description,
        "buyer_name": buyer_name,
        "buyer_company": buyer_company,
        "buyer_country": country,
        "destination": destination,
        "quantity": quantity,
        "unit": unit,
        "incoterm": incoterm,
        "payment_terms": payment_terms,
        "verification_status": verification_status,
        "qualification_stage": stage,
        "risk_level": risk,
        "confidence": confidence,
        "opportunity_score": score,
        "revenue_priority_tier": "A" if score >= 80 and risk != "high" else ("A-" if score >= 70 and risk != "high" else "B"),
        "evidence_summary": evidence_summary or description,
        "next_action": next_action,
        "source_url": source_url,
        "evidence_urls": evidence_urls or ([source_url] if source_url else []),
        "supplier_outreach": supplier_outreach or [],
        "possible_profit_status": "INPUTS_REQUIRED",
        "possible_profit_basis": "Supplier cost, buyer price and protected SAHJONY compensation are not yet evidenced.",
        "possible_profit_min_usd": None,
        "possible_profit_max_usd": None,
        "possible_profit_period": None,
        "source_record": "live_execution_snapshot",
        "created_at": created_at or now(),
        "updated_at": now(),
    }
    if extra:
        row.update(extra)
    return row


EXECUTION_SNAPSHOT = [
    _deal(
        "ext_oman_motors_20260519",
        "Oman buyer — AC/DC industrial motors",
        "Industrial equipment",
        "AC/DC industrial motors for one 20-ft container; final model mix and technical specification require buyer confirmation.",
        "OM",
        "Oman",
        "supplier_sourcing",
        "medium",
        86,
        78,
        quantity=1,
        unit="20-ft container",
        incoterm="FOB/CIF Oman requested",
        payment_terms="L/C requested",
        verification_status="supplier_response_active",
        supplier_outreach=[
            {"supplier":"Bharat Bijlee","status":"RFQ_SENT"},
            {"supplier":"CG Power","status":"BOUNCED_550"},
            {"supplier":"ABB India","status":"ACKNOWLEDGED_ROUTED_INTERNAL"},
            {"supplier":"WEG India","status":"RFQ_SENT_NO_BOUNCE"},
        ],
        evidence_summary="Bharat Bijlee and WEG RFQs remain active. CG Power returned a 550 delivery failure. ABB acknowledged the RFQ and routed it to its India Contact Center / appropriate Motion-export team, creating a live supplier-response milestone.",
        next_action="Obtain ABB/Bharat Bijlee/WEG model ranges, IEC certifications, 20-ft loading, FOB/CIF Oman prices, lead time and warranty; verify buyer entity, authority and issuing-bank L/C capability before binding pricing.",
        source_url="https://www.bharatbijlee.com/",
        evidence_urls=["https://www.bharatbijlee.com/","https://global.abb/group/en","https://www.weg.net/"],
        created_at="2026-05-19T00:00:00+00:00",
        extra={"supplier_contacted_count":4,"supplier_effective_count":3,"supplier_delivery_failures":1,"supplier_reply_count":1},
    ),
    _deal(
        "ext_us_ev_chargers_20260608",
        "U.S./Canada buyer — AC and DC EV chargers",
        "EV infrastructure",
        "North America-bound AC/DC EV charging equipment for an initial 20-ft container; certified models, connector standards and final power/network requirements are gating items.",
        "US",
        "United States / Canada",
        "supplier_response",
        "medium",
        87,
        80,
        quantity=1,
        unit="20-ft container",
        incoterm="FOB/CIF requested",
        payment_terms="Irrevocable L/C requested where available",
        verification_status="supplier_response_active",
        supplier_outreach=[
            {"supplier":"Exicom","status":"RFQ_SENT"},
            {"supplier":"Servotech Renewable Power System","status":"REPLIED_REQUESTED_CONTACT_NUMBER","contact_phone":"+91-9717691800"},
            {"supplier":"Lubi EV Solutions","status":"RFQ_SENT_NO_BOUNCE"},
            {"supplier":"Techbec","status":"PRIMARY_ADDRESS_BOUNCED_REROUTED_TO_INFO_PROJECT"},
        ],
        evidence_summary="Servotech replied and requested SAHJONY's contact number. Its reply provided corporate/direct sales numbers and confirmed the commercial conversation is live. Exicom and Lubi remain active; Techbec's primary sales address bounced and the RFQ was rerouted to alternate contacts.",
        next_action="Respond to Servotech with the business contact number, obtain UL/ETL/CSA or equivalent evidence, NACS/J3400/CCS1/J1772 support, OCPP/network capability, FOB/CIF pricing, loading, lead time and warranty; verify buyer entity and payment capability.",
        source_url="https://www.servotech.in/",
        evidence_urls=["https://www.exicom.com/","https://www.servotech.in/","https://www.lubievsolutions.com/"],
        created_at="2026-06-08T00:00:00+00:00",
        extra={"supplier_contacted_count":4,"supplier_effective_count":4,"supplier_reply_count":1,"supplier_delivery_failures":1,
            "possible_profit_status":"TARGET_ONLY","possible_profit_rate_pct":8,
            "possible_profit_period":"Initial 20-ft container",
            "possible_profit_basis":"8% supplier-side channel/referral commission requested; compliant SKU pricing and written protection are pending."},
    ),
    _deal(
        "ext_al_scrap_mombasa_20260727",
        "Aluminium 6063 extrusion / UBC scrap — Mombasa trial",
        "Metals / recycled commodities",
        "Aluminium 6063 extrusion scrap and/or UBC scrap for a 25-50 MT trial shipment to Mombasa, Kenya.",
        "KE",
        "Mombasa, Kenya",
        "supplier_sourcing",
        "medium",
        79,
        75,
        quantity=50,
        unit="metric tons max trial",
        incoterm="CFR Mombasa / FOB comparison",
        payment_terms="100% L/C at sight preferred",
        verification_status="supplier_sourcing_active",
        supplier_outreach=[
            {"supplier":"Nautica Metal Scrap B.V.","status":"RFQ_SENT"},
            {"supplier":"Sentosa Global Metal Trading","status":"RFQ_SENT"},
            {"supplier":"Gamma Metallurgy","status":"RFQ_SENT_NO_BOUNCE"},
            {"supplier":"EUROSCRAP","status":"RFQ_SENT_NO_BOUNCE"},
        ],
        evidence_summary="Four suppliers are in parallel competition. RFQs request CFR/FOB pricing, SGS/Bureau Veritas support, chemistry/specification evidence, stock proof, loading evidence and bank-secured terms.",
        next_action="Compare SCOs on delivered economics, chemistry, stock evidence, inspection, loading, lead time and L/C acceptance; verify buyer entity and destination/incoterm consistency before matching.",
        source_url="https://nauticametalscrap.com/aluminum-scrap-6063",
        created_at="2026-07-27T00:00:00+00:00",
        extra={"supplier_contacted_count":4,"supplier_effective_count":4,"supplier_reply_count":0,
            "possible_profit_status":"UNCONFIRMED_TARGET","possible_profit_min_usd":3750,
            "possible_profit_max_usd":7500,"possible_profit_period":"25–50 MT trial",
            "possible_profit_basis":"USD 150/MT requested supplier-side commission × 25–50 MT; supplier confirmation is pending."},
    ),
    _deal(
        "ext_soda_ash_korea_20260825",
        "South Korea buyer — Soda Ash Light 99.2% — 500 MT/month",
        "Industrial chemicals",
        "Active buyer requirement for Soda Ash Light, Na2CO3 99.2% minimum, approximately 500 MT per month, 50 kg packing, FOB China, L/C payment.",
        "KR",
        "South Korea",
        "supplier_sourcing",
        "medium",
        88,
        82,
        buyer_name="Chris Park",
        quantity=500,
        unit="metric tons/month",
        incoterm="FOB China",
        payment_terms="L/C",
        verification_status="buyer_contacted_supplier_sourcing",
        supplier_outreach=[
            {"supplier":"TNJ Chemical","status":"RFQ_SENT"},
            {"supplier":"YRC Export","status":"RFQ_SENT"},
        ],
        evidence_summary="Buyer outreach has been sent to Chris Park and supplier RFQs have been sent to TNJ Chemical and YRC Export for 500 MT/month Soda Ash Light 99.2%, 50 kg packing, FOB China, L/C.",
        next_action="Obtain supplier COA/specification, price per MT, monthly capacity, packing/loading, lead time and L/C acceptance; confirm buyer legal entity, destination port and issuing bank before commercial matching.",
        source_url="https://www.go4worldbusiness.com/",
        created_at="2026-08-25T01:06:45+00:00",
        extra={"supplier_contacted_count":2,"supplier_effective_count":2,"buyer_contacted":True,
            "possible_profit_status":"EVIDENCED_ESTIMATE","possible_profit_min_usd":420,
            "possible_profit_max_usd":630,"possible_profit_period":"42 MT controlled trial",
            "possible_profit_basis":"USD 10–15/MT margin × 42 MT; supplier net and buyer offer are evidenced, but buyer acceptance and collection are not.",
            "possible_profit_recurring_usd":7500,"possible_profit_recurring_period":"500 MT/month target at USD 15/MT"},
    ),
    _deal(
        "ext_uae_motors_20260825",
        "UAE buyer — AC/DC industrial motors — 20-ft container",
        "Industrial equipment",
        "Active UAE distribution requirement for approximately one 20-ft container of industrial AC/DC motors for retail/distribution applications.",
        "AE",
        "United Arab Emirates",
        "supplier_sourcing",
        "medium",
        81,
        72,
        quantity=1,
        unit="20-ft container",
        incoterm="FOB/CIF UAE requested",
        payment_terms="Commercial terms pending",
        verification_status="supplier_sourcing_active",
        supplier_outreach=[{"supplier":"Brook Crompton North America","status":"RFQ_SENT"}],
        evidence_summary="A direct RFQ was sent to Brook Crompton for a 20-ft container of AC/DC industrial motors for UAE distribution.",
        next_action="Obtain motor range, export pricing, container loading, certifications, lead time and warranty; verify UAE buyer entity, exact model mix, destination and payment instrument.",
        source_url="https://www.brookcrompton.com/",
        created_at="2026-08-25T01:06:11+00:00",
        extra={"supplier_contacted_count":1,"supplier_effective_count":1},
    ),
    _deal(
        "ext_jet_a1_dongil_20260824",
        "Jet A1 — Dongil Kim — 1-2 million barrels",
        "Energy / refined products",
        "Marketplace RFQ for Jet A1, HS 271019, 1-2 million barrels, CIF, L/C; destination wording is internally inconsistent: Rotterdam / South Korea.",
        "KR",
        "Destination clarification required — Rotterdam / South Korea",
        "enhanced_diligence",
        "high",
        67,
        48,
        buyer_name="Dongil Kim",
        quantity=2000000,
        unit="barrels max",
        incoterm="CIF",
        payment_terms="L/C",
        verification_status="marketplace_verified_only",
        evidence_summary="go4WorldBusiness distributed the requirement and described matching leads as called and verified. Marketplace verification is not full KYB; exact port, legal entity, authority, issuing bank and mandate remain unverified.",
        next_action="Obtain direct buyer connection, exact discharge port, legal entity, mandate, issuing bank/L/C capability, sanctions screening, specification, inspection and transaction protocol before any SCO or seller documents.",
        source_url="https://www.go4worldbusiness.com/buylead/view/1318637/wanted-%3A-fuel-like-a1-jet-fuel.html",
        created_at="2026-08-24T07:48:27+00:00",
        extra={"buyer_connection_requested":True},
    ),
    _deal(
        "ext_jet_a1_ali_top_20260825",
        "Jet A1 — Ali Top — 300,000 MT/month",
        "Energy / refined products",
        "Marketplace RFQ for Jet A1 under a 12-month contract, 300,000 MT monthly, CIF, irrevocable documentary L/C; destination wording is broad/ambiguous.",
        "US",
        "ASWP in Canada/Asia/etc. — exact port required",
        "enhanced_diligence",
        "high",
        64,
        44,
        buyer_name="Ali Top",
        quantity=300000,
        unit="metric tons/month",
        incoterm="CIF",
        payment_terms="Irrevocable documentary L/C",
        verification_status="marketplace_verified_only",
        next_action="Obtain legal entity, authorized mandate, exact discharge port, specification, issuing bank and documentary L/C procedure before seller matching or price release.",
        source_url="https://www.go4worldbusiness.com/",
        created_at="2026-08-25T03:38:52+00:00",
        extra={"buyer_connection_requested":True},
    ),
    _deal(
        "ext_jet_a1_nicola_ricciardi_20260825",
        "Jet A1 — Nicola Ricciardi — 1-2 million barrels",
        "Energy / refined products",
        "Marketplace RFQ for Jet A1, 1-2 million barrels, FOB ASWP/Houston, with L/C/MT103 language and terminal/title verification procedures.",
        "CA",
        "ASWP / Houston, United States",
        "enhanced_diligence",
        "high",
        62,
        42,
        buyer_name="Nicola Ricciardi",
        quantity=2000000,
        unit="barrels max",
        incoterm="FOB",
        payment_terms="L/C / MT103 stated",
        verification_status="marketplace_verified_only",
        next_action="Require full KYB, mandate/authority, terminal relationship evidence, exact specification, issuing-bank capability and coherent procedure before any seller matching.",
        source_url="https://www.go4worldbusiness.com/buylead/view/1305522/wanted-%3A-fuel-like-a1-jet-fuel.html",
        created_at="2026-08-25T03:38:52+00:00",
        extra={"buyer_connection_requested":True},
    ),
    _deal(
        "ext_indianoil_registration_20260824",
        "IndianOil — crude/petroleum approved-mailing-list onboarding",
        "Institutional energy counterparty onboarding",
        "Indian Oil Corporation Ltd. directly sent SAHJONY its registration package for approved mailing-list participation in crude oil/LPG and petroleum product tenders.",
        "IN",
        "India / IndianOil International Trade",
        "counterparty_onboarding",
        "medium",
        92,
        94,
        buyer_company="Indian Oil Corporation Ltd.",
        incoterm="Tender-specific",
        payment_terms="Tender-specific",
        verification_status="direct_institutional_correspondence",
        evidence_summary="Direct IndianOil correspondence requires principal-to-principal dealings, three years of physical trade volumes/values, audited financials, bank references, trade references, authorized-signatory documents and undertakings. SAHJONY requested a truthful eligibility clarification rather than fabricating history.",
        next_action="Await eligibility clarification; if eligible, assemble truthful corporate/financial/bank/reference/signatory documentation and complete official registration.",
        source_url="https://iocl.com/",
        created_at="2026-08-24T12:05:33+00:00",
    ),
]


def _mailbox(prospect_id: str, product: str, contact: str, created_at: str, country: str = "UN", detail: str | None = None) -> dict:
    return _deal(
        prospect_id,
        f"{product} — {contact}",
        "Marketplace buyer lead",
        detail or f"go4WorldBusiness buyer-feed requirement for {product}. Contact shown in the buyer feed: {contact}.",
        country,
        "Destination / exact port requires direct buyer confirmation",
        "research",
        "high" if any(k in product.lower() for k in ("crude", "jet", "diesel", "fuel", "lpg", "lng", "cng")) else "medium",
        58,
        45,
        buyer_name=contact,
        verification_status="marketplace_verified_only",
        evidence_summary=f"go4WorldBusiness delivered this buyer lead to SAHJONY and stated that matching inquiries were called and verified. This status is treated as marketplace-level verification only, not full KYB, mandate or bank verification.",
        next_action="Obtain direct buyer connection, legal entity, authority/mandate, exact quantity/specification/destination and payment capability before pricing or seller matching.",
        source_url="https://www.go4worldbusiness.com/",
        created_at=created_at,
        extra={"mailbox_feed":True},
    )


MAILBOX_BUY_LEADS = [
    _mailbox("mbx_lpg_lng_cng_richard_20260821","LPG / LNG / CNG","Richard Lee","2026-08-21T14:10:52+00:00"),
    _mailbox("mbx_light_crude_amit_20260821","Light Crude Oil Petroleum","Amit Sharma","2026-08-21T09:00:04+00:00"),
    _mailbox("mbx_light_crude_vincent_20260820","Light Crude Oil","Vincent Choi","2026-08-20T12:09:48+00:00"),
    _mailbox("mbx_jet_diesel_grant_20260820","Jet Fuel / Diesel EN590","Grant Chen","2026-08-20T06:38:12+00:00"),
    _mailbox("mbx_jet_harith_20260819","Jet A1 Fuel","Harith Rahimy","2026-08-19T10:24:57+00:00"),
    _mailbox("mbx_jet_peter_20260819","Jet A1 Fuel","Peter Lee","2026-08-19T09:22:27+00:00"),
    _mailbox("mbx_hfo_chuks_20260819","HFO Heavy Fuel","Chuks Otalor","2026-08-19T03:22:24+00:00"),
    _mailbox("mbx_jet_julio_20260817","Jet A1 Fuel","Julio Rivera","2026-08-17T02:59:48+00:00"),
    _mailbox("mbx_jet_walid_20260814","Jet Fuel A1","Walid","2026-08-14T12:48:30+00:00"),
    _mailbox("mbx_fuel_coke_cindy_20260814","Fuel Coke","Cindy Hu","2026-08-14T07:44:00+00:00"),
    _mailbox("mbx_jet_trial_20260814","Jet A1 Fuel","Marketplace buyer","2026-08-14T04:47:22+00:00", detail="ASTM D1655 Jet A1 requirement: 50,000 MT trial shipment, scaling to approximately 100,000-500,000 MT/month. Full buyer identity, destination, mandate and bank capability still require independent verification."),
    _mailbox("mbx_espo_james_20260813","ESPO Light Crude Oil","James Wong Kc","2026-08-13T10:28:50+00:00"),
    _mailbox("mbx_jet_james_20260813","Jet A1 Fuel","James Wong Kc","2026-08-13T09:32:57+00:00"),
    _mailbox("mbx_mineral_oil_alpa_20260810","Mineral Oil","Alpa Agrawal","2026-08-10T14:06:30+00:00"),
    _mailbox("mbx_jet_antonio_20260807","Jet A1 Fuel","Antonio","2026-08-07T12:36:18+00:00"),
    _mailbox("mbx_hsfo_henry_20260806","High Sulfur Fuel Oil","Henry","2026-08-06T13:19:15+00:00"),
    _mailbox("mbx_jet_kenner_20260806","Jet A1 Fuel","Kenner Rogers","2026-08-06T04:36:54+00:00"),
    _mailbox("mbx_silicone_norman_20260805","Silicone Oil","Norman","2026-08-05T12:47:49+00:00"),
    _mailbox("mbx_crude_kenner_20260805","Crude Oil","Kenner Rogers","2026-08-05T03:58:14+00:00"),
    _mailbox("mbx_used_crude_dipak_20260804","Used Crude Oil","Dipak Verma","2026-08-04T04:45:52+00:00"),
    _mailbox("mbx_jet_odiljon_20260803","Jet A1 Fuel","Odiljon","2026-08-03T09:34:29+00:00"),
    _mailbox("mbx_jet_guillermo_20260803","Jet A1 Fuel","Guillermo Diaz","2026-08-03T03:42:22+00:00"),
    _mailbox("mbx_d6_jorge_20260731","D6 Diesel","Jorge Barrera Hinojosa","2026-07-31T02:53:08+00:00"),
    _mailbox("mbx_crude_robert_20260730","Crude Oil","Robert Johnston","2026-07-30T15:23:34+00:00"),
    _mailbox("mbx_jet_abdul_shittu_20260730","Jet Fuel","Mr. Abdul Shittu","2026-07-30T13:44:29+00:00"),
    _mailbox("mbx_d6_berish_20260729","D6 Diesel","Berish Brauner","2026-07-29T03:12:55+00:00"),
    _mailbox("mbx_jet_genesis_20260729","Jet A1 Fuel","Genesis","2026-07-29T02:15:45+00:00"),
    _mailbox("mbx_lsfo_uwe_20260728","Low Sulphur Fuel Oil","Uwe Halliger","2026-07-28T16:53:42+00:00"),
    _mailbox("mbx_ldo_abdul_20260728","Light Diesel Oil (LDO)","Abdul Rasaq","2026-07-28T14:40:42+00:00"),
    _mailbox("mbx_base_oil_alaa_20260727","Base Oil","Eng Alaa","2026-07-27T14:14:53+00:00"),
    _mailbox("mbx_light_crude_mahdi_20260727","Light Crude Oil","Mahdi","2026-07-27T13:04:06+00:00"),
]


async def sync_execution_snapshot(backend) -> dict:
    inserted = 0
    updated = 0
    failures: list[str] = []
    rows = EXECUTION_SNAPSHOT + MAILBOX_BUY_LEADS
    for raw in rows:
        try:
            prospect_id = str(raw["prospect_id"])
            existing = await backend.select("external_trade_prospects", params={"prospect_id": f"eq.{prospect_id}", "limit": "1"}) or []
            row = dict(existing[0]) if existing else {}
            row.update(raw)
            row["organization_id"] = ORG_ID
            row["created_at"] = row.get("created_at") or raw.get("created_at") or now()
            row["updated_at"] = now()
            await backend.insert("external_trade_prospects", row)
            updated += 1 if existing else 0
            inserted += 0 if existing else 1
        except Exception as exc:
            failures.append(f"{raw.get('prospect_id')}: {type(exc).__name__}: {str(exc)[:180]}")
    return {"status":"ok" if not failures else "partial","expected":len(rows),"inserted":inserted,"updated":updated,"failed":len(failures),"failures":failures,"canonical_database":"active_vercel_database_url"}


def priority_tier(row: dict) -> str:
    explicit = str(row.get("revenue_priority_tier") or "").strip().upper()
    if explicit:
        return explicit
    score = int(row.get("opportunity_score") or 0)
    risk = str(row.get("risk_level") or "medium").lower()
    if score >= 80 and risk != "high": return "A"
    if score >= 70 and risk != "high": return "A-"
    return "B"


def _risk_from_score(row: dict) -> str:
    explicit = str(row.get("risk_level") or "").strip().lower()
    if explicit in {"low","medium","high"}: return explicit
    confidence = int(row.get("confidence") or 0)
    if confidence >= 80: return "low"
    if confidence >= 55: return "medium"
    return "high"


def _project_research_lead(row: dict) -> dict:
    code = str(row.get("country") or row.get("country_department") or "UN").upper()
    lead_type = str(row.get("lead_type") or row.get("deal_side") or "OTHER").upper()
    need = str(row.get("product_need_or_offer") or "").strip()
    company = str(row.get("business_name") or "External trade prospect").strip()
    return {
        "prospect_id": row.get("lead_id"),
        "organization_id": ORG_ID,
        "opportunity_title": f"{company} · {lead_type.replace('_',' ').title()}",
        "product_description": need,
        "product_category": row.get("product_category"),
        "buyer_name": row.get("contact_name"),
        "buyer_company": company,
        "buyer_country": code,
        "destination": row.get("city_region") or code,
        "email": row.get("email"),
        "phone": row.get("phone"),
        "quantity": row.get("quantity"),
        "unit": row.get("unit"),
        "incoterm": row.get("incoterm"),
        "payment_terms": row.get("payment_terms"),
        "source_url": row.get("source_url"),
        "source_description": row.get("source_description"),
        "evidence_urls": row.get("evidence_urls") or [],
        "evidence_summary": row.get("source_description") or need,
        "notes": row.get("notes"),
        "verification_status": "unverified",
        "qualification_stage": str(row.get("status") or "research").lower(),
        "risk_level": _risk_from_score(row),
        "confidence": row.get("confidence"),
        "opportunity_score": row.get("opportunity_score"),
        "lead_type": lead_type,
        "deal_side": row.get("deal_side"),
        "scout_code": row.get("scout_code"),
        "lead_search_job_id": row.get("lead_search_job_id"),
        "next_action": "Independently verify identity, authority, active commercial need, sanctions/compliance posture and payment capability before promotion or outreach authority.",
        "possible_profit_status": "INPUTS_REQUIRED",
        "possible_profit_basis": "Supplier cost, buyer price and protected SAHJONY compensation are not yet evidenced.",
        "possible_profit_min_usd": None,
        "possible_profit_max_usd": None,
        "possible_profit_period": None,
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "source_record": "lead_scout_leads",
    }


@app.get("/crm/external-prospects/health")
async def external_prospects_health():
    backend = get_backend()
    sync = await sync_execution_snapshot(backend)
    researched = await backend.select("lead_scout_leads", params={"limit":"5000"}) or []
    curated = await backend.select("external_trade_prospects", params={"organization_id":f"eq.{ORG_ID}","limit":"5000"}) or []
    return {
        "status":"ok" if sync["failed"] == 0 else "degraded",
        "service":"external-trade-prospects",
        "scope":"research_only",
        "promotion":"fail_closed",
        "customer_intake_isolation":True,
        "research_pipeline_connected":True,
        "all_lead_scout_records_visible":True,
        "possible_profit_projection":True,
        "possible_profit_is_not_booked_revenue":True,
        "execution_snapshot_records":len(EXECUTION_SNAPSHOT),
        "mailbox_buy_lead_records":len(MAILBOX_BUY_LEADS),
        "lead_scout_record_count":len(researched),
        "curated_record_count":len(curated),
        "sync":sync,
        "sources":["external_trade_prospects","lead_scout_leads","live_execution_snapshot","gmail_go4worldbusiness_feed"],
    }


@app.get("/crm/external-prospects")
async def list_external_prospects(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = identity(x_role, authorization, x_employee_id)
    backend = get_backend()
    sync = await sync_execution_snapshot(backend)
    curated = await backend.select("external_trade_prospects", params={"organization_id":f"eq.{ORG_ID}","order":"created_at.desc","limit":"5000"}) or []
    researched = await backend.select("lead_scout_leads", params={"order":"created_at.desc","limit":"5000"}) or []

    prospects: list[dict] = []
    seen: set[str] = set()
    for row in curated:
        item = dict(row)
        key = str(item.get("prospect_id") or item.get("source_url") or item.get("opportunity_title") or "")
        if key and key in seen: continue
        if key: seen.add(key)
        item["revenue_priority_tier"] = priority_tier(item)
        item["record_type"] = "EXTERNAL_RESEARCH"
        item["customer_intake"] = False
        prospects.append(item)

    # Expose every lead-scout book: energy core, global energy, worldwide trade,
    # mid-market oil-dependent, Cuba MIPYME and AI-researched records.
    for row in researched:
        item = _project_research_lead(dict(row))
        key = str(item.get("prospect_id") or item.get("source_url") or item.get("opportunity_title") or "")
        if key and key in seen: continue
        if key: seen.add(key)
        item["revenue_priority_tier"] = priority_tier(item)
        item["record_type"] = "EXTERNAL_RESEARCH"
        item["customer_intake"] = False
        prospects.append(item)

    prospects.sort(key=lambda item: str(item.get("created_at") or item.get("updated_at") or ""), reverse=True)
    return {
        "status":"ok",
        "scope":actor["role"],
        "research_only":True,
        "customer_intake_isolation":True,
        "all_lead_books_visible":True,
        "count":len(prospects),
        "curated_count":len(curated),
        "research_lead_count":len(researched),
        "execution_sync":sync,
        "prospects":prospects,
    }
