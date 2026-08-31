from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from business_email_registry import DEPARTMENTS
from business_communications_director_api import _route_department
from business_os_executor_api import execute_mission_internal
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY AI-Operated Business OS", version="1.1.0", docs_url=None, redoc_url=None)

Priority = Literal["urgent", "high", "normal", "low"]

AUTONOMOUS_DOMAINS = {
    "communications": ["email", "whatsapp", "voice", "calendar", "web", "follow_up"],
    "sales": ["lead_triage", "qualification", "crm_updates", "rfq_preparation", "next_best_action", "follow_up"],
    "sourcing": ["supplier_research", "rfq_distribution", "offer_comparison", "supplier_shortlisting"],
    "operations": ["task_coordination", "milestone_tracking", "shipment_status", "document_requests"],
    "finance": ["invoice_tracking", "margin_analysis", "reconciliation_research", "payment_status"],
    "compliance": ["screening_research", "document_checklists", "release_readiness", "escalation"],
    "application": ["health_monitoring", "deployment_diagnostics", "data_quality_checks", "incident_triage"],
    "executive": ["daily_brief", "priority_ranking", "department_routing", "exception_management"],
}

FAIL_CLOSED = [
    "send or authorize funds",
    "change beneficiary or bank details",
    "accept, amend, terminate or waive a contract",
    "issue binding commercial terms without verified cost evidence and configured authority",
    "release a shipment when compliance approval is required",
    "make legal admissions or legal determinations",
    "delete critical production data without an explicit governed recovery path",
    "disable security controls or expose credentials",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if not verify_owner_token(token):
        raise HTTPException(403, "Invalid owner credential")


def _department_record(key: str) -> dict[str, str]:
    for department in DEPARTMENTS:
        if str(department.get("key")) == key:
            return department
    return {"key": key, "name": key.replace("_", " ").title(), "email": "", "function": ""}


def _is_high_risk(text: str) -> bool:
    blob = text.lower()
    signals = (
        "wire", "send money", "bank detail", "beneficiary", "sign contract", "accept contract",
        "terminate contract", "refund", "binding price", "binding quote", "legal admission",
        "release shipment", "delete production", "api key", "password", "disable security",
    )
    return any(signal in blob for signal in signals)


def _mission_steps(objective: str, department: str, high_risk: bool) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {"order": 1, "action": "load_context", "autonomous": True, "detail": "Load CRM, conversation, deal, supplier, shipment and application context relevant to the objective."},
        {"order": 2, "action": "analyze", "autonomous": True, "detail": "Analyze objective, evidence, urgency, missing information, expected value and operational risk."},
        {"order": 3, "action": "route", "autonomous": True, "detail": f"Assign primary ownership to {department} and create cross-department handoffs when required."},
        {"order": 4, "action": "execute_reversible_work", "autonomous": True, "detail": "Execute routine reversible work through durable action queues: research, communications, CRM updates, follow-ups, scheduling, RFQ preparation and status coordination."},
        {"order": 5, "action": "verify_evidence", "autonomous": True, "detail": "Verify durable execution evidence before advancing mission state."},
    ]
    if high_risk:
        steps.append({"order": 6, "action": "governance_gate", "autonomous": False, "detail": "Stop before binding, financial, legal, compliance-release, destructive or irreversible action and request owner authorization with evidence."})
    else:
        steps.append({"order": 6, "action": "close_loop", "autonomous": True, "detail": "Record outcome, update next action, schedule follow-up and continue until resolved or an exception gate is reached."})
    return steps


class MissionCreate(BaseModel):
    objective: str = Field(min_length=3, max_length=5000)
    department: str | None = Field(default=None, max_length=100)
    priority: Priority = "normal"
    source: str = Field(default="owner", max_length=80)
    customer_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    desired_outcome: str | None = Field(default=None, max_length=3000)
    context: dict[str, Any] = Field(default_factory=dict)


@app.get("/business-os/health")
async def business_os_health() -> dict[str, Any]:
    persistence = persistent_backend_status()
    return {
        "status": "ok" if persistence.get("configured") else "configuration_required",
        "service": "sahjony-ai-operated-business-os",
        "version": "1.1.0",
        "operating_model": "exception_driven_autonomous_execution",
        "departments": [d["key"] for d in DEPARTMENTS],
        "department_count": len(DEPARTMENTS),
        "autonomous_domains": AUTONOMOUS_DOMAINS,
        "communications_os": True,
        "whatsapp_sales": True,
        "email_agent": True,
        "calendar_management": True,
        "crm_orchestration": True,
        "supplier_sourcing": True,
        "operations_coordination": True,
        "finance_analysis": True,
        "compliance_research": True,
        "application_operations": True,
        "executive_exception_management": True,
        "mission_executor": True,
        "auto_execute_low_risk_missions": True,
        "durable_execution_verification": True,
        "binding_actions_fail_closed": True,
        "persistent_event_log": bool(persistence.get("configured")),
        "persistence_provider": persistence.get("provider"),
    }


@app.get("/business-os/policy")
def business_os_policy() -> dict[str, Any]:
    return {
        "autonomous_domains": AUTONOMOUS_DOMAINS,
        "fail_closed_actions": FAIL_CLOSED,
        "rule": "Autonomously execute routine reversible work through durable queues and verify evidence; stop before binding, financial, legal, compliance-release, destructive or irreversible actions unless governed authority exists.",
    }


@app.post("/business-os/missions")
async def create_business_mission(payload: MissionCreate, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    department = payload.department if payload.department and any(d["key"] == payload.department for d in DEPARTMENTS) else _route_department(payload.objective)[0]
    record = _department_record(department)
    high_risk = _is_high_risk(f"{payload.objective}\n{payload.desired_outcome or ''}")
    mission_id = f"mission_{secrets.token_urlsafe(14)}"
    ts = _now()
    steps = _mission_steps(payload.objective, department, high_risk)
    next_action = next((step for step in steps if step["autonomous"]), steps[0])
    row = {
        "event_id": f"evt_{secrets.token_urlsafe(16)}",
        "event_type": "task",
        "source_type": "business_os_mission",
        "source_id": mission_id,
        "trade_case_id": payload.trade_case_id,
        "customer_id": payload.customer_id,
        "actor_role": "owner",
        "actor_id": "owner",
        "visibility": "internal",
        "title": payload.objective[:240],
        "summary": payload.desired_outcome or payload.objective,
        "action_required": high_risk,
        "action_label": "Owner governance gate" if high_risk else "Autonomous execution",
        "priority": "urgent" if payload.priority == "urgent" else ("high" if payload.priority == "high" else "normal"),
        "event_status": "open",
        "payload": {
            "mission_id": mission_id,
            "department": department,
            "department_name": record.get("name"),
            "department_email": record.get("email"),
            "source": payload.source,
            "desired_outcome": payload.desired_outcome,
            "context": payload.context,
            "high_risk": high_risk,
            "autonomous_execution_allowed": not high_risk,
            "steps": steps,
            "next_action": next_action,
        },
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("business_events", row)

    execution: dict[str, Any] | None = None
    if not high_risk:
        try:
            execution = await execute_mission_internal(mission_id)
        except Exception as exc:
            execution = {"status": "execution_failed", "error": type(exc).__name__, "retry_available": True}

    return {
        "status": "mission_created_and_executed" if execution and execution.get("status") == "completed" else ("governance_required" if high_risk else "mission_created"),
        "mission_id": mission_id,
        "department": department,
        "department_name": record.get("name"),
        "priority": payload.priority,
        "autonomous_execution_allowed": not high_risk,
        "owner_governance_required": high_risk,
        "next_action": next_action,
        "plan": steps,
        "execution": execution,
        "event_id": row["event_id"],
    }


@app.get("/business-os/command-center")
async def business_os_command_center(authorization: str | None = Header(None, alias="Authorization"), limit: int = 100) -> dict[str, Any]:
    _owner(authorization)
    safe_limit = str(max(1, min(limit, 250)))
    events = await get_backend().select("business_events", params={"order": "created_at.desc", "limit": safe_limit})
    communications = await get_backend().select("communication_conversations", params={"order": "updated_at.desc", "limit": "50"})
    handoffs = await get_backend().select("communication_handoffs", params={"status": "eq.REQUESTED", "order": "created_at.desc", "limit": "50"})
    missions = [e for e in (events or []) if e.get("source_type") == "business_os_mission"]
    executions = [e for e in (events or []) if e.get("source_type") == "business_os_execution"]
    gates = [e for e in (events or []) if bool(e.get("action_required"))]
    return {
        "status": "ok",
        "health": await business_os_health(),
        "missions": missions,
        "executions": executions,
        "open_governance_gates": gates,
        "recent_business_events": events or [],
        "open_communications": communications or [],
        "requested_handoffs": handoffs or [],
        "operating_principle": "AI executes routine operations continuously; owner manages exceptions and governed commitments.",
    }
