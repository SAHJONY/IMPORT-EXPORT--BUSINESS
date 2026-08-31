from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from global_deal_decision_engine import DealDecisionContext, EvidenceItem, decision_engine_profile, evaluate_deal
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY Global Deal Decision Engine", version="1.0.0", docs_url=None, redoc_url=None)

EvidenceState = Literal["verified", "missing", "stale", "failed", "not_applicable"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


class EvidencePayload(BaseModel):
    key: str = Field(min_length=2, max_length=160)
    state: EvidenceState = "missing"
    source: str | None = Field(default=None, max_length=1000)
    effective_at: str | None = Field(default=None, max_length=100)
    expires_at: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=3000)


class DealDecisionRequest(BaseModel):
    decision_type: str = Field(min_length=2, max_length=120)
    origin_country: str | None = Field(default=None, max_length=120)
    transit_countries: list[str] = Field(default_factory=list)
    destination_country: str | None = Field(default=None, max_length=120)
    product: str | None = Field(default=None, max_length=500)
    hs_code: str | None = Field(default=None, max_length=40)
    seller: str | None = Field(default=None, max_length=500)
    buyer: str | None = Field(default=None, max_length=500)
    banks: list[str] = Field(default_factory=list)
    payment_terms: str | None = Field(default=None, max_length=500)
    incoterm: str | None = Field(default=None, max_length=100)
    currency: str | None = Field(default=None, max_length=40)
    shipment_mode: str | None = Field(default=None, max_length=120)
    expected_revenue: float | None = None
    expected_cost: float | None = None
    expected_margin: float | None = None
    as_of: str | None = Field(default=None, max_length=100)
    customer_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    lead_id: str | None = Field(default=None, max_length=160)
    evidence: list[EvidencePayload] = Field(default_factory=list)


@app.get("/business-os/deal-decision/health")
async def deal_decision_health() -> dict[str, Any]:
    persistence = persistent_backend_status()
    return {
        **decision_engine_profile(),
        "persistence_configured": bool(persistence.get("configured")),
        "persistence_provider": persistence.get("provider"),
        "durable_decision_log": bool(persistence.get("configured")),
    }


@app.post("/business-os/deal-decision/evaluate")
async def evaluate_global_deal(payload: DealDecisionRequest, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    ctx = DealDecisionContext(
        decision_type=payload.decision_type,
        origin_country=payload.origin_country,
        transit_countries=payload.transit_countries,
        destination_country=payload.destination_country,
        product=payload.product,
        hs_code=payload.hs_code,
        seller=payload.seller,
        buyer=payload.buyer,
        banks=payload.banks,
        payment_terms=payload.payment_terms,
        incoterm=payload.incoterm,
        currency=payload.currency,
        shipment_mode=payload.shipment_mode,
        expected_revenue=payload.expected_revenue,
        expected_cost=payload.expected_cost,
        expected_margin=payload.expected_margin,
        as_of=payload.as_of,
    )
    evidence = [EvidenceItem(**item.model_dump()) for item in payload.evidence]
    result = evaluate_deal(ctx, evidence)

    persistence = persistent_backend_status()
    event_id = f"evt_{secrets.token_urlsafe(16)}"
    if persistence.get("configured"):
        row = {
            "event_id": event_id,
            "event_type": "decision",
            "source_type": "global_deal_decision",
            "source_id": payload.trade_case_id or payload.lead_id or event_id,
            "trade_case_id": payload.trade_case_id,
            "customer_id": payload.customer_id,
            "lead_id": payload.lead_id,
            "actor_role": "system",
            "actor_id": "global-deal-decision-engine",
            "visibility": "internal",
            "title": f"Deal decision · {result['decision']} · {payload.decision_type}"[:240],
            "summary": str(result.get("reason") or "")[:3000],
            "action_required": result["decision"] != "GO",
            "action_label": result.get("next_action"),
            "priority": "urgent" if result["decision"] == "BLOCK" else ("high" if result["decision"] == "HOLD" else "normal"),
            "event_status": "open" if result["decision"] != "GO" else "closed",
            "payload": {"decision": result, "request": payload.model_dump(exclude={"evidence"}), "evidence": [e.model_dump() for e in payload.evidence]},
            "created_at": _now(),
            "updated_at": _now(),
        }
        await get_backend().insert("business_events", row)
    else:
        event_id = ""

    return {**result, "event_id": event_id or None, "durable_evidence_logged": bool(event_id)}


@app.get("/business-os/deal-decision/recent")
async def recent_deal_decisions(authorization: str | None = Header(None, alias="Authorization"), limit: int = 50) -> dict[str, Any]:
    _owner(authorization)
    safe_limit = str(max(1, min(limit, 250)))
    rows = await get_backend().select("business_events", params={"source_type": "eq.global_deal_decision", "order": "created_at.desc", "limit": safe_limit}) or []
    return {"status": "ok", "count": len(rows), "items": rows}
