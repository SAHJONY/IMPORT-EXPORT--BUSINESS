from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(
    title="SAHJONY Outreach & Marketing Department",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

DEPARTMENT_ID = "dept_outreach_marketing"
DEPARTMENT_NAME = "Outreach & Marketing Department"
EXECUTIVE_OWNER = "Sofia Smith"

CHANNELS = (
    "whatsapp",
    "email",
    "facebook_messenger",
    "website",
    "partner_network",
    "trade_platforms",
    "linkedin_manual_or_authorized",
)

FUNNELS = (
    "buyer_acquisition",
    "supplier_acquisition",
    "partner_recruitment",
    "rfq_reactivation",
    "quote_followup",
    "cross_sell",
    "country_market_activation",
    "account_based_marketing",
)

KPI_DEFINITIONS = {
    "research_leads": "Evidence-backed prospects not yet qualified as buyer demand.",
    "contactable_leads": "Prospects with a legitimate business contact channel.",
    "engaged_accounts": "Accounts with a real response or meaningful interaction.",
    "qualified_rfqs": "Verified buyer requirements with product, quantity, destination and timing.",
    "supplier_responses": "Supplier engagement that is not automatically a firm quote.",
    "firm_quotes": "Current supplier offers with price and material commercial terms.",
    "transaction_ready": "Buyer, supplier, KYB, economics, payment and logistics paths substantially ready.",
    "contracted_transactions": "Executed transaction agreements only.",
    "invoices": "Issued invoices supported by a real transaction.",
    "collected_revenue": "Cash actually collected by SAHJONY.",
}

POLICY = {
    "primary_objective": "maximize legitimate collected gross profit with minimal SAHJONY capital exposure",
    "operating_model": "proactive_research_and_consent_gated_outreach",
    "bulk_unsolicited_messaging": False,
    "binding_commitments": False,
    "autonomous_research": True,
    "autonomous_internal_prioritization": True,
    "autonomous_drafting": True,
    "autonomous_sending": "only_when_channel_policy_and_consent_or_prior_business_relationship_allow",
    "protected_counterparty_disclosure": False,
    "owner_approval_required_for": [
        "binding commercial commitments",
        "contract signature",
        "payment authorization",
        "capital deployment",
        "protected counterparty disclosure when economics are not secured",
        "commission payout",
    ],
}

PLAYBOOKS = {
    "new_buyer": [
        "verify identity and business relevance",
        "enrich legitimate public business contact data",
        "segment by product, geography, buying potential and urgency",
        "craft personalized value proposition",
        "seek permission or use an established business relationship before promotional send",
        "capture product, specification, quantity, destination, timing and payment capability",
        "promote to qualified RFQ only when evidence supports it",
        "route to supplier matching and protected economics",
    ],
    "dormant_lead": [
        "review last interaction and reason for stall",
        "check whether need, market or price conditions changed",
        "prepare contextual reactivation message",
        "send only through an authorized channel under applicable outreach policy",
        "close, nurture or reactivate based on response evidence",
    ],
    "quote_followup": [
        "confirm quote validity and outstanding buyer questions",
        "identify commercial blocker",
        "prepare concise next-step response",
        "seek written buyer confirmation of volume, destination and timing",
        "protect SAHJONY fee or margin before sensitive introductions",
    ],
    "partner_recruitment": [
        "verify partner identity and network relevance",
        "explain program without promising earnings",
        "capture consent and partner terms acceptance",
        "track referred opportunities separately from earned commissions",
        "commission becomes earned only after governed closed-won and collection evidence",
    ],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auth_owner(x_role: str | None, authorization: str | None) -> None:
    if x_role != "owner":
        raise HTTPException(status_code=403, detail="Owner role required")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


def _safe_text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


@app.get("/crm/outreach-marketing/health")
async def health():
    return {
        "status": "ok",
        "department_id": DEPARTMENT_ID,
        "department": DEPARTMENT_NAME,
        "executive_owner": EXECUTIVE_OWNER,
        "mission": POLICY["primary_objective"],
        "channels": CHANNELS,
        "funnels": FUNNELS,
        "cash_collected_primary_metric": True,
        "qualified_rfq_primary_conversion_metric": True,
        "bulk_unsolicited_messaging": False,
        "binding_commitments": False,
        "capital_at_risk_default_usd": 0,
    }


@app.get("/crm/outreach-marketing/structure")
async def structure():
    return {
        "status": "ok",
        "department": DEPARTMENT_NAME,
        "leader": EXECUTIVE_OWNER,
        "desks": [
            {"id": "market_intelligence", "mission": "Find demand signals, accounts and market triggers."},
            {"id": "buyer_outreach", "mission": "Convert evidence-backed prospects into qualified RFQs."},
            {"id": "supplier_outreach", "mission": "Acquire current comparable supplier terms and commercial packs."},
            {"id": "partner_growth", "mission": "Recruit and activate compliant referral and distribution partners."},
            {"id": "lifecycle_nurture", "mission": "Follow up, reactivate and cross-sell without spamming."},
            {"id": "campaign_ops", "mission": "Build segmented campaigns, experiments and channel calendars."},
            {"id": "revenue_analytics", "mission": "Measure progression to qualified RFQ, firm quote and collected revenue."},
            {"id": "brand_content", "mission": "Create evidence-led trade content and product-market messaging."},
        ],
        "handoffs": {
            "qualified_buyer_requirement": "sales_and_deal_execution",
            "supplier_quote": "supplier_sourcing_and_pricing",
            "kyb_blocker": "compliance",
            "freight_blocker": "logistics",
            "payment_blocker": "finance_and_trade_payments",
            "contract_or_binding_term": "owner_approval",
        },
    }


@app.get("/crm/outreach-marketing/policy")
async def policy():
    return {"status": "ok", "policy": POLICY, "playbooks": PLAYBOOKS}


@app.get("/crm/outreach-marketing/kpis")
async def kpis():
    backend = get_backend()
    tables = {}
    for table in ("external_trade_prospects", "customer_accounts", "customer_trade_intakes", "deal_supplier_matches"):
        try:
            rows = await backend.select(table, params={"limit": "5000"}) or []
            tables[table] = len(rows)
        except Exception:
            tables[table] = None
    qualified = 0
    try:
        intakes = await backend.select("customer_trade_intakes", params={"limit": "5000"}) or []
        qualified = sum(1 for r in intakes if str(r.get("qualification_status") or "").upper() == "QUALIFIED")
    except Exception:
        pass
    return {
        "status": "ok",
        "as_of": _now_iso(),
        "definitions": KPI_DEFINITIONS,
        "observed": {
            "research_leads": tables.get("external_trade_prospects"),
            "customer_accounts": tables.get("customer_accounts"),
            "buyer_trade_intakes": tables.get("customer_trade_intakes"),
            "qualified_rfqs": qualified,
            "deal_supplier_matches": tables.get("deal_supplier_matches"),
        },
        "not_inferred_without_evidence": ["contracted_transactions", "invoices", "collected_revenue", "earned_commission"],
    }


@app.post("/crm/outreach-marketing/campaigns")
async def create_campaign(
    payload: dict,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
):
    _auth_owner(x_role, authorization)
    campaign_type = _safe_text(payload.get("campaign_type"), 80)
    segment = _safe_text(payload.get("segment"), 160)
    objective = _safe_text(payload.get("objective"), 500)
    if campaign_type not in FUNNELS:
        raise HTTPException(status_code=400, detail=f"campaign_type must be one of: {', '.join(FUNNELS)}")
    if not segment or not objective:
        raise HTTPException(status_code=400, detail="segment and objective are required")
    campaign_id = f"mkt_{int(datetime.now(timezone.utc).timestamp())}_{abs(hash(segment)) % 100000}"
    record = {
        "event_id": campaign_id,
        "event_type": "outreach_marketing_campaign_created",
        "source_type": "outreach_marketing_department",
        "source_id": DEPARTMENT_ID,
        "trade_case_id": None,
        "customer_id": None,
        "lead_id": None,
        "actor_role": "owner",
        "actor_id": "owner",
        "visibility": "business",
        "title": f"Marketing campaign: {segment}"[:240],
        "summary": objective[:4000],
        "action_required": True,
        "action_label": "Sofia campaign planning and governed execution",
        "priority": _safe_text(payload.get("priority") or "normal", 40),
        "event_status": "open",
        "payload": {
            "department": DEPARTMENT_NAME,
            "executive_owner": EXECUTIVE_OWNER,
            "campaign_type": campaign_type,
            "segment": segment,
            "objective": objective,
            "channels": [c for c in payload.get("channels", []) if c in CHANNELS],
            "offer_or_message": _safe_text(payload.get("offer_or_message"), 1000),
            "country": _safe_text(payload.get("country"), 120),
            "product": _safe_text(payload.get("product"), 240),
            "target_accounts": max(0, min(int(payload.get("target_accounts") or 0), 100000)),
            "send_authority": "CONSENT_OR_PRIOR_BUSINESS_RELATIONSHIP_REQUIRED",
            "bulk_unsolicited_messaging": False,
            "binding_commitments_allowed": False,
            "capital_at_risk_usd": 0,
            "created_at": _now_iso(),
        },
    }
    await get_backend().insert("business_events", record)
    return {
        "status": "created",
        "campaign_id": campaign_id,
        "department": DEPARTMENT_NAME,
        "execution_mode": "proactive_nonbinding_policy_gated",
        "campaign": record["payload"],
    }


@app.post("/crm/outreach-marketing/tasks")
async def create_marketing_task(
    payload: dict,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
):
    _auth_owner(x_role, authorization)
    action = _safe_text(payload.get("action"), 500)
    account_ref = _safe_text(payload.get("account_ref"), 240)
    if not action:
        raise HTTPException(status_code=400, detail="action is required")
    event_id = f"mkt_task_{int(datetime.now(timezone.utc).timestamp())}_{abs(hash(action)) % 100000}"
    await get_backend().insert("business_events", {
        "event_id": event_id,
        "event_type": "outreach_marketing_task",
        "source_type": "outreach_marketing_department",
        "source_id": DEPARTMENT_ID,
        "trade_case_id": None,
        "customer_id": account_ref or None,
        "lead_id": account_ref or None,
        "actor_role": "owner",
        "actor_id": "owner",
        "visibility": "business",
        "title": action[:240],
        "summary": _safe_text(payload.get("context"), 4000),
        "action_required": True,
        "action_label": "Sofia Outreach & Marketing execution",
        "priority": _safe_text(payload.get("priority") or "normal", 40),
        "event_status": "open",
        "payload": {
            "department": DEPARTMENT_NAME,
            "executive_owner": EXECUTIVE_OWNER,
            "account_ref": account_ref,
            "action": action,
            "channel": _safe_text(payload.get("channel"), 80),
            "send_authority": "POLICY_GATED",
            "binding_commitments_allowed": False,
            "created_at": _now_iso(),
        },
    })
    return {"status": "created", "task_id": event_id, "assigned_to": EXECUTIVE_OWNER}
