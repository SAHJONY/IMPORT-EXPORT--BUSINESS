from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from customer_crm_api import identity
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Profit Machine", version="1.0.0", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"

RevenueStage = Literal[
    "PIPELINE",
    "QUALIFIED",
    "QUOTED",
    "FEE_PROTECTED",
    "CONTRACTED",
    "IN_EXECUTION",
    "INVOICED",
    "COLLECTED",
    "LOST",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "verified", "pass", "approved", "signed", "confirmed"}


def _money(value) -> float:
    try:
        return max(0.0, float(value or 0))
    except Exception:
        return 0.0


def _stage_rank(stage: str) -> int:
    order = {
        "PIPELINE": 0,
        "QUALIFIED": 1,
        "QUOTED": 2,
        "FEE_PROTECTED": 3,
        "CONTRACTED": 4,
        "IN_EXECUTION": 5,
        "INVOICED": 6,
        "COLLECTED": 7,
        "LOST": -1,
    }
    return order.get(str(stage or "PIPELINE").upper(), 0)


class ProfitControlIn(BaseModel):
    funding_source: str | None = Field(default=None, max_length=240)
    payment_instrument: str | None = Field(default=None, max_length=240)
    buyer_funds_verified: bool = False
    supplier_payment_trigger: str | None = Field(default=None, max_length=500)
    supplier_credit_available: bool = False
    third_party_trade_finance: bool = False
    sahjony_capital_required_usd: float = Field(default=0, ge=0)
    principal_risk: bool = False
    inventory_title_risk: bool = False

    fee_model: str | None = Field(default=None, max_length=240)
    fee_rate_or_amount: str | None = Field(default=None, max_length=240)
    fee_protection_status: str = Field(default="PENDING", max_length=80)
    fee_payment_trigger: str | None = Field(default=None, max_length=500)

    buyer_requirement_verified: bool = False
    buyer_authority_verified: bool = False
    supplier_quote_verified: bool = False
    supplier_kyb_verified: bool = False
    compliance_status: str = Field(default="PENDING", max_length=80)

    revenue_stage: RevenueStage = "PIPELINE"
    transaction_notional_usd: float | None = Field(default=None, ge=0)
    expected_fee_usd: float | None = Field(default=None, ge=0)
    contracted_fee_usd: float | None = Field(default=None, ge=0)
    invoiced_fee_usd: float | None = Field(default=None, ge=0)
    collected_fee_usd: float | None = Field(default=None, ge=0)

    next_follow_up_at: str | None = Field(default=None, max_length=80)
    next_action: str | None = Field(default=None, max_length=1200)
    notes: str | None = Field(default=None, max_length=4000)


def _inferred_control(prospect: dict) -> dict:
    payment = str(prospect.get("payment_terms") or "").lower()
    instrument = None
    funding = None
    if "l/c" in payment or "letter of credit" in payment or "documentary credit" in payment:
        instrument = "Irrevocable documentary L/C"
        funding = "Buyer / issuing bank"
    elif "escrow" in payment:
        instrument = "Escrow"
        funding = "Buyer-funded escrow"
    elif "documentary" in payment:
        instrument = "Documentary collection"
        funding = "Buyer"

    stage = str(prospect.get("qualification_stage") or "").lower()
    supplier_quote = any(token in stage for token in ("quote", "sco", "supplier_response"))
    buyer_requirement = bool(prospect.get("buyer_contacted")) or "buyer" in str(prospect.get("verification_status") or "").lower()

    return {
        "control_id": f"profit_{prospect.get('prospect_id')}",
        "prospect_id": prospect.get("prospect_id"),
        "organization_id": ORG_ID,
        "funding_source": funding,
        "payment_instrument": instrument,
        "buyer_funds_verified": False,
        "supplier_payment_trigger": None,
        "supplier_credit_available": False,
        "third_party_trade_finance": False,
        "sahjony_capital_required_usd": 0.0,
        "principal_risk": False,
        "inventory_title_risk": False,
        "fee_model": None,
        "fee_rate_or_amount": None,
        "fee_protection_status": "PENDING",
        "fee_payment_trigger": None,
        "buyer_requirement_verified": buyer_requirement,
        "buyer_authority_verified": False,
        "supplier_quote_verified": supplier_quote,
        "supplier_kyb_verified": False,
        "compliance_status": "PENDING",
        "revenue_stage": "QUOTED" if supplier_quote else ("QUALIFIED" if buyer_requirement else "PIPELINE"),
        "transaction_notional_usd": None,
        "expected_fee_usd": None,
        "contracted_fee_usd": None,
        "invoiced_fee_usd": None,
        "collected_fee_usd": None,
        "next_follow_up_at": None,
        "next_action": prospect.get("next_action"),
        "notes": None,
    }


def _evaluate(prospect: dict, control: dict) -> dict:
    blockers: list[str] = []

    own_capital = _money(control.get("sahjony_capital_required_usd"))
    if own_capital > 0:
        blockers.append("SAHJONY own capital required must be $0")
    if _truthy(control.get("principal_risk")):
        blockers.append("Principal risk must remain false")
    if _truthy(control.get("inventory_title_risk")):
        blockers.append("Inventory/title risk must remain false")
    if not str(control.get("funding_source") or "").strip():
        blockers.append("Funding source not confirmed")
    if not str(control.get("payment_instrument") or "").strip():
        blockers.append("Payment instrument not confirmed")
    if not _truthy(control.get("buyer_funds_verified")):
        blockers.append("Buyer funds/payment capability not verified")
    if not str(control.get("supplier_payment_trigger") or "").strip():
        blockers.append("Supplier payment trigger not defined")

    zero_capital_gate = "PASS" if not blockers else "BLOCKED"

    fee_blockers: list[str] = []
    if not str(control.get("fee_model") or "").strip():
        fee_blockers.append("SAHJONY fee model not defined")
    if str(control.get("fee_protection_status") or "PENDING").upper() not in {"SIGNED", "EXECUTED", "CONFIRMED", "APPROVED"}:
        fee_blockers.append("Fee protection not executed")
    if not str(control.get("fee_payment_trigger") or "").strip():
        fee_blockers.append("Fee payment trigger not defined")
    fee_gate = "PASS" if not fee_blockers else "BLOCKED"

    buyer_ready = _truthy(control.get("buyer_requirement_verified")) and _truthy(control.get("buyer_authority_verified"))
    supplier_ready = _truthy(control.get("supplier_quote_verified")) and _truthy(control.get("supplier_kyb_verified"))
    compliance_pass = str(control.get("compliance_status") or "PENDING").upper() in {"PASS", "APPROVED", "CLEARED"}
    high_risk = str(prospect.get("risk_level") or "medium").lower() == "high"

    commercial_blockers = list(blockers) + fee_blockers
    if not buyer_ready:
        commercial_blockers.append("Buyer requirement/authority not fully verified")
    if not supplier_ready:
        commercial_blockers.append("Supplier quote/KYB not fully verified")
    if not compliance_pass:
        commercial_blockers.append("Compliance not cleared")
    if high_risk:
        commercial_blockers.append("High-risk opportunity requires enhanced diligence")

    close_gate = "PASS" if not commercial_blockers else "BLOCKED"

    score = int(prospect.get("opportunity_score") or 50)
    confidence = int(prospect.get("confidence") or 50)
    close_score = round(score * 0.35 + confidence * 0.15)
    close_score += 12 if zero_capital_gate == "PASS" else 0
    close_score += 12 if fee_gate == "PASS" else 0
    close_score += 10 if buyer_ready else 0
    close_score += 10 if supplier_ready else 0
    close_score += 6 if compliance_pass else 0
    close_score -= 20 if high_risk else 0
    close_score = max(0, min(100, close_score))

    revenue_stage = str(control.get("revenue_stage") or "PIPELINE").upper()
    if revenue_stage == "COLLECTED" and _money(control.get("collected_fee_usd")) <= 0:
        commercial_blockers.append("Collected stage requires positive collected revenue evidence")
        close_gate = "BLOCKED"

    return {
        "zero_capital_gate_status": zero_capital_gate,
        "fee_protection_gate_status": fee_gate,
        "commercial_close_gate_status": close_gate,
        "buyer_ready": buyer_ready,
        "supplier_ready": supplier_ready,
        "compliance_pass": compliance_pass,
        "close_score": close_score,
        "blockers": commercial_blockers,
        "expected_fee_usd": _money(control.get("expected_fee_usd")),
        "contracted_fee_usd": _money(control.get("contracted_fee_usd")),
        "invoiced_fee_usd": _money(control.get("invoiced_fee_usd")),
        "collected_fee_usd": _money(control.get("collected_fee_usd")),
    }


async def _load_queue() -> list[dict]:
    backend = get_backend()
    prospects = await backend.select(
        "external_trade_prospects",
        params={"organization_id": f"eq.{ORG_ID}", "order": "updated_at.desc", "limit": "5000"},
    ) or []
    controls = await backend.select(
        "profit_controls",
        params={"organization_id": f"eq.{ORG_ID}", "limit": "5000"},
    ) or []
    by_prospect = {str(row.get("prospect_id")): row for row in controls if row.get("prospect_id")}

    queue: list[dict] = []
    for prospect in prospects:
        pid = str(prospect.get("prospect_id") or "")
        control = _inferred_control(prospect)
        if pid in by_prospect:
            control.update(by_prospect[pid])
        evaluation = _evaluate(prospect, control)
        queue.append({"prospect": prospect, "control": control, "evaluation": evaluation})

    queue.sort(key=lambda row: (row["evaluation"]["commercial_close_gate_status"] == "PASS", row["evaluation"]["close_score"]), reverse=True)
    return queue


def _require_owner(x_role, authorization, x_employee_id):
    actor = identity(x_role, authorization, x_employee_id)
    if actor["role"] != "owner":
        raise HTTPException(403, "Owner access required")
    return actor


@app.get("/owner/profit-machine/health")
async def profit_machine_health():
    backend = get_backend()
    prospects = await backend.select("external_trade_prospects", params={"organization_id": f"eq.{ORG_ID}", "limit": "1"}) or []
    return {
        "status": "ok",
        "service": "profit-machine",
        "zero_own_capital_required": True,
        "fee_protection_required": True,
        "cash_collected_is_primary_revenue_metric": True,
        "pipeline_connected": bool(prospects),
        "human_approval_required_for_binding_commitments": True,
    }


@app.get("/owner/profit-machine")
async def profit_machine_queue(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    _require_owner(x_role, authorization, x_employee_id)
    queue = await _load_queue()

    backend = get_backend()
    customers = await backend.select("customer_accounts", params={"limit": "5000"}) or []
    intakes = await backend.select("customer_trade_intakes", params={"limit": "5000"}) or []

    kpis = {
        "opportunities": len(queue),
        "zero_capital_pass": sum(1 for r in queue if r["evaluation"]["zero_capital_gate_status"] == "PASS"),
        "fee_protected": sum(1 for r in queue if r["evaluation"]["fee_protection_gate_status"] == "PASS"),
        "close_ready": sum(1 for r in queue if r["evaluation"]["commercial_close_gate_status"] == "PASS"),
        "qualified_buyers": sum(1 for r in customers if str(r.get("sales_status") or "").upper() in {"QUALIFIED_LEAD", "REPLIED", "OPPORTUNITY"}),
        "buyer_requirements": len(intakes),
        "expected_fee_usd": round(sum(r["evaluation"]["expected_fee_usd"] for r in queue), 2),
        "contracted_fee_usd": round(sum(r["evaluation"]["contracted_fee_usd"] for r in queue), 2),
        "invoiced_fee_usd": round(sum(r["evaluation"]["invoiced_fee_usd"] for r in queue), 2),
        "collected_fee_usd": round(sum(r["evaluation"]["collected_fee_usd"] for r in queue), 2),
    }
    return {
        "status": "ok",
        "operating_model": "zero-own-capital-intermediary",
        "primary_metric": "collected_fee_usd",
        "kpis": kpis,
        "queue": queue,
    }


@app.patch("/owner/profit-machine/{prospect_id}")
async def update_profit_control(
    prospect_id: str,
    payload: ProfitControlIn,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = _require_owner(x_role, authorization, x_employee_id)
    backend = get_backend()
    prospects = await backend.select("external_trade_prospects", params={"prospect_id": f"eq.{prospect_id}", "limit": "1"}) or []
    if not prospects:
        raise HTTPException(404, "Opportunity not found")

    ts = now()
    row = payload.model_dump()
    row.update({
        "control_id": f"profit_{prospect_id}",
        "prospect_id": prospect_id,
        "organization_id": ORG_ID,
        "updated_by": actor["id"],
        "updated_at": ts,
    })
    existing = await backend.select("profit_controls", params={"prospect_id": f"eq.{prospect_id}", "limit": "1"}) or []
    if existing:
        await backend.patch("profit_controls", row, params={"prospect_id": f"eq.{prospect_id}"})
    else:
        row["created_at"] = ts
        await backend.insert("profit_controls", row)

    evaluation = _evaluate(prospects[0], row)
    return {"status": "ok", "prospect_id": prospect_id, "control": row, "evaluation": evaluation}


@app.get("/owner/profit-machine/follow-up-queue")
async def follow_up_queue(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    _require_owner(x_role, authorization, x_employee_id)
    queue = await _load_queue()
    backend = get_backend()
    customers = await backend.select("customer_accounts", params={"order": "updated_at.desc", "limit": "5000"}) or []
    ts = now()

    actions: list[dict] = []
    for row in queue:
        p = row["prospect"]
        c = row["control"]
        e = row["evaluation"]
        if str(c.get("revenue_stage") or "PIPELINE").upper() in {"COLLECTED", "LOST"}:
            continue
        actions.append({
            "type": "deal_follow_up",
            "id": p.get("prospect_id"),
            "priority": "P0" if e["close_score"] >= 75 else "P1",
            "title": p.get("opportunity_title"),
            "next_action": c.get("next_action") or p.get("next_action") or (e["blockers"][0] if e["blockers"] else "Advance closing"),
            "next_follow_up_at": c.get("next_follow_up_at"),
            "blockers": e["blockers"],
        })

    for customer in customers:
        due = str(customer.get("next_follow_up_at") or "")
        if due and due <= ts and str(customer.get("sales_status") or "").upper() not in {"DO_NOT_CONTACT", "CLOSED_LOST"}:
            actions.append({
                "type": "buyer_follow_up",
                "id": customer.get("customer_id"),
                "priority": "P0",
                "title": customer.get("legal_name") or customer.get("trade_name") or customer.get("email"),
                "next_action": "Follow up on buyer requirement and capture the next commercial commitment.",
                "next_follow_up_at": due,
                "blockers": [],
            })

    actions.sort(key=lambda a: (a["priority"] != "P0", str(a.get("next_follow_up_at") or "9999")))
    return {"status": "ok", "generated_at": ts, "count": len(actions), "actions": actions[:500]}
