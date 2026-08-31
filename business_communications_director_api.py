from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from business_email_registry import DEPARTMENTS

app = FastAPI(title="SAHJONY Business Communications Director", version="1.1.0", docs_url=None, redoc_url=None)

Channel = Literal["email", "whatsapp", "voice", "calendar", "web", "sms", "internal"]

DEPARTMENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "sales": ("quote", "cotiz", "price", "precio", "buy", "compr", "customer", "cliente", "order", "pedido"),
    "sourcing": ("supplier", "proveedor", "rfq", "source", "sourcing", "manufacturer", "factory", "procurement"),
    "operations": ("status", "milestone", "case", "operations", "coordination", "execution", "project"),
    "compliance": ("ofac", "sanction", "compliance", "customs", "aduana", "export control", "license", "permit"),
    "finance": ("invoice", "payment", "wire", "bank", "refund", "finance", "factura", "pago"),
    "logistics": ("freight", "shipment", "container", "carrier", "port", "delivery", "shipping", "logistics", "flete"),
    "customer_success": ("onboarding", "support", "help", "service", "retention", "follow up", "post-sale", "customer success"),
    "partnerships": ("partner", "partnership", "referral", "affiliate", "alliance", "strategic", "channel partner"),
    "marketing": ("marketing", "campaign", "social media", "press", "media", "content", "advertising", "brand"),
    "energy": ("crude", "fuel", "diesel", "gasoline", "jet fuel", "energy", "petroleum", "isotank", "barrel"),
    "cuba": ("cuba", "mipyme", "havana", "habana", "mincex", "mincin", "cuban", "cubano", "cubana"),
    "executive": ("executive", "ceo", "chairman", "administration", "escalation", "board", "strategic decision"),
}

ROUTINE_AUTONOMOUS_ACTIONS = [
    "receive and triage inbound business email",
    "reply to routine non-binding customer questions",
    "reply to routine supplier and sourcing requests",
    "request missing RFQ, shipment, compliance or scheduling information",
    "send non-binding status updates",
    "schedule, reschedule and coordinate routine business meetings",
    "send meeting confirmations and reminders",
    "route conversations across every active SAHJONY business department",
    "maintain thread context across WhatsApp, email, voice and calendar",
    "draft and send routine follow-ups when a business thread is waiting for a response",
]

FAIL_CLOSED_ACTIONS = [
    "accept, amend, terminate or waive a contract",
    "authorize payment, refund, wire, beneficiary or bank-detail changes",
    "release binding pricing, credit, financing or commercial terms without verified evidence",
    "select or commit to a supplier when the choice creates financial or legal obligation",
    "release a shipment where compliance approval is required",
    "make legal admissions or legal determinations",
    "share credentials, API keys, passwords or secrets",
]


class RouteRequest(BaseModel):
    channel: Channel
    subject: str | None = Field(default=None, max_length=500)
    content: str = Field(min_length=1, max_length=50000)
    sender: str | None = Field(default=None, max_length=500)
    current_department: str | None = Field(default=None, max_length=100)


class CommunicationMission(BaseModel):
    objective: str = Field(min_length=2, max_length=4000)
    channel: Channel | Literal["omnichannel"] = "omnichannel"
    department: str | None = Field(default=None, max_length=100)
    recipient: str | None = Field(default=None, max_length=500)
    routine_non_binding: bool = True
    calendar_coordination: bool = False
    follow_up_required: bool = True


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


def _department_map() -> dict[str, dict[str, str]]:
    return {str(d["key"]): d for d in DEPARTMENTS}


def _route_department(text: str, current: str | None = None) -> tuple[str, int, list[str]]:
    blob = text.lower()
    scores: dict[str, int] = {}
    matches: dict[str, list[str]] = {}
    for dept, words in DEPARTMENT_KEYWORDS.items():
        found = [w for w in words if w in blob]
        scores[dept] = len(found)
        matches[dept] = found
    winner = max(scores, key=scores.get) if scores else "sales"
    if scores.get(winner, 0) == 0 and current in _department_map():
        winner = str(current)
    elif scores.get(winner, 0) == 0:
        winner = "sales"
    confidence = min(99, 55 + scores.get(winner, 0) * 10)
    return winner, confidence, matches.get(winner, [])


@app.get("/communications-os/director/health")
def communications_director_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "sahjony-business-communications-director",
        "version": "1.1.0",
        "mode": "24_7_omnichannel_agentic",
        "channels": ["email", "whatsapp", "voice", "calendar", "web", "internal"],
        "departments": [d["key"] for d in DEPARTMENTS],
        "department_count": len(DEPARTMENTS),
        "email_receive_send": True,
        "autonomous_routine_email_replies": True,
        "calendar_management": True,
        "whatsapp_sales_connected": True,
        "voice_coordination": True,
        "cross_channel_context": True,
        "department_handoffs": True,
        "follow_up_engine": True,
        "binding_actions_fail_closed": True,
    }


@app.get("/communications-os/director/policy")
def communications_director_policy() -> dict[str, Any]:
    return {
        "routine_autonomous_actions": ROUTINE_AUTONOMOUS_ACTIONS,
        "fail_closed_actions": FAIL_CLOSED_ACTIONS,
        "departments": DEPARTMENTS,
        "operating_principle": "Autonomously manage routine communications and scheduling; require verified evidence and authority for binding, financial, legal, compliance-release or irreversible actions.",
    }


@app.post("/communications-os/director/route")
def communications_director_route(p: RouteRequest, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    department, confidence, matched = _route_department(f"{p.subject or ''}\n{p.content}", p.current_department)
    record = _department_map()[department]
    lower = p.content.lower()
    high_risk = any(term in lower for term in ("wire", "bank detail", "beneficiary", "contract", "sign agreement", "refund", "sanction release", "legal admission"))
    return {
        "status": "routed",
        "channel": p.channel,
        "department": department,
        "department_name": record["name"],
        "department_email": record["email"],
        "confidence": confidence,
        "matched_signals": matched,
        "autonomous_reply_allowed": not high_risk,
        "owner_approval_required": high_risk,
        "recommended_action": "prepare and send routine response" if not high_risk else "prepare response and escalate before binding action",
    }


@app.post("/communications-os/director/missions/plan")
def communications_mission_plan(p: CommunicationMission, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    dept = p.department if p.department in _department_map() else _route_department(p.objective)[0]
    high_risk = not p.routine_non_binding
    steps = [
        "load customer/contact and conversation context",
        f"assign mission to {dept} department",
        "choose the best communication channel and preserve sender language",
        "prepare concise business response or information request",
    ]
    if p.calendar_coordination:
        steps += ["check calendar availability", "schedule or propose meeting slots", "send calendar confirmation/reminder"]
    if p.follow_up_required:
        steps += ["create follow-up state", "continue until reply, resolution, opt-out or escalation threshold"]
    if high_risk:
        steps += ["stop before any binding or irreversible action", "request owner authorization with evidence summary"]
    else:
        steps += ["send routine non-binding communication autonomously", "record communication outcome and next action"]
    return {
        "status": "planned",
        "department": dept,
        "channel": p.channel,
        "recipient": p.recipient,
        "autonomous_execution_allowed": not high_risk,
        "owner_approval_required": high_risk,
        "steps": steps,
    }
