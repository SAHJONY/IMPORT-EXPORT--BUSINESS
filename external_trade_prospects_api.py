from __future__ import annotations

from fastapi import FastAPI, Header

from customer_crm_api import identity
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY External Trade Prospects", version="1.1.0", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"


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
        "sources": ["external_trade_prospects", "lead_scout_leads"],
    }


@app.get("/crm/external-prospects")
async def list_external_prospects(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = identity(x_role, authorization, x_employee_id)
    backend = get_backend()

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
        # Only Country AI / research-generated leads belong on this surface.
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
        "prospects": prospects,
    }
