from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(
    title="SAHJONY Autonomous Social Media Management OS",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

DEPARTMENT_ID = "dept_outreach_marketing"
EXECUTIVE_OWNER = "Sofia Smith"
SERVICE_ID = "social_media_management"

SUPPORTED_NETWORKS = (
    "facebook",
    "instagram",
    "linkedin",
    "x",
    "threads",
    "tiktok",
    "youtube",
    "pinterest",
)

CONTENT_PILLARS = (
    "verified_trade_opportunities",
    "product_and_supplier_intelligence",
    "cuba_private_sector_trade",
    "global_sourcing_education",
    "logistics_and_market_updates",
    "buyer_need_discovery",
    "supplier_and_partner_acquisition",
    "brand_trust_and_case_evidence",
)

POLICY = {
    "mission": "turn authorized social channels into a measurable global-trade demand and relationship engine",
    "autonomous_monitoring": True,
    "autonomous_research": True,
    "autonomous_content_planning": True,
    "autonomous_drafting": True,
    "autonomous_scheduling": True,
    "autonomous_publishing": "allowed only for pre-authorized nonbinding brand/content classes and connected business profiles",
    "autonomous_comment_or_dm_replies": "allowed only when channel policy and account authority permit and response is nonbinding",
    "bulk_unsolicited_dm": False,
    "binding_commercial_commitments": False,
    "public_counterparty_disclosure_without_clearance": False,
    "unverified_price_or_inventory_claims": False,
    "unverified_revenue_or_customer_claims": False,
    "capital_at_risk_usd": 0,
    "owner_approval_required_for": [
        "binding commercial commitment",
        "public disclosure of protected buyer or supplier identities",
        "paid advertising spend or budget increase",
        "legal or regulatory statement outside approved policy",
        "crisis response with material reputational or legal exposure",
    ],
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(v: Any, n: int = 500) -> str:
    return str(v or "").strip()[:n]


def _auth_owner(x_role: str | None, authorization: str | None) -> None:
    if x_role != "owner":
        raise HTTPException(403, "Owner role required")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


@app.get("/crm/social-media/health")
async def health():
    return {
        "status": "ok",
        "service": SERVICE_ID,
        "department": DEPARTMENT_ID,
        "executive_owner": EXECUTIVE_OWNER,
        "supported_networks": SUPPORTED_NETWORKS,
        "content_pillars": CONTENT_PILLARS,
        "autonomous_nonbinding_management": True,
        "bulk_unsolicited_dm": False,
        "binding_commitments": False,
        "capital_at_risk_usd": 0,
    }


@app.get("/crm/social-media/policy")
async def policy():
    return {"status": "ok", "policy": POLICY, "content_pillars": CONTENT_PILLARS}


@app.get("/crm/social-media/operating-system")
async def operating_system():
    return {
        "status": "ok",
        "owner": EXECUTIVE_OWNER,
        "loops": [
            "monitor account health, messages, comments, mentions and response SLAs",
            "discover market signals and buyer/supplier conversations relevant to SAHJONY Global Trade",
            "convert legitimate inbound interest into CRM research leads",
            "prepare channel-native content from evidence-backed trade intelligence",
            "schedule content by target-market timezone and audience working hours",
            "reply to nonbinding inbound questions using CRM and approved catalog evidence",
            "route product + quantity + destination + timing signals into buyer-demand qualification",
            "route supplier offers into supplier verification and quotation workflow",
            "measure post, conversation and campaign progression to qualified RFQ and collected revenue",
            "reactivate high-value accounts without spam or unsupported claims",
        ],
        "optimization": {
            "north_star": "qualified demand and legitimate collected gross profit attributable to social channels",
            "secondary": ["response_rate", "qualified_rfq_rate", "supplier_response_rate", "meeting_or_quote_rate", "time_to_first_response"],
            "vanity_metrics_only": ["followers", "likes", "impressions"],
        },
        "handoff": "SOFIA Sales OS -> CRM -> supplier matching -> protected economics -> governed Deal Room",
    }


@app.post("/crm/social-media/accounts/register")
async def register_account(
    payload: dict,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
):
    _auth_owner(x_role, authorization)
    network = _safe(payload.get("network"), 40).lower()
    profile_name = _safe(payload.get("profile_name"), 200)
    external_profile_id = _safe(payload.get("external_profile_id"), 240)
    if network not in SUPPORTED_NETWORKS:
        raise HTTPException(400, f"Unsupported network: {network}")
    if not profile_name:
        raise HTTPException(400, "profile_name is required")
    event_id = f"social_account_{network}_{int(datetime.now(timezone.utc).timestamp())}"
    await get_backend().insert("business_events", {
        "event_id": event_id,
        "event_type": "social_media_account_registered",
        "source_type": "social_media_management",
        "source_id": network,
        "trade_case_id": None,
        "customer_id": None,
        "lead_id": None,
        "actor_role": "owner",
        "actor_id": "owner",
        "visibility": "business",
        "title": f"Social account: {profile_name}"[:240],
        "summary": f"Authorized {network} profile registered for governed autonomous management.",
        "action_required": True,
        "action_label": "Sofia social media account activation",
        "priority": "normal",
        "event_status": "open",
        "payload": {
            "network": network,
            "profile_name": profile_name,
            "external_profile_id": external_profile_id,
            "provider": _safe(payload.get("provider") or "native_or_authorized_connector", 120),
            "autonomous_management": True,
            "autonomous_nonbinding_publishing": bool(payload.get("autonomous_nonbinding_publishing", True)),
            "autonomous_nonbinding_replies": bool(payload.get("autonomous_nonbinding_replies", True)),
            "paid_media_authority": False,
            "bulk_unsolicited_dm": False,
            "binding_commitments": False,
            "registered_at": _now_iso(),
        },
    })
    return {"status": "registered", "account_event_id": event_id, "network": network, "profile_name": profile_name}


@app.post("/crm/social-media/content/queue")
async def queue_content(
    payload: dict,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
):
    _auth_owner(x_role, authorization)
    pillar = _safe(payload.get("pillar"), 100)
    objective = _safe(payload.get("objective"), 500)
    if pillar not in CONTENT_PILLARS:
        raise HTTPException(400, f"pillar must be one of: {', '.join(CONTENT_PILLARS)}")
    if not objective:
        raise HTTPException(400, "objective is required")
    event_id = f"social_content_{int(datetime.now(timezone.utc).timestamp())}_{abs(hash(objective)) % 100000}"
    networks = [str(x).lower() for x in (payload.get("networks") or []) if str(x).lower() in SUPPORTED_NETWORKS]
    await get_backend().insert("business_events", {
        "event_id": event_id,
        "event_type": "social_media_content_queued",
        "source_type": "social_media_management",
        "source_id": SERVICE_ID,
        "trade_case_id": None,
        "customer_id": None,
        "lead_id": None,
        "actor_role": "owner",
        "actor_id": "owner",
        "visibility": "business",
        "title": f"Social content: {pillar}"[:240],
        "summary": objective,
        "action_required": True,
        "action_label": "Sofia create, validate and schedule social content",
        "priority": _safe(payload.get("priority") or "normal", 40),
        "event_status": "open",
        "payload": {
            "pillar": pillar,
            "objective": objective,
            "networks": networks,
            "target_market": _safe(payload.get("target_market"), 120),
            "product_or_category": _safe(payload.get("product_or_category"), 240),
            "source_evidence_required": True,
            "unverified_claims_allowed": False,
            "counterparty_disclosure_allowed": False,
            "binding_commitments_allowed": False,
            "paid_media_authority": False,
            "queued_at": _now_iso(),
        },
    })
    return {"status": "queued", "content_event_id": event_id, "assigned_to": EXECUTIVE_OWNER, "networks": networks}
