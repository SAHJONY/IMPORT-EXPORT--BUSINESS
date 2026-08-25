from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, Header

from customer_crm_api import identity
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY External Trade Prospects", version="1.2.0", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


EXECUTION_SNAPSHOT = [
    {
        "prospect_id": "ext_oman_motors_20260519",
        "organization_id": ORG_ID,
        "opportunity_title": "Oman buyer — AC/DC industrial motors",
        "product_category": "Industrial equipment",
        "product_description": "AC/DC industrial motors for one 20-ft container; model mix and final technical specification still require buyer confirmation.",
        "buyer_country": "OM",
        "destination": "Oman",
        "quantity": 1,
        "unit": "20-ft container",
        "incoterm": "FOB/CIF Oman requested",
        "payment_terms": "L/C requested",
        "verification_status": "supplier_sourcing_active",
        "qualification_stage": "supplier_sourcing",
        "risk_level": "medium",
        "confidence": 72,
        "opportunity_score": 84,
        "revenue_priority_tier": "A",
        "supplier_contacted_count": 4,
        "supplier_effective_count": 3,
        "supplier_delivery_failures": 1,
        "supplier_outreach": [
            {"supplier": "Bharat Bijlee", "status": "RFQ_SENT"},
            {"supplier": "CG Power", "status": "BOUNCED_550"},
            {"supplier": "ABB India", "status": "RFQ_SENT_NO_BOUNCE"},
            {"supplier": "WEG India", "status": "RFQ_SENT_NO_BOUNCE"},
        ],
        "evidence_summary": "RFQs sent to Bharat Bijlee, ABB India and WEG India. Earlier CG Power address returned a 550 delivery failure and is excluded from effective supplier coverage. Three active manufacturers remain in competition.",
        "next_action": "Collect model ranges, certifications, 20-ft loading, FOB/CIF Oman pricing, lead time and warranty from the three active manufacturers; independently verify buyer legal entity, purchasing authority and L/C capability before requesting binding model-level pricing.",
        "source_url": "https://www.bharatbijlee.com/",
        "evidence_urls": ["https://www.bharatbijlee.com/", "https://global.abb/group/en", "https://www.weg.net/"],
        "source_record": "live_execution_snapshot",
        "created_at": "2026-05-19T00:00:00+00:00",
        "updated_at": "2026-08-25T04:23:00+00:00",
    },
    {
        "prospect_id": "ext_us_ev_chargers_20260608",
        "organization_id": ORG_ID,
        "opportunity_title": "U.S./Canada buyer — DC and AC EV chargers",
        "product_category": "EV infrastructure",
        "product_description": "AC/DC EV charging equipment for one 20-ft container; North American certifications and final power/connector/network requirements are gating items.",
        "buyer_country": "US",
        "destination": "United States / Canada",
        "quantity": 1,
        "unit": "20-ft container",
        "incoterm": "FOB/CIF requested",
        "payment_terms": "Commercial terms pending",
        "verification_status": "supplier_sourcing_active",
        "qualification_stage": "supplier_sourcing",
        "risk_level": "medium",
        "confidence": 70,
        "opportunity_score": 83,
        "revenue_priority_tier": "A",
        "supplier_contacted_count": 4,
        "supplier_effective_count": 4,
        "supplier_delivery_failures": 0,
        "supplier_outreach": [
            {"supplier": "Exicom", "status": "RFQ_SENT"},
            {"supplier": "Servotech", "status": "RFQ_SENT"},
            {"supplier": "Lubi EV Solutions", "status": "RFQ_SENT_NO_BOUNCE"},
            {"supplier": "Techbec", "status": "RFQ_SENT_NO_BOUNCE"},
        ],
        "evidence_summary": "Four manufacturers are now in the sourcing queue: Exicom, Servotech, Lubi EV Solutions and Techbec. No delivery-failure notices have been received for these RFQs. North American certification evidence is mandatory before commercial advancement.",
        "next_action": "Obtain certified-model evidence (cUL/cETL/cTUVus or equivalent applicable approval), OCPP/network support, pricing, container loading, lead time and warranty; verify buyer entity, exact destination, power ratings, connectors and payment capability before binding order terms.",
        "source_url": "https://www.exicom.com/",
        "evidence_urls": ["https://www.exicom.com/", "https://www.servotech.in/", "https://www.lubievsolutions.com/"],
        "source_record": "live_execution_snapshot",
        "created_at": "2026-06-08T00:00:00+00:00",
        "updated_at": "2026-08-25T04:23:00+00:00",
    },
    {
        "prospect_id": "ext_al_scrap_mombasa_20260727",
        "organization_id": ORG_ID,
        "opportunity_title": "Aluminium 6063 extrusion / UBC scrap — Mombasa trial",
        "product_category": "Metals / recycled commodities",
        "product_description": "Aluminium 6063 extrusion scrap and/or UBC scrap for a 25-50 MT trial shipment to Mombasa, Kenya.",
        "buyer_country": "KE",
        "destination": "Mombasa, Kenya",
        "quantity": 50,
        "unit": "metric tons max trial",
        "incoterm": "CFR Mombasa / FOB comparison",
        "payment_terms": "100% L/C at sight preferred",
        "verification_status": "supplier_sourcing_active",
        "qualification_stage": "supplier_sourcing",
        "risk_level": "medium",
        "confidence": 75,
        "opportunity_score": 79,
        "revenue_priority_tier": "A-",
        "supplier_contacted_count": 4,
        "supplier_effective_count": 4,
        "supplier_delivery_failures": 0,
        "supplier_outreach": [
            {"supplier": "Nautica Metal Scrap B.V.", "status": "RFQ_SENT"},
            {"supplier": "Sentosa Global Metal Trading", "status": "RFQ_SENT"},
            {"supplier": "Gamma Metallurgy", "status": "RFQ_SENT_NO_BOUNCE"},
            {"supplier": "EUROSCRAP", "status": "RFQ_SENT_NO_BOUNCE"},
        ],
        "evidence_summary": "Four suppliers are in parallel RFQ competition for the 25-50 MT trial. Requests require CFR/FOB pricing, SGS or Bureau Veritas inspection support, chemistry/specification evidence, stock proof and bank-secured payment terms.",
        "next_action": "Compare SCOs on delivered economics, chemistry, stock evidence, inspection, loading photos/video, lead time and L/C acceptance; independently verify buyer legal entity and destination/incoterm consistency before matching.",
        "source_url": "https://nauticametalscrap.com/aluminum-scrap-6063",
        "evidence_urls": ["https://nauticametalscrap.com/aluminum-scrap-6063", "https://gammametallurgy.com/"],
        "source_record": "live_execution_snapshot",
        "created_at": "2026-07-27T00:00:00+00:00",
        "updated_at": "2026-08-25T04:23:00+00:00",
    },
    {
        "prospect_id": "ext_jet_a1_dongil_20260824",
        "organization_id": ORG_ID,
        "opportunity_title": "Jet A1 — Dongil Kim — 1-2 million barrels",
        "product_category": "Energy / refined products",
        "product_description": "Marketplace RFQ for Jet A1, HS 271019, 1-2 million barrels, CIF, L/C. Listing identifies buyer as Dongil Kim and contains an internally inconsistent destination description: Rotterdam and South Korea.",
        "buyer_name": "Dongil Kim",
        "buyer_country": "KR",
        "destination": "Destination clarification required — listing says Rotterdam / South Korea",
        "quantity": 2000000,
        "unit": "barrels max",
        "incoterm": "CIF",
        "payment_terms": "L/C",
        "verification_status": "marketplace_verified_only",
        "qualification_stage": "enhanced_diligence",
        "risk_level": "high",
        "confidence": 48,
        "opportunity_score": 67,
        "revenue_priority_tier": "B",
        "buyer_connection_requested": True,
        "evidence_summary": "go4WorldBusiness distributed the requirement on August 24, 2026 and described its matching leads as called and verified. Marketplace verification is not treated as full KYB. Exact discharge port, buyer entity, authority, issuing bank and mandate remain unverified.",
        "next_action": "Obtain direct buyer connection and clarify exact discharge port; verify legal entity, mandate, issuing bank/L/C capability, sanctions exposure, product specification, inspection procedure and transaction protocol before any SCO, seller identity or banking document is released.",
        "source_url": "https://www.go4worldbusiness.com/buylead/view/1318637/wanted-%3A-fuel-like-a1-jet-fuel.html",
        "evidence_urls": ["https://www.go4worldbusiness.com/buylead/view/1318637/wanted-%3A-fuel-like-a1-jet-fuel.html"],
        "source_record": "live_execution_snapshot",
        "created_at": "2026-08-24T07:48:27+00:00",
        "updated_at": "2026-08-25T04:23:00+00:00",
    },
    {
        "prospect_id": "ext_jet_a1_ali_top_20260825",
        "organization_id": ORG_ID,
        "opportunity_title": "Jet A1 — Ali Top — 300,000 MT monthly",
        "product_category": "Energy / refined products",
        "product_description": "Marketplace RFQ for Jet A1 under a 12-month contract, 300,000 MT monthly, CIF, irrevocable documentary L/C. Destination wording is broad and commercially ambiguous.",
        "buyer_name": "Ali Top",
        "buyer_country": "US",
        "destination": "ASWP in Canada, Asia, etc. / United States — exact port required",
        "quantity": 300000,
        "unit": "metric tons/month",
        "incoterm": "CIF",
        "payment_terms": "Irrevocable documentary L/C",
        "verification_status": "marketplace_verified_only",
        "qualification_stage": "enhanced_diligence",
        "risk_level": "high",
        "confidence": 44,
        "opportunity_score": 64,
        "revenue_priority_tier": "B",
        "buyer_connection_requested": True,
        "evidence_summary": "go4WorldBusiness distributed this requirement on August 25, 2026. Quantity and contract duration are material, but destination language is too vague for responsible pricing or seller matching without direct KYB and bank verification.",
        "next_action": "Obtain buyer legal entity, authorized signatory/mandate evidence, exact discharge port, specification, issuing bank details and documentary L/C procedure; do not release seller documents or pricing until independent verification is complete.",
        "source_url": "https://www.go4worldbusiness.com/",
        "evidence_urls": ["https://www.go4worldbusiness.com/"],
        "source_record": "live_execution_snapshot",
        "created_at": "2026-08-25T03:38:52+00:00",
        "updated_at": "2026-08-25T04:23:00+00:00",
    },
    {
        "prospect_id": "ext_jet_a1_nicola_ricciardi_20260825",
        "organization_id": ORG_ID,
        "opportunity_title": "Jet A1 — Nicola Ricciardi — 1-2 million barrels",
        "product_category": "Energy / refined products",
        "product_description": "Marketplace RFQ for Jet A1, 1-2 million barrels, FOB, ASWP/Houston, with L/C and MT103 language plus terminal verification, Q&Q and title/injection procedure requirements.",
        "buyer_name": "Nicola Ricciardi",
        "buyer_country": "CA",
        "destination": "ASWP / Houston, United States",
        "quantity": 2000000,
        "unit": "barrels max",
        "incoterm": "FOB",
        "payment_terms": "L/C / MT103 stated",
        "verification_status": "marketplace_verified_only",
        "qualification_stage": "enhanced_diligence",
        "risk_level": "high",
        "confidence": 42,
        "opportunity_score": 62,
        "revenue_priority_tier": "B",
        "buyer_connection_requested": True,
        "evidence_summary": "The marketplace feed shows a large FOB Jet A1 requirement with an extensive terminal/title verification procedure. Repeated large fuel requirements increase commercial interest but do not establish buyer authority, terminal control, bank capability or a valid mandate.",
        "next_action": "Require full KYB, mandate/authority, terminal relationship evidence, exact product specification, issuing bank capability and a commercially coherent transaction procedure before matching to any seller or releasing sensitive documents.",
        "source_url": "https://www.go4worldbusiness.com/buylead/view/1305522/wanted-%3A-fuel-like-a1-jet-fuel.html",
        "evidence_urls": ["https://www.go4worldbusiness.com/buylead/view/1305522/wanted-%3A-fuel-like-a1-jet-fuel.html"],
        "source_record": "live_execution_snapshot",
        "created_at": "2026-08-25T03:38:52+00:00",
        "updated_at": "2026-08-25T04:23:00+00:00",
    },
    {
        "prospect_id": "ext_indianoil_registration_20260824",
        "organization_id": ORG_ID,
        "opportunity_title": "IndianOil — crude/petroleum approved-mailing-list onboarding",
        "product_category": "Institutional energy counterparty onboarding",
        "product_description": "Indian Oil Corporation Ltd. directly sent SAHJONY its registration form and required undertakings for approved mailing-list participation in crude oil/LPG and petroleum product tenders.",
        "buyer_company": "Indian Oil Corporation Ltd.",
        "buyer_country": "IN",
        "destination": "India / IndianOil International Trade",
        "incoterm": "Tender-specific",
        "payment_terms": "Tender-specific",
        "verification_status": "direct_institutional_correspondence",
        "qualification_stage": "counterparty_onboarding",
        "risk_level": "medium",
        "confidence": 92,
        "opportunity_score": 88,
        "revenue_priority_tier": "A",
        "evidence_summary": "IndianOil's International Trade team directly provided the registration package. The form requires principal-to-principal dealings, three years of physical trade volumes/values, audited financial statements, bank references, trade references, authorized-signatory documents and supporting undertakings. SAHJONY has asked whether a newer U.S. trading company without three completed years of petroleum physical-trade history can qualify rather than fabricating history.",
        "next_action": "Await IndianOil eligibility clarification. If eligible, assemble only truthful corporate, financial, bank, trade-reference and authorized-signatory documentation and complete the official registration package; if the three-year history requirement is mandatory, pursue the appropriate institutional route without misrepresentation.",
        "source_url": "https://iocl.com/",
        "evidence_urls": ["https://iocl.com/"],
        "source_record": "live_execution_snapshot",
        "created_at": "2026-08-24T12:05:33+00:00",
        "updated_at": "2026-08-25T04:23:00+00:00",
    },
]


async def sync_execution_snapshot(backend) -> dict:
    inserted = 0
    updated = 0
    failures: list[str] = []
    for raw in EXECUTION_SNAPSHOT:
        try:
            prospect_id = str(raw["prospect_id"])
            existing = await backend.select(
                "external_trade_prospects",
                params={"prospect_id": f"eq.{prospect_id}", "limit": "1"},
            ) or []
            row = dict(existing[0]) if existing else {}
            row.update(raw)
            row["organization_id"] = ORG_ID
            row["created_at"] = row.get("created_at") or raw.get("created_at") or now()
            row["updated_at"] = now()
            await backend.insert("external_trade_prospects", row)
            if existing:
                updated += 1
            else:
                inserted += 1
        except Exception as exc:
            failures.append(f"{raw.get('prospect_id')}: {type(exc).__name__}: {str(exc)[:180]}")
    return {
        "status": "ok" if not failures else "partial",
        "expected": len(EXECUTION_SNAPSHOT),
        "inserted": inserted,
        "updated": updated,
        "failed": len(failures),
        "failures": failures,
        "canonical_database": "active_vercel_database_url",
    }


def priority_tier(row: dict) -> str:
    explicit = str(row.get("revenue_priority_tier") or "").strip().upper()
    if explicit:
        return explicit
    score = int(row.get("opportunity_score") or 0)
    title = str(row.get("opportunity_title") or row.get("product_need_or_offer") or "").lower()
    risk = str(row.get("risk_level") or "medium").lower()
    quantity = float(row.get("quantity") or 0)
    if score >= 80 or "motor" in title or "charger" in title:
        return "A"
    if score >= 70 or "rmg-380" in title or "lsfo" in title:
        return "A-POTENTIAL"
    if score >= 55 or (quantity >= 25 and risk != "high"):
        return "A-"
    return "B"


def _risk_from_score(row: dict) -> str:
    explicit = str(row.get("risk_level") or "").strip().lower()
    if explicit in {"low", "medium", "high"}:
        return explicit
    confidence = int(row.get("confidence") or 0)
    if confidence >= 80:
        return "low"
    if confidence >= 55:
        return "medium"
    return "high"


def _project_research_lead(row: dict) -> dict:
    code = str(row.get("country") or row.get("country_department") or "").upper()
    lead_type = str(row.get("lead_type") or "OTHER").upper()
    need = str(row.get("product_need_or_offer") or "").strip()
    company = str(row.get("business_name") or "External trade prospect").strip()
    return {
        "prospect_id": row.get("lead_id"),
        "organization_id": ORG_ID,
        "opportunity_title": f"{company} · {lead_type.replace('_', ' ').title()}",
        "product_description": need,
        "buyer_name": row.get("contact_name"),
        "buyer_company": company,
        "buyer_country": code,
        "destination": row.get("city_region") or code,
        "quantity": None,
        "unit": None,
        "incoterm": None,
        "payment_terms": None,
        "source_url": row.get("source_url"),
        "evidence_urls": row.get("evidence_urls") or [],
        "verification_status": "unverified",
        "qualification_stage": "research",
        "risk_level": _risk_from_score(row),
        "confidence": row.get("confidence"),
        "opportunity_score": row.get("opportunity_score"),
        "lead_type": lead_type,
        "lead_search_job_id": row.get("lead_search_job_id"),
        "next_action": "Independently verify identity, authority, active commercial need and payment capability before promotion.",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "source_record": "lead_scout_leads",
    }


@app.get("/crm/external-prospects/health")
async def external_prospects_health():
    return {
        "status": "ok",
        "service": "external-trade-prospects",
        "scope": "research_only",
        "promotion": "fail_closed",
        "customer_intake_isolation": True,
        "research_pipeline_connected": True,
        "execution_snapshot_records": len(EXECUTION_SNAPSHOT),
        "sources": ["external_trade_prospects", "lead_scout_leads", "live_execution_snapshot"],
    }


@app.get("/crm/external-prospects")
async def list_external_prospects(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = identity(x_role, authorization, x_employee_id)
    backend = get_backend()
    execution_sync = await sync_execution_snapshot(backend)

    curated = await backend.select(
        "external_trade_prospects",
        params={"organization_id": f"eq.{ORG_ID}", "order": "created_at.desc", "limit": "500"},
    ) or []
    researched = await backend.select(
        "lead_scout_leads",
        params={"order": "created_at.desc", "limit": "500"},
    ) or []

    prospects: list[dict] = []
    seen: set[str] = set()

    for row in curated:
        item = dict(row)
        key = str(item.get("prospect_id") or item.get("source_url") or item.get("opportunity_title") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        item["revenue_priority_tier"] = priority_tier(item)
        item["record_type"] = "EXTERNAL_RESEARCH"
        item["customer_intake"] = False
        item["source_record"] = item.get("source_record") or "external_trade_prospects"
        prospects.append(item)

    for row in researched:
        if not row.get("lead_search_job_id") and str(row.get("scout_code") or "").upper().find("AI-") != 0:
            continue
        item = _project_research_lead(dict(row))
        key = str(item.get("prospect_id") or item.get("source_url") or item.get("opportunity_title") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        item["revenue_priority_tier"] = priority_tier(item)
        item["record_type"] = "EXTERNAL_RESEARCH"
        item["customer_intake"] = False
        prospects.append(item)

    prospects.sort(key=lambda item: str(item.get("created_at") or item.get("updated_at") or ""), reverse=True)
    return {
        "status": "ok",
        "scope": actor["role"],
        "research_only": True,
        "customer_intake_isolation": True,
        "count": len(prospects),
        "curated_count": len(curated),
        "research_lead_count": len([p for p in prospects if p.get("source_record") == "lead_scout_leads"]),
        "execution_snapshot_count": len([p for p in prospects if p.get("source_record") == "live_execution_snapshot"]),
        "execution_sync": execution_sync,
        "prospects": prospects,
    }
