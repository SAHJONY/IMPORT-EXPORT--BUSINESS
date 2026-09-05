from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token
from insforge_backend import get_backend
from crm_quality_10x_api import assess_record, _company, _has_contact, _has_need, _is_mipyme, _verified

app = FastAPI(title="SOFIA Super Proactive Sales OS", version="1.0.0", docs_url=None, redoc_url=None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _auth(role: str | None, authorization: str | None, employee_id: str | None):
    if role not in {"owner", "employee"}:
        raise HTTPException(400, "X-Role must be owner or employee")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if role == "owner":
        if not verify_owner_token(token):
            raise HTTPException(403, "Invalid owner credential")
        return {"role": "owner", "id": "owner"}
    configured = os.getenv("EMPLOYEE_TOKEN", "").strip()
    if not configured or not secrets.compare_digest(token, configured):
        raise HTTPException(403, "Invalid employee credential")
    return {"role": "employee", "id": (employee_id or "staff")[:160]}


def _text(*values: Any) -> str:
    return " ".join(str(v or "").strip() for v in values if str(v or "").strip()).strip()


def _ref(r: dict) -> str:
    return str(r.get("customer_id") or r.get("prospect_id") or r.get("external_reference") or r.get("_record_key") or r.get("id") or "unknown")


def _activity(r: dict) -> str:
    return _text(r.get("primary_activity"), r.get("activity"), r.get("product_category"), r.get("business_type"))[:500]


def _priority_score(r: dict, assessment: dict) -> int:
    score = int(assessment.get("score") or 0)
    if _has_contact(r): score += 8
    if _has_need(r): score += 15
    if _verified(r): score += 10
    if _text(r.get("target_budget"), r.get("target_price"), r.get("quantity"), r.get("requested_quantity")): score += 6
    if _text(r.get("supplier_id"), r.get("supplier_company"), r.get("best_supplier")): score += 8
    if str(r.get("capital_at_risk_usd") or "0") in {"0", "0.0", "", "None"}: score += 5
    return min(score, 100)


def _stage(r: dict, assessment: dict) -> str:
    checks = assessment.get("checks") or {}
    if checks.get("current_need") and checks.get("quantity_or_volume") and checks.get("kyb_verified"):
        if checks.get("supplier_match") and checks.get("commercial_economics"):
            return "COMMERCIAL_VALIDATION"
        return "QUALIFIED_DEMAND"
    if _has_contact(r):
        return "CONTACTABLE"
    return "RESEARCH"


def _next_action(r: dict, assessment: dict) -> tuple[str, str]:
    checks = assessment.get("checks") or {}
    if not checks.get("contactability"):
        return (
            "RESEARCH_ENRICHMENT",
            "Find a legitimate public business contact and current operating evidence using fallback research sources; do not ask the owner to supply the lead.",
        )
    if not checks.get("current_need"):
        return (
            "NEED_DISCOVERY",
            "Prepare a sector-specific discovery pitch focused on current product/service need, quantity, destination and timing; send only through an approved/consented outreach channel.",
        )
    if not checks.get("quantity_or_volume"):
        return ("RFQ_COMPLETION", "Confirm exact quantity/volume, specification, destination and requested shipment date.")
    if not checks.get("kyb_verified"):
        return ("KYB", "Validate business identity, authorized representative and applicable restricted-party/compliance checks before commercial promotion.")
    if not checks.get("supplier_match"):
        return ("SUPPLIER_MATCH", "Match at least three qualified suppliers and obtain comparable current non-binding commercial terms.")
    if not checks.get("commercial_economics"):
        return ("ECONOMICS", "Model supplier cost, freight, fees, risk reserve and protected SAHJONY margin against competition benchmarks.")
    return ("DEAL_ADVANCE", "Advance through the governed Deal Room with fee protection, payment path, logistics path and non-binding controls.")


def _pitch(r: dict) -> str:
    company = _company(r)
    activity = _activity(r) or "su actividad comercial"
    return (
        f"SOFIA personalized discovery for {company}: based on {activity}, identify the products, services or inputs "
        "the business needs now, the quantity, destination and timing. Present SAHJONY as a verified global sourcing and trade "
        "orchestration partner able to compare suppliers, pricing, quality and logistics. Do not promise savings, availability, "
        "credit, delivery dates or revenue until supported by current evidence."
    )


async def _load_records():
    b = get_backend()
    accounts = await b.select("customer_accounts", params={"limit": "5000"}) or []
    try:
        external = await b.select("external_trade_prospects", params={"organization_id": "eq.org_sahjony_global_trade", "limit": "5000"}) or []
    except Exception:
        external = []
    try:
        intakes = await b.select("customer_trade_intakes", params={"limit": "5000"}) or []
    except Exception:
        intakes = []
    return accounts, external, intakes


def _build_queue(records: list[dict], limit: int = 100):
    queue = []
    for r in records:
        a = assess_record(r)
        action_type, action = _next_action(r, a)
        queue.append({
            "record_ref": _ref(r),
            "company": _company(r),
            "country": r.get("country") or r.get("country_code"),
            "province": r.get("province"),
            "municipality": r.get("municipality"),
            "activity": _activity(r),
            "commercial_stage": _stage(r, a),
            "maturity_score": a.get("score", 0),
            "proactivity_score": _priority_score(r, a),
            "next_action_type": action_type,
            "next_best_action": action,
            "why_now": "Prioritized by evidence, contactability, demand readiness, supplier fit and speed-to-revenue potential.",
            "personalized_pitch_brief": _pitch(r),
            "owner_dependency": False,
            "fee_protection_required": True,
            "zero_own_capital_preferred": True,
            "binding_commitments_allowed": False,
            "autonomous_promotional_send_allowed": False,
            "outreach_rule": "Use approved/consented business channels only; research and preparation remain autonomous.",
        })
    queue.sort(key=lambda x: (x["proactivity_score"], x["maturity_score"]), reverse=True)
    return queue[: max(1, min(limit, 500))]


@app.get("/crm/sofia-proactive/health")
async def health():
    return {
        "status": "ok",
        "service": "sofia-super-proactive-sales-os",
        "version": "1.0.0",
        "mode": "AUTONOMOUS_NONBINDING_CONSENT_GATED",
        "sofia_super_proactive_sales_os": True,
        "autonomous_research_loops": True,
        "owner_dependency_for_research": False,
        "personalized_pitch_engine": True,
        "follow_the_sun_sales_queue": True,
        "mipyme_cross_trade_matching": True,
        "supplier_matching": True,
        "competition_benchmarking": True,
        "fee_protection_gate": True,
        "zero_own_capital_preferred": True,
        "binding_commitments": False,
        "bulk_unsolicited_outreach": False,
        "revenue_inference": False,
    }


@app.get("/crm/sofia-proactive/queue")
async def queue(
    limit: int = 100,
    cuba_only: bool = False,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    _auth(x_role, authorization, x_employee_id)
    accounts, external, intakes = await _load_records()
    records = accounts + external
    if cuba_only:
        records = [r for r in records if str(r.get("country") or r.get("country_code") or "").upper() in {"CUBA", "CU", "CUB"}]
    q = _build_queue(records, limit)
    return {
        "status": "ok",
        "generated_at": _now().isoformat(),
        "records_loaded": len(records),
        "customer_trade_intakes": len(intakes),
        "queue_count": len(q),
        "queue": q,
    }


@app.get("/crm/sofia-proactive/metrics")
async def metrics():
    accounts, external, intakes = await _load_records()
    records = accounts + external
    assessed = [(r, assess_record(r)) for r in records]
    return {
        "status": "ok",
        "generated_at": _now().isoformat(),
        "records_loaded": len(records),
        "contactable": sum(1 for r, _ in assessed if _has_contact(r)),
        "kyb_verified": sum(1 for r, _ in assessed if _verified(r)),
        "records_with_current_need": sum(1 for r, _ in assessed if _has_need(r)),
        "qualified_demand_records": sum(1 for r, a in assessed if _stage(r, a) == "QUALIFIED_DEMAND"),
        "commercial_validation_records": sum(1 for r, a in assessed if _stage(r, a) == "COMMERCIAL_VALIDATION"),
        "customer_trade_intakes": len(intakes),
        "owner_blocked_research": 0,
        "north_star": "evidence-backed opportunities progressing to legitimate collected revenue with protected SAHJONY economics and minimal capital exposure",
    }


@app.post("/crm/sofia-proactive/run")
async def run(
    limit: int = 50,
    persist_internal_actions: bool = False,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = _auth(x_role, authorization, x_employee_id)
    accounts, external, intakes = await _load_records()
    records = accounts + external
    q = _build_queue(records, limit)
    persisted = 0
    if persist_internal_actions:
        b = get_backend()
        stamp = _now()
        for item in q:
            # Internal work item only. This endpoint never sends outreach or creates binding commercial commitments.
            try:
                await b.insert("business_events", {
                    "event_id": f"sofia_sales_{stamp.strftime('%Y%m%d%H')}_{hashlib_sha(item['record_ref'] + item['next_action_type'])}",
                    "event_type": "sofia_proactive_sales_action",
                    "source_type": "sofia_sales_os",
                    "source_id": item["record_ref"],
                    "trade_case_id": None,
                    "customer_id": None,
                    "lead_id": item["record_ref"],
                    "actor_role": actor["role"],
                    "actor_id": actor["id"],
                    "visibility": "business",
                    "title": f"SOFIA: {item['next_action_type']} — {item['company']}"[:240],
                    "summary": item["next_best_action"][:4000],
                    "action_required": True,
                    "action_label": item["next_action_type"][:160],
                    "priority": "high" if item["proactivity_score"] >= 75 else "normal",
                    "event_status": "open",
                    "payload": {
                        "commercial_stage": item["commercial_stage"],
                        "proactivity_score": item["proactivity_score"],
                        "owner_dependency": False,
                        "binding_commitments_allowed": False,
                        "autonomous_promotional_send_allowed": False,
                        "fee_protection_required": True,
                        "capital_at_risk_usd": 0,
                        "created_at": stamp.isoformat(),
                    },
                })
                persisted += 1
            except Exception:
                pass
    return {
        "status": "ok",
        "mode": "INTERNAL_ACTION_ORCHESTRATION",
        "generated_at": _now().isoformat(),
        "queue_count": len(q),
        "persisted_internal_actions": persisted,
        "external_messages_sent": 0,
        "binding_commitments_created": 0,
        "queue": q,
    }


def hashlib_sha(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()[:20]


@app.get("/crm/sofia-proactive/policy")
async def policy():
    return {
        "status": "ok",
        "research_fallback_chain": [
            "primary_sources",
            "high_quality_secondary_sources",
            "crm_intelligence",
            "alternate_search_provider",
            "public_business_directories",
            "legitimate_trade_records",
            "internal_manual_research_queue",
        ],
        "continuous_loops": [
            "new_lead_intake",
            "missing_data_enrichment",
            "personalized_pitch_preparation",
            "buyer_need_discovery",
            "dormant_lead_reactivation",
            "supplier_matching",
            "competition_price_scan",
            "quote_chase_and_expiry",
            "follow_up_sla",
            "cross_sell_and_upsell",
            "mipyme_to_mipyme_matching",
            "global_market_expansion",
            "deal_blocker_escalation",
        ],
        "hard_gates": {
            "qualified_demand": "requires current buyer requirement evidence",
            "firm_quote": "requires current price, Incoterm, quantity basis and commercial validity",
            "counterparty_disclosure": "requires governed fee protection where applicable",
            "binding_commitment": "owner approval required",
            "payment": "owner approval required",
            "revenue": "never inferred; requires evidence of collected funds",
        },
    }
