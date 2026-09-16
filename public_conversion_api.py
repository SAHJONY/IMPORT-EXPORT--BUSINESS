from __future__ import annotations

import secrets
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Public Conversion Intelligence", version="1.0.0", docs_url=None, redoc_url=None)

ConversionEvent = Literal[
    "rfq_view",
    "rfq_submit",
    "call_click",
    "callback_click",
    "whatsapp_handoff",
    "supplier_registration_start",
    "supplier_registration_complete",
]

TARGETS_90D = {
    "rfq_submit_rate_pct": 4.0,
    "call_click_rate_pct": 2.0,
    "whatsapp_handoff_rate_pct": 3.0,
    "supplier_registration_completion_pct": 25.0,
}


class PublicEventIn(BaseModel):
    event: ConversionEvent
    page: str = Field(min_length=1, max_length=240)
    locale: str = Field(default="en", max_length=16)
    source: str | None = Field(default=None, max_length=120)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


@app.get("/conversion/health")
async def health():
    return {
        "status": "ok",
        "service": "public-conversion-intelligence",
        "privacy": "first_party_no_cookie_no_ip_or_user_agent_storage",
        "targets_window_days": 90,
        "targets": TARGETS_90D,
    }


@app.post("/conversion/event")
async def record_event(p: PublicEventIn):
    # Deliberately stores no IP address, user-agent, contact details or browser fingerprint.
    event_id = f"evt_web_{secrets.token_urlsafe(12)}"
    row = {
        "event_id": event_id,
        "event_type": "system",
        "source_type": "public_conversion",
        "source_id": p.event,
        "trade_case_id": None,
        "customer_id": None,
        "actor_role": "system",
        "actor_id": "public_web",
        "visibility": "owner",
        "title": f"Public conversion · {p.event}",
        "summary": f"{p.event} on {p.page}",
        "action_required": False,
        "action_label": None,
        "priority": "normal",
        "event_status": "resolved",
        "payload": {"event": p.event, "page": p.page, "locale": p.locale, "source": p.source},
        "created_at": now(),
        "updated_at": now(),
    }
    try:
        await get_backend().insert("business_events", row)
    except Exception as exc:
        # Analytics may never block customer conversion paths.
        return {"status": "degraded", "accepted": False, "reason": type(exc).__name__}
    return {"status": "accepted", "accepted": True, "event_id": event_id}


def _rate(num: int, den: int) -> float:
    return round((num / den) * 100, 2) if den else 0.0


CATEGORY_RULES = [
    ("Industrial equipment", ("machine", "equipment", "motor", "pump", "compressor", "generator", "transformer", "tool")),
    ("Food & beverage", ("food", "beverage", "oil", "rice", "flour", "sugar", "coffee", "grain")),
    ("Packaging", ("packaging", "bottle", "container", "carton", "label", "film", "pouch")),
    ("Automotive & mobility", ("vehicle", "car", "truck", "auto", "ev", "charger", "tire", "battery")),
    ("Construction & building", ("cement", "steel", "aluminum", "lumber", "roof", "building", "construction")),
    ("Chemicals & materials", ("chemical", "resin", "scrap", "polymer", "fertilizer", "material")),
]

def _public_category(product_need: str) -> str:
    text=(product_need or "").lower()
    for label, keywords in CATEGORY_RULES:
        if any(word in text for word in keywords): return label
    return "Other commercial demand"

@app.get("/supplier-demand/public-summary")
async def supplier_demand_public_summary():
    since=datetime.now(timezone.utc)-timedelta(days=90)
    try:
        rows=await get_backend().select("customer_trade_intakes",params={"created_at":f"gte.{since.isoformat()}","limit":"5000"}) or []
    except Exception as exc:
        return {"status":"degraded","window_days":90,"privacy_threshold":3,"signals":[],"reason":type(exc).__name__}
    buckets={}
    for row in rows:
        category=_public_category(str(row.get("product_need") or ""))
        dest=str(row.get("destination_country") or "").upper().strip()[:3] or "OTHER"
        key=(category,dest)
        item=buckets.setdefault(key,{"category":category,"destination":dest,"rfq_count":0,"quantity_min":None,"quantity_max":None})
        item["rfq_count"]+=1
        try: q=float(row.get("quantity")) if row.get("quantity") is not None else None
        except (TypeError,ValueError): q=None
        if q is not None and q>=0:
            item["quantity_min"]=q if item["quantity_min"] is None else min(item["quantity_min"],q)
            item["quantity_max"]=q if item["quantity_max"] is None else max(item["quantity_max"],q)
    signals=[]
    for item in buckets.values():
        if item["rfq_count"]<3: continue
        # Quantities are only published when at least three requests contributed to the bucket; no budgets, buyer IDs or raw specs leave the backend.
        signals.append(item)
    signals.sort(key=lambda x:(-x["rfq_count"],x["category"],x["destination"]))
    return {"status":"ok","window_days":90,"privacy_threshold":3,"source":"real_customer_trade_intakes","total_recent_intakes":len(rows),"signals":signals[:12],"message":"Only category/destination buckets with at least three recent RFQs are publishable."}

@app.get("/owner/conversion-dashboard")
async def dashboard(authorization: str | None = Header(None, alias="Authorization")):
    owner(authorization)
    since = datetime.now(timezone.utc) - timedelta(days=90)
    try:
        rows = await get_backend().select(
            "business_events",
            params={"source_type": "eq.public_conversion", "created_at": f"gte.{since.isoformat()}", "limit": "10000"},
        ) or []
    except Exception as exc:
        raise HTTPException(503, f"Conversion analytics unavailable: {type(exc).__name__}") from exc
    counts = Counter(str((r.get("payload") or {}).get("event") or r.get("source_id") or "") for r in rows)
    metrics = {
        "rfq_submit_rate_pct": _rate(counts["rfq_submit"], counts["rfq_view"]),
        "call_click_rate_pct": _rate(counts["call_click"], counts["rfq_view"]),
        "whatsapp_handoff_rate_pct": _rate(counts["whatsapp_handoff"], counts["rfq_view"]),
        "supplier_registration_completion_pct": _rate(counts["supplier_registration_complete"], counts["supplier_registration_start"]),
    }
    return {
        "status": "ok",
        "window_days": 90,
        "event_counts": dict(counts),
        "metrics": metrics,
        "targets": TARGETS_90D,
        "target_status": {k: {"actual": metrics[k], "target": v, "met": metrics[k] >= v} for k, v in TARGETS_90D.items()},
        "privacy": "No IP, user-agent, email, phone or fingerprint stored by this instrumentation endpoint.",
    }
