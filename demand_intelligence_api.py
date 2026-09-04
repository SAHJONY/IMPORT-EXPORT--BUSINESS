from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Demand Intelligence", version="1.0.0", docs_url=None, redoc_url=None)

SIGNAL_TABLE = "demand_inventory_signals"
DRAFT_TABLE = "demand_rfq_drafts"
CANONICAL_AGENT_ID = "sofia-smith"
CANONICAL_AGENT_NAME = "Sofia Smith"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _employee_token() -> str:
    token = os.getenv("EMPLOYEE_TOKEN", "").strip()
    if not token:
        raise HTTPException(503, "Employee access not configured")
    return token


def _identity(role: str | None, authorization: str | None, employee_id: str | None) -> dict[str, str]:
    if role not in {"owner", "employee"}:
        raise HTTPException(400, "X-Role must be owner or employee")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if role == "owner":
        if not verify_owner_token(token):
            raise HTTPException(403, "Invalid owner credential")
        return {"role": "owner", "id": "owner"}
    if not secrets.compare_digest(token, _employee_token()):
        raise HTTPException(403, "Invalid employee credential")
    return {"role": "employee", "id": (employee_id or "staff")[:160]}


class InventorySignalIn(BaseModel):
    business_id: str = Field(min_length=2, max_length=200)
    business_name: str | None = Field(default=None, max_length=240)
    product_name: str = Field(min_length=2, max_length=300)
    sku: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, max_length=160)
    unit: str = Field(default="unit", min_length=1, max_length=60)
    current_stock: float = Field(ge=0)
    monthly_consumption: float = Field(gt=0)
    reorder_point: float = Field(ge=0)
    preferred_packaging: str | None = Field(default=None, max_length=300)
    last_purchase_price_usd: float | None = Field(default=None, ge=0)
    last_purchase_date: str | None = Field(default=None, max_length=40)
    destination: str | None = Field(default=None, max_length=240)
    required_date: str | None = Field(default=None, max_length=40)
    source_ref: str | None = Field(default=None, max_length=1000)
    source_type: Literal["CUSTOMER_REPORTED", "INTERNAL_ENTRY", "IMPORT_FILE", "OTHER"] = "CUSTOMER_REPORTED"


class RfqDraftIn(BaseModel):
    quantity_override: float | None = Field(default=None, gt=0)
    destination_override: str | None = Field(default=None, max_length=240)
    required_date_override: str | None = Field(default=None, max_length=40)
    packaging_override: str | None = Field(default=None, max_length=300)


def assess_inventory(current_stock: float, monthly_consumption: float, reorder_point: float) -> dict[str, float | str | bool]:
    days_cover = (current_stock / monthly_consumption) * 30.0
    target_stock = max(monthly_consumption, reorder_point)
    recommended_qty = max(target_stock - current_stock, 0.0)
    if current_stock <= 0 or days_cover <= 7:
        status = "CRITICAL"
    elif current_stock <= reorder_point or days_cover <= 14:
        status = "REORDER_DUE"
    elif days_cover <= 30:
        status = "WATCH"
    else:
        status = "HEALTHY"
    return {
        "status": status,
        "days_of_cover": round(days_cover, 1),
        "recommended_reorder_quantity": round(recommended_qty, 3),
        "reorder_candidate": status in {"CRITICAL", "REORDER_DUE"},
    }


@app.get("/demand-intelligence/health")
async def health():
    return {
        "status": "ok",
        "service": "cuba-demand-intelligence",
        "canonical_agent_id": CANONICAL_AGENT_ID,
        "canonical_agent_name": CANONICAL_AGENT_NAME,
        "offline_first_input_supported": True,
        "rfq_draft_only": True,
        "auto_supplier_commitment": False,
        "auto_outreach": False,
        "capital_at_risk_usd": 0,
    }


@app.post("/demand-intelligence/signals")
async def create_signal(
    payload: InventorySignalIn,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = _identity(x_role, authorization, x_employee_id)
    signal_id = f"dis_{secrets.token_urlsafe(10)}"
    ts = now()
    assessment = assess_inventory(payload.current_stock, payload.monthly_consumption, payload.reorder_point)
    row = {
        "id": signal_id,
        "signal_id": signal_id,
        **payload.model_dump(),
        **assessment,
        "pipeline_stage": "RESEARCH_LEAD",
        "assigned_to": CANONICAL_AGENT_NAME,
        "assigned_agent_id": CANONICAL_AGENT_ID,
        "capital_at_risk_usd": 0,
        "binding_commitment": False,
        "created_by_role": actor["role"],
        "created_by": actor["id"],
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert(SIGNAL_TABLE, row)
    return {"signal": row}


@app.get("/demand-intelligence/signals")
async def list_signals(
    status: str | None = None,
    business_id: str | None = None,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    _identity(x_role, authorization, x_employee_id)
    params: dict[str, str] = {"order": "updated_at.desc", "limit": "1000"}
    if status:
        params["status"] = f"eq.{status.upper()}"
    if business_id:
        params["business_id"] = f"eq.{business_id}"
    rows = await get_backend().select(SIGNAL_TABLE, params=params) or []
    return {"signals": rows, "count": len(rows)}


@app.post("/demand-intelligence/signals/{signal_id}/rfq-draft")
async def create_rfq_draft(
    signal_id: str,
    payload: RfqDraftIn,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = _identity(x_role, authorization, x_employee_id)
    rows = await get_backend().select(SIGNAL_TABLE, params={"signal_id": f"eq.{signal_id}", "limit": "2"}) or []
    if not rows:
        raise HTTPException(404, "Demand signal not found")
    signal = rows[0]
    quantity = payload.quantity_override or float(signal.get("recommended_reorder_quantity") or 0)
    if quantity <= 0:
        raise HTTPException(409, "No reorder quantity is supported by the current signal")
    packaging = payload.packaging_override or signal.get("preferred_packaging")
    destination = payload.destination_override or signal.get("destination")
    required_date = payload.required_date_override or signal.get("required_date")
    missing = [
        name for name, value in (("packaging", packaging), ("destination", destination), ("required_date", required_date)) if not value
    ]
    draft_id = f"drfq_{secrets.token_urlsafe(10)}"
    ts = now()
    draft = {
        "id": draft_id,
        "draft_id": draft_id,
        "source_signal_id": signal_id,
        "business_id": signal.get("business_id"),
        "business_name": signal.get("business_name"),
        "product_need": signal.get("product_name"),
        "category": signal.get("category"),
        "specifications": f"Unit: {signal.get('unit')}. Packaging: {packaging or 'TBD'}. SKU: {signal.get('sku') or 'TBD'}.",
        "quantity": quantity,
        "unit": signal.get("unit"),
        "destination": destination,
        "destination_country": "CU",
        "target_delivery_date": required_date,
        "currency": "USD",
        "benchmark_last_purchase_price_usd": signal.get("last_purchase_price_usd"),
        "pricing_status": "BENCHMARK_ONLY_NOT_FIRM_QUOTE" if signal.get("last_purchase_price_usd") is not None else "NO_PRICE_EVIDENCE",
        "pipeline_stage": "RFQ_DRAFT",
        "assigned_to": CANONICAL_AGENT_NAME,
        "assigned_agent_id": CANONICAL_AGENT_ID,
        "capital_at_risk_usd": 0,
        "binding_commitment": False,
        "external_outreach_released": False,
        "ready_for_managed_trade_intake": not missing,
        "missing_fields": missing,
        "created_by_role": actor["role"],
        "created_by": actor["id"],
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert(DRAFT_TABLE, draft)
    return {"rfq_draft": draft}
