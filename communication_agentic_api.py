from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status
from voice_agent_api import _openai_key, _reasoning_model

app = FastAPI(title="SAHJONY Agentic Communication Core", version="2.0.0", docs_url=None, redoc_url=None)

Priority = Literal["urgent", "high", "normal", "low"]
AutonomyMode = Literal["ADVISORY", "ASSIST", "AUTONOMOUS_NONBINDING"]
EndpointChannel = Literal["browser", "phone", "whatsapp", "sms", "email", "portal"]
ConsentStatus = Literal["UNKNOWN", "CONSENTED", "TRANSACTIONAL_ONLY", "REVOKED", "DO_NOT_CONTACT"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


def _agent_mcp_token() -> str:
    key = _openai_key()
    if not key:
        return ""
    return hashlib.sha256(("sahjony-agentic-communications:" + key).encode()).hexdigest()


def _normalize_phone(value: str) -> str:
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        candidate = "+" + digits
    elif len(digits) == 10:
        candidate = "+1" + digits
    elif 11 <= len(digits) <= 15:
        candidate = "+" + digits
    else:
        return raw
    return candidate if re.fullmatch(r"\+[1-9]\d{6,14}", candidate) else raw


def _normalize_destination(channel: str, value: str) -> str:
    if channel in {"phone", "whatsapp", "sms"}:
        return _normalize_phone(value)
    if channel == "email":
        return value.strip().lower()
    return value.strip()


def _endpoint_usable(row: dict[str, Any], *, marketing: bool = False) -> bool:
    if bool(row.get("do_not_contact")):
        return False
    status = str(row.get("consent_status") or "UNKNOWN").upper()
    if status in {"REVOKED", "DO_NOT_CONTACT"}:
        return False
    if marketing:
        return status == "CONSENTED"
    return status in {"CONSENTED", "TRANSACTIONAL_ONLY", "UNKNOWN"}


class ContactCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=240)
    title: str | None = Field(default=None, max_length=160)
    country_code: str | None = Field(default=None, max_length=3)
    preferred_language: str = Field(default="auto", max_length=40)
    timezone: str | None = Field(default=None, max_length=80)
    lead_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    supplier_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=6000)


class EndpointCreate(BaseModel):
    channel: EndpointChannel
    destination: str = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=120)
    preferred: bool = False
    verified: bool = False
    verification_source: str | None = Field(default=None, max_length=240)
    consent_status: ConsentStatus = "UNKNOWN"
    consent_source: str | None = Field(default=None, max_length=240)


class MissionCreate(BaseModel):
    contact_id: str | None = Field(default=None, max_length=180)
    conversation_id: str | None = Field(default=None, max_length=180)
    trade_case_id: str | None = Field(default=None, max_length=180)
    objective: str = Field(min_length=3, max_length=4000)
    success_criteria: str | None = Field(default=None, max_length=4000)
    priority: Priority = "normal"
    autonomy_mode: AutonomyMode = "ASSIST"
    allowed_channels: list[str] = Field(default_factory=list, max_length=10)
    max_outbound_attempts: int = Field(default=3, ge=0, le=20)


class MissionPlanRequest(BaseModel):
    marketing: bool = False
    preferred_channel: str | None = Field(default=None, max_length=40)
    extra_context: str | None = Field(default=None, max_length=5000)


async def _contact(contact_id: str) -> dict[str, Any]:
    rows = await get_backend().select("communication_contacts", params={"contact_id": f"eq.{contact_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(404, "Communication contact not found")
    return rows[0]


async def _endpoints(contact_id: str) -> list[dict[str, Any]]:
    return await get_backend().select(
        "communication_contact_endpoints",
        params={"contact_id": f"eq.{contact_id}", "order": "preferred.desc,updated_at.desc", "limit": "100"},
    ) or []


async def _route(contact_id: str, *, marketing: bool = False) -> dict[str, Any]:
    contact = await _contact(contact_id)
    endpoints = await _endpoints(contact_id)
    if str(contact.get("status") or "ACTIVE").upper() == "DO_NOT_CONTACT":
        return {"contact_id": contact_id, "route_ready": False, "reason": "contact_do_not_contact", "routes": []}

    ranked: list[dict[str, Any]] = []
    order = {"browser": 0, "whatsapp": 1, "email": 2, "phone": 3, "sms": 4, "portal": 5}
    for ep in endpoints:
        if not _endpoint_usable(ep, marketing=marketing):
            continue
        ranked.append({
            "endpoint_id": ep.get("endpoint_id"),
            "channel": ep.get("channel"),
            "destination": ep.get("destination"),
            "normalized_destination": ep.get("normalized_destination"),
            "verified": bool(ep.get("verified")),
            "preferred": bool(ep.get("preferred")),
            "consent_status": ep.get("consent_status"),
        })
    ranked.sort(key=lambda x: (not x["preferred"], not x["verified"], order.get(str(x["channel"]), 99)))
    return {
        "contact_id": contact_id,
        "route_ready": bool(ranked),
        "marketing": marketing,
        "routes": ranked,
        "fail_closed_marketing": True,
    }


@app.get("/communications-os/agentic/health")
async def agentic_health() -> dict[str, Any]:
    persistence = persistent_backend_status()
    return {
        "status": "ok" if persistence.get("configured") else "configuration_required",
        "service": "sahjony-agentic-communication-core",
        "version": "2.0.0",
        "contact_360": True,
        "mission_engine": True,
        "next_best_action": True,
        "mcp_tools": ["get_contact_context", "get_trade_context", "route_contact", "create_follow_up", "record_note", "request_human_handoff"],
        "binding_tools_exposed": False,
        "autonomous_nonbinding_only": True,
        "openai_configured": bool(_openai_key()),
        "reasoning_model": _reasoning_model(),
        "persistence": persistence.get("provider"),
        "fail_closed": True,
    }


@app.get("/communications-os/contacts")
async def list_contacts(
    authorization: str | None = Header(None, alias="Authorization"),
    search: str | None = None,
    limit: int = 200,
):
    _owner(authorization)
    rows = await get_backend().select("communication_contacts", params={"order": "updated_at.desc", "limit": str(max(1, min(limit, 500)))}) or []
    if search:
        needle = search.strip().lower()
        rows = [r for r in rows if needle in " ".join(str(r.get(k) or "") for k in ("display_name", "company", "title", "country_code")).lower()]
    return {"status": "ok", "count": len(rows), "contacts": rows}


@app.post("/communications-os/contacts")
async def create_contact(payload: ContactCreate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    contact_id = f"ctc_{secrets.token_urlsafe(12)}"
    ts = _now()
    row = {"contact_id": contact_id, **payload.model_dump(), "status": "ACTIVE", "created_by": "owner", "created_at": ts, "updated_at": ts}
    await get_backend().insert("communication_contacts", row)
    return {"status": "created", "contact": row}


@app.get("/communications-os/contacts/{contact_id}")
async def contact_360(contact_id: str, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    contact = await _contact(contact_id)
    endpoints = await _endpoints(contact_id)
    conversations = await get_backend().select("communication_conversations", params={"limit": "100", "order": "updated_at.desc"}) or []
    linked = [c for c in conversations if any(contact.get(k) and c.get(k) == contact.get(k) for k in ("lead_id", "customer_id", "trade_case_id"))]
    notes = await get_backend().select("communication_agent_notes", params={"contact_id": f"eq.{contact_id}", "order": "created_at.desc", "limit": "100"}) or []
    missions = await get_backend().select("communication_missions", params={"contact_id": f"eq.{contact_id}", "order": "updated_at.desc", "limit": "100"}) or []
    return {"status": "ok", "contact": contact, "endpoints": endpoints, "conversations": linked, "notes": notes, "missions": missions, "route": await _route(contact_id)}


@app.post("/communications-os/contacts/{contact_id}/endpoints")
async def add_endpoint(contact_id: str, payload: EndpointCreate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    await _contact(contact_id)
    ts = _now()
    endpoint_id = f"cep_{secrets.token_urlsafe(12)}"
    row = {
        "endpoint_id": endpoint_id,
        "contact_id": contact_id,
        **payload.model_dump(),
        "normalized_destination": _normalize_destination(payload.channel, payload.destination),
        "verified_at": ts if payload.verified else None,
        "consented_at": ts if payload.consent_status in {"CONSENTED", "TRANSACTIONAL_ONLY"} else None,
        "revoked_at": ts if payload.consent_status in {"REVOKED", "DO_NOT_CONTACT"} else None,
        "created_at": ts,
        "updated_at": ts,
    }
    if payload.preferred:
        await get_backend().patch("communication_contact_endpoints", {"preferred": False, "updated_at": ts}, params={"contact_id": f"eq.{contact_id}", "channel": f"eq.{payload.channel}"})
    await get_backend().insert("communication_contact_endpoints", row)
    return {"status": "created", "endpoint": row}


@app.get("/communications-os/contacts/{contact_id}/route")
async def route_contact(contact_id: str, marketing: bool = False, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    return await _route(contact_id, marketing=marketing)


@app.post("/communications-os/missions")
async def create_mission(payload: MissionCreate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if payload.contact_id:
        await _contact(payload.contact_id)
    ts = _now()
    mission_id = f"cmis_{secrets.token_urlsafe(12)}"
    row = {
        "mission_id": mission_id,
        **payload.model_dump(),
        "status": "READY",
        "binding_actions_allowed": False,
        "owner_approved": True,
        "approved_at": ts,
        "created_by": "owner",
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_missions", row)
    return {"status": "created", "mission": row}


async def _sol_plan(mission: dict[str, Any], contact: dict[str, Any] | None, route: dict[str, Any], extra: str | None) -> dict[str, Any] | None:
    if not _openai_key():
        return None
    prompt = {
        "mission": {k: mission.get(k) for k in ("objective", "success_criteria", "priority", "autonomy_mode", "trade_case_id")},
        "contact": {k: contact.get(k) for k in ("display_name", "company", "title", "country_code", "preferred_language")} if contact else None,
        "available_routes": route.get("routes", [])[:8],
        "extra_context": extra,
    }
    instructions = (
        "You are GPT-5.6 Sol planning the next non-binding communication action for SAHJONY Global Trade. "
        "Return strict JSON with keys summary, recommended_channel, action_type, message_objective, human_review_reason. "
        "Never authorize price acceptance, contracts, payments, bank changes, financing, exclusivity, KYC/sanctions/export decisions, legal admissions, or regulatory conclusions. "
        "Choose only from available routes. If no safe route exists, set recommended_channel to null and action_type to HUMAN_HANDOFF."
    )
    body = {"model": _reasoning_model(), "instructions": instructions, "input": json.dumps(prompt), "max_output_tokens": 500}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {_openai_key()}", "Content-Type": "application/json"}, json=body)
        if response.status_code >= 400:
            return None
        data = response.json()
        text = data.get("output_text") or ""
        if not text:
            chunks = []
            for item in data.get("output") or []:
                for content in (item.get("content") or []) if isinstance(item, dict) else []:
                    if isinstance(content, dict) and isinstance(content.get("text"), str):
                        chunks.append(content["text"])
            text = "".join(chunks)
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        return None
    return None


@app.post("/communications-os/missions/{mission_id}/plan")
async def plan_mission(mission_id: str, payload: MissionPlanRequest, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    rows = await get_backend().select("communication_missions", params={"mission_id": f"eq.{mission_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(404, "Communication mission not found")
    mission = rows[0]
    contact = await _contact(str(mission.get("contact_id"))) if mission.get("contact_id") else None
    route = await _route(str(mission.get("contact_id")), marketing=payload.marketing) if mission.get("contact_id") else {"routes": [], "route_ready": False}
    plan = await _sol_plan(mission, contact, route, payload.extra_context)
    if not plan:
        first = next((r for r in route.get("routes", []) if not payload.preferred_channel or r.get("channel") == payload.preferred_channel), None)
        plan = {
            "summary": "Use the highest-confidence consent-compatible route for a non-binding follow-up." if first else "No safe communication route is available; require human review.",
            "recommended_channel": first.get("channel") if first else None,
            "action_type": "FOLLOW_UP_TASK" if first else "HUMAN_HANDOFF",
            "message_objective": mission.get("objective"),
            "human_review_reason": None if first else "No usable endpoint/consent route",
            "planner": "deterministic_fallback",
        }
    else:
        plan["planner"] = _reasoning_model()

    action_id = f"cact_{secrets.token_urlsafe(12)}"
    safe_action = str(plan.get("action_type") or "FOLLOW_UP_TASK").upper()
    if safe_action not in {"FOLLOW_UP_TASK", "HUMAN_HANDOFF", "EMAIL_DRAFT", "WHATSAPP_DRAFT", "SMS_DRAFT", "PORTAL_MESSAGE", "PRIVATE_ROOM_INVITE", "AI_ROOM_INVITE", "CALL_INVITE", "INTERNAL_NOTE"}:
        safe_action = "FOLLOW_UP_TASK"
    requires_approval = safe_action not in {"FOLLOW_UP_TASK", "INTERNAL_NOTE", "HUMAN_HANDOFF"}
    ts = _now()
    action = {
        "action_id": action_id,
        "mission_id": mission_id,
        "contact_id": mission.get("contact_id"),
        "conversation_id": mission.get("conversation_id"),
        "trade_case_id": mission.get("trade_case_id"),
        "action_type": safe_action,
        "channel": plan.get("recommended_channel"),
        "destination": None,
        "payload": {"plan": plan, "objective": mission.get("objective")},
        "status": "WAITING_APPROVAL" if requires_approval else "QUEUED",
        "requires_owner_approval": requires_approval,
        "owner_approved": False,
        "attempt_count": 0,
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_action_queue", action)
    await get_backend().patch("communication_missions", {"status": "RUNNING", "updated_at": ts}, params={"mission_id": f"eq.{mission_id}"})
    return {"status": "planned", "mission_id": mission_id, "plan": plan, "action": action, "binding_actions_allowed": False}


async def _mcp_contact_context(args: dict[str, Any]) -> dict[str, Any]:
    contact_id = str(args.get("contact_id") or "").strip()
    if not contact_id:
        return {"error": "contact_id_required"}
    try:
        contact = await _contact(contact_id)
    except HTTPException:
        return {"error": "contact_not_found"}
    return {"contact": {k: contact.get(k) for k in ("contact_id", "display_name", "company", "title", "country_code", "preferred_language", "lead_id", "customer_id", "supplier_id", "trade_case_id", "status")}, "route": await _route(contact_id)}


async def _mcp_trade_context(args: dict[str, Any]) -> dict[str, Any]:
    case_id = str(args.get("trade_case_id") or "").strip()
    if not case_id:
        return {"error": "trade_case_id_required"}
    datasets: dict[str, Any] = {}
    for table, key in (("managed_trade_cases", "managed_case_id"), ("trade_cases", "trade_case_id")):
        try:
            rows = await get_backend().select(table, params={key: f"eq.{case_id}", "limit": "1"}) or []
            if rows:
                datasets[table] = rows[0]
        except Exception:
            continue
    if not datasets:
        return {"error": "trade_case_not_found"}
    return {"trade_case_id": case_id, "context": datasets, "binding_decisions": "owner_or_governed_backend_only"}


async def _mcp_follow_up(args: dict[str, Any]) -> dict[str, Any]:
    objective = str(args.get("objective") or "").strip()[:3000]
    if not objective:
        return {"error": "objective_required"}
    ts = _now()
    action_id = f"cact_{secrets.token_urlsafe(12)}"
    row = {
        "action_id": action_id,
        "mission_id": args.get("mission_id"),
        "contact_id": args.get("contact_id"),
        "conversation_id": args.get("conversation_id"),
        "trade_case_id": args.get("trade_case_id"),
        "action_type": "FOLLOW_UP_TASK",
        "channel": None,
        "destination": None,
        "payload": {"objective": objective, "created_by": "realtime_agent"},
        "status": "QUEUED",
        "requires_owner_approval": False,
        "owner_approved": False,
        "attempt_count": 0,
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_action_queue", row)
    return {"status": "queued", "action_id": action_id, "binding": False}


async def _mcp_note(args: dict[str, Any]) -> dict[str, Any]:
    content = str(args.get("content") or "").strip()[:8000]
    if not content:
        return {"error": "content_required"}
    note_type = str(args.get("note_type") or "SUMMARY").upper()
    if note_type not in {"SUMMARY", "FOLLOW_UP", "QUALIFICATION", "RISK", "HANDOFF", "CUSTOMER_REQUEST", "SUPPLIER_REQUEST"}:
        note_type = "SUMMARY"
    note_id = f"can_{secrets.token_urlsafe(12)}"
    row = {
        "note_id": note_id,
        "contact_id": args.get("contact_id"),
        "conversation_id": args.get("conversation_id"),
        "room_id": args.get("room_id"),
        "trade_case_id": args.get("trade_case_id"),
        "note_type": note_type,
        "content": content,
        "source": "openai_realtime_agent",
        "contains_recording": False,
        "created_at": _now(),
    }
    await get_backend().insert("communication_agent_notes", row)
    return {"status": "recorded", "note_id": note_id, "recording_created": False}


async def _mcp_handoff(args: dict[str, Any]) -> dict[str, Any]:
    reason = str(args.get("reason") or "Human review requested").strip()[:1200]
    urgency = str(args.get("urgency") or "high").lower()
    if urgency not in {"urgent", "high", "normal", "low"}:
        urgency = "high"
    handoff_id = f"handoff_{secrets.token_urlsafe(12)}"
    ts = _now()
    row = {
        "handoff_id": handoff_id,
        "status": "REQUESTED",
        "conversation_id": args.get("conversation_id"),
        "room_id": args.get("room_id"),
        "reason": reason,
        "urgency": urgency,
        "requested_by": "ai",
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_handoffs", row)
    return {"status": "requested", "handoff_id": handoff_id}


_MCP_TOOLS = [
    {"name": "get_contact_context", "description": "Read approved SAHJONY contact context and safe communication routes.", "inputSchema": {"type": "object", "properties": {"contact_id": {"type": "string"}}, "required": ["contact_id"]}},
    {"name": "get_trade_context", "description": "Read existing trade-case context. Never authorizes a commercial or compliance decision.", "inputSchema": {"type": "object", "properties": {"trade_case_id": {"type": "string"}}, "required": ["trade_case_id"]}},
    {"name": "route_contact", "description": "Return consent-compatible contact routes without sending anything.", "inputSchema": {"type": "object", "properties": {"contact_id": {"type": "string"}, "marketing": {"type": "boolean"}}, "required": ["contact_id"]}},
    {"name": "create_follow_up", "description": "Create an internal non-binding follow-up task. Does not send a message or make a commitment.", "inputSchema": {"type": "object", "properties": {"objective": {"type": "string"}, "contact_id": {"type": "string"}, "conversation_id": {"type": "string"}, "trade_case_id": {"type": "string"}, "mission_id": {"type": "string"}}, "required": ["objective"]}},
    {"name": "record_note", "description": "Store a concise text note; never stores call audio/video.", "inputSchema": {"type": "object", "properties": {"content": {"type": "string"}, "note_type": {"type": "string"}, "contact_id": {"type": "string"}, "conversation_id": {"type": "string"}, "room_id": {"type": "string"}, "trade_case_id": {"type": "string"}}, "required": ["content"]}},
    {"name": "request_human_handoff", "description": "Request owner/employee takeover for sensitive, binding, uncertain or escalated matters.", "inputSchema": {"type": "object", "properties": {"reason": {"type": "string"}, "urgency": {"type": "string"}, "conversation_id": {"type": "string"}, "room_id": {"type": "string"}}, "required": ["reason"]}},
]


@app.api_route("/communications-os/mcp/agent", methods=["GET", "POST"])
async def agent_mcp(request: Request):
    authorization = request.headers.get("Authorization", "")
    expected = _agent_mcp_token()
    supplied = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(401, "Invalid communication-agent MCP credential")
    if request.method == "GET":
        return {"status": "ok", "server": "sahjony-agentic-communications", "tools": [t["name"] for t in _MCP_TOOLS], "binding_tools": False}
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid MCP JSON-RPC payload")
    method = str(payload.get("method") or "")
    request_id = payload.get("id")
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        result: Any = {"protocolVersion": str((payload.get("params") or {}).get("protocolVersion") or "2025-03-26"), "capabilities": {"tools": {}}, "serverInfo": {"name": "sahjony-agentic-communications", "version": "2.0.0"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": _MCP_TOOLS}
    elif method == "tools/call":
        params = payload.get("params") or {}
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        if name == "get_contact_context":
            value = await _mcp_contact_context(args)
        elif name == "get_trade_context":
            value = await _mcp_trade_context(args)
        elif name == "route_contact":
            contact_id = str(args.get("contact_id") or "")
            value = await _route(contact_id, marketing=bool(args.get("marketing", False))) if contact_id else {"error": "contact_id_required"}
        elif name == "create_follow_up":
            value = await _mcp_follow_up(args)
        elif name == "record_note":
            value = await _mcp_note(args)
        elif name == "request_human_handoff":
            value = await _mcp_handoff(args)
        else:
            return JSONResponse(status_code=200, content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Tool not found"}})
        result = {"content": [{"type": "text", "text": json.dumps(value, default=str)}], "isError": bool(isinstance(value, dict) and value.get("error"))}
    else:
        return JSONResponse(status_code=200, content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}})
    return {"jsonrpc": "2.0", "id": request_id, "result": result}
