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
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status
from voice_agent_api import _openai_key, _reasoning_model

app = FastAPI(title="SAHJONY Communications Platform", version="3.0.0", docs_url=None, redoc_url=None)

DEFAULT_WORKSPACE_ID = os.getenv("COMMUNICATION_DEFAULT_WORKSPACE_ID", "ws_sahjony_global_trade").strip() or "ws_sahjony_global_trade"
Priority = Literal["urgent", "high", "normal", "low"]
AutonomyMode = Literal["ADVISORY", "ASSIST", "AUTONOMOUS_NONBINDING"]
ConsentStatus = Literal["UNKNOWN", "CONSENTED", "TRANSACTIONAL_ONLY", "REVOKED", "DO_NOT_CONTACT"]
EndpointChannel = Literal["browser", "phone", "whatsapp", "sms", "email", "portal"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


def _mcp_token() -> str:
    key = _openai_key()
    if not key:
        return ""
    return hashlib.sha256(("sahjony-communications-platform:" + key).encode()).hexdigest()


def _clean_context_type(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", value.strip()).strip("_").lower()
    if not value:
        raise HTTPException(422, "context_type is required")
    return value[:100]


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
    status = str(row.get("consent_status") or "UNKNOWN").upper()
    if bool(row.get("do_not_contact")) or status in {"REVOKED", "DO_NOT_CONTACT"}:
        return False
    if marketing:
        return status == "CONSENTED"
    return status in {"UNKNOWN", "CONSENTED", "TRANSACTIONAL_ONLY"}


async def _workspace(workspace_id: str) -> dict[str, Any]:
    rows = await get_backend().select("communication_workspaces", params={"workspace_id": f"eq.{workspace_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(404, "Communication workspace not found")
    return rows[0]


async def _industry_pack(pack_id: str) -> dict[str, Any]:
    rows = await get_backend().select("communication_industry_packs", params={"pack_id": f"eq.{pack_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(404, "Industry pack not found")
    return rows[0]


async def _contact(contact_id: str, workspace_id: str | None = None) -> dict[str, Any]:
    params = {"contact_id": f"eq.{contact_id}", "limit": "1"}
    rows = await get_backend().select("communication_contacts", params=params) or []
    if not rows:
        raise HTTPException(404, "Communication contact not found")
    row = rows[0]
    actual = str(row.get("workspace_id") or DEFAULT_WORKSPACE_ID)
    if workspace_id and actual != workspace_id:
        raise HTTPException(404, "Communication contact not found in workspace")
    return row


async def _context(context_id: str, workspace_id: str | None = None) -> dict[str, Any]:
    rows = await get_backend().select("communication_contexts", params={"context_id": f"eq.{context_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(404, "Communication context not found")
    row = rows[0]
    if workspace_id and row.get("workspace_id") != workspace_id:
        raise HTTPException(404, "Communication context not found in workspace")
    return row


async def _routes(contact_id: str, workspace_id: str, *, marketing: bool = False) -> dict[str, Any]:
    contact = await _contact(contact_id, workspace_id)
    if str(contact.get("status") or "ACTIVE").upper() == "DO_NOT_CONTACT":
        return {"workspace_id": workspace_id, "contact_id": contact_id, "route_ready": False, "reason": "contact_do_not_contact", "routes": []}
    endpoints = await get_backend().select(
        "communication_contact_endpoints",
        params={"contact_id": f"eq.{contact_id}", "order": "preferred.desc,updated_at.desc", "limit": "100"},
    ) or []
    rank = {"browser": 0, "whatsapp": 1, "email": 2, "phone": 3, "sms": 4, "portal": 5}
    usable = []
    for row in endpoints:
        if not _endpoint_usable(row, marketing=marketing):
            continue
        usable.append({
            "endpoint_id": row.get("endpoint_id"),
            "channel": row.get("channel"),
            "destination": row.get("destination"),
            "normalized_destination": row.get("normalized_destination"),
            "preferred": bool(row.get("preferred")),
            "verified": bool(row.get("verified")),
            "consent_status": row.get("consent_status"),
        })
    usable.sort(key=lambda item: (not item["preferred"], not item["verified"], rank.get(str(item["channel"]), 99)))
    return {"workspace_id": workspace_id, "contact_id": contact_id, "route_ready": bool(usable), "marketing": marketing, "routes": usable}


async def _capability_policy(workspace_id: str, capability_key: str) -> dict[str, Any]:
    capability_rows = await get_backend().select("communication_capabilities", params={"capability_key": f"eq.{capability_key}", "limit": "1"}) or []
    if not capability_rows:
        return {"decision": "DENY", "reason": "unknown_capability", "capability_key": capability_key, "workspace_id": workspace_id}
    capability = capability_rows[0]
    overrides = await get_backend().select(
        "communication_workspace_capabilities",
        params={"workspace_id": f"eq.{workspace_id}", "capability_key": f"eq.{capability_key}", "limit": "1"},
    ) or []
    enabled = bool(overrides[0].get("enabled")) if overrides else bool(capability.get("default_enabled"))
    approval = bool(overrides[0].get("requires_human_approval")) if overrides else bool(capability.get("default_requires_human_approval"))
    risk = str(capability.get("risk_tier") or "REGULATED").upper()
    if risk in {"BINDING", "REGULATED"}:
        decision = "DENY"
        reason = "binding_or_regulated_action_not_exposed_to_agent"
    elif not enabled:
        decision = "DENY"
        reason = "capability_disabled"
    elif approval:
        decision = "REQUIRE_APPROVAL"
        reason = "human_approval_required"
    else:
        decision = "ALLOW"
        reason = "workspace_policy_allows"
    return {
        "workspace_id": workspace_id,
        "capability_key": capability_key,
        "risk_tier": risk,
        "decision": decision,
        "reason": reason,
        "enabled": enabled,
        "requires_human_approval": approval,
    }


async def _record_policy_event(workspace_id: str, capability_key: str, decision: str, reason: str, *, contact_id: str | None = None, context_id: str | None = None, mission_id: str | None = None, payload: dict[str, Any] | None = None) -> None:
    try:
        await get_backend().insert("communication_policy_events", {
            "event_id": f"cpe_{secrets.token_urlsafe(12)}",
            "workspace_id": workspace_id,
            "contact_id": contact_id,
            "context_id": context_id,
            "mission_id": mission_id,
            "capability_key": capability_key,
            "decision": decision,
            "reason": reason,
            "actor_type": "system",
            "actor_id": "communication_platform",
            "payload": payload or {},
            "created_at": _now(),
        })
    except Exception:
        pass


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=240)
    slug: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    brand_name: str = Field(default="SAHJONY", max_length=160)
    industry_pack_id: str = Field(default="pack_general", max_length=160)
    default_language: str = Field(default="auto", max_length=40)
    timezone: str | None = Field(default=None, max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextCreate(BaseModel):
    context_type: str = Field(min_length=1, max_length=100)
    external_id: str | None = Field(default=None, max_length=240)
    display_name: str | None = Field(default=None, max_length=240)
    status: Literal["OPEN", "ACTIVE", "HOLD", "CLOSED", "ARCHIVED"] = "OPEN"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContactCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=240)
    title: str | None = Field(default=None, max_length=160)
    country_code: str | None = Field(default=None, max_length=3)
    preferred_language: str = Field(default="auto", max_length=40)
    timezone: str | None = Field(default=None, max_length=80)
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


class ContactContextLink(BaseModel):
    contact_id: str = Field(min_length=1, max_length=180)
    context_id: str = Field(min_length=1, max_length=180)
    relationship_role: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MissionCreate(BaseModel):
    contact_id: str | None = Field(default=None, max_length=180)
    context_id: str | None = Field(default=None, max_length=180)
    conversation_id: str | None = Field(default=None, max_length=180)
    objective: str = Field(min_length=3, max_length=4000)
    success_criteria: str | None = Field(default=None, max_length=4000)
    priority: Priority = "normal"
    autonomy_mode: AutonomyMode = "ASSIST"
    allowed_channels: list[str] = Field(default_factory=list, max_length=10)
    max_outbound_attempts: int = Field(default=3, ge=0, le=20)


class MissionPlan(BaseModel):
    marketing: bool = False
    extra_context: str | None = Field(default=None, max_length=5000)


@app.get("/communication-platform/health")
async def platform_health() -> dict[str, Any]:
    persistence = persistent_backend_status()
    return {
        "status": "ok" if persistence.get("configured") else "configuration_required",
        "service": "sahjony-industry-agnostic-communications-platform",
        "version": "3.0.0",
        "architecture": "core_plus_industry_packs",
        "industry_agnostic": True,
        "workspace_isolation_model": True,
        "generic_context_graph": True,
        "contact_360": True,
        "consent_aware_routing": True,
        "mission_engine": True,
        "capability_policy_engine": True,
        "binding_tools_exposed": False,
        "regulated_tools_exposed": False,
        "default_workspace_id": DEFAULT_WORKSPACE_ID,
        "reasoning_model": _reasoning_model(),
        "openai_configured": bool(_openai_key()),
        "persistence": persistence.get("provider"),
        "fail_closed": True,
    }


@app.get("/communication-platform/industry-packs")
async def list_industry_packs(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    rows = await get_backend().select("communication_industry_packs", params={"active": "eq.true", "order": "name.asc", "limit": "100"}) or []
    return {"status": "ok", "industry_packs": rows}


@app.get("/communication-platform/workspaces")
async def list_workspaces(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    rows = await get_backend().select("communication_workspaces", params={"order": "updated_at.desc", "limit": "100"}) or []
    return {"status": "ok", "workspaces": rows}


@app.post("/communication-platform/workspaces")
async def create_workspace(payload: WorkspaceCreate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    await _industry_pack(payload.industry_pack_id)
    workspace_id = f"ws_{secrets.token_urlsafe(12)}"
    ts = _now()
    row = {"workspace_id": workspace_id, **payload.model_dump(), "status": "ACTIVE", "created_at": ts, "updated_at": ts}
    await get_backend().insert("communication_workspaces", row)
    return {"status": "created", "workspace": row}


@app.get("/communication-platform/workspaces/{workspace_id}")
async def workspace_detail(workspace_id: str, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    workspace = await _workspace(workspace_id)
    pack = await _industry_pack(str(workspace.get("industry_pack_id")))
    capabilities = await get_backend().select("communication_workspace_capabilities", params={"workspace_id": f"eq.{workspace_id}", "limit": "200"}) or []
    contexts = await get_backend().select("communication_contexts", params={"workspace_id": f"eq.{workspace_id}", "order": "updated_at.desc", "limit": "100"}) or []
    contacts = await get_backend().select("communication_contacts", params={"workspace_id": f"eq.{workspace_id}", "order": "updated_at.desc", "limit": "100"}) or []
    missions = await get_backend().select("communication_missions", params={"workspace_id": f"eq.{workspace_id}", "order": "updated_at.desc", "limit": "100"}) or []
    return {"status": "ok", "workspace": workspace, "industry_pack": pack, "capabilities": capabilities, "contexts": contexts, "contacts": contacts, "missions": missions}


@app.post("/communication-platform/workspaces/{workspace_id}/contexts")
async def create_context(workspace_id: str, payload: ContextCreate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    await _workspace(workspace_id)
    ts = _now()
    row = {
        "context_id": f"ctx_{secrets.token_urlsafe(12)}",
        "workspace_id": workspace_id,
        "context_type": _clean_context_type(payload.context_type),
        "external_id": payload.external_id,
        "display_name": payload.display_name,
        "status": payload.status,
        "metadata": payload.metadata,
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_contexts", row)
    return {"status": "created", "context": row}


@app.post("/communication-platform/workspaces/{workspace_id}/contacts")
async def create_contact(workspace_id: str, payload: ContactCreate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    await _workspace(workspace_id)
    ts = _now()
    row = {
        "contact_id": f"ctc_{secrets.token_urlsafe(12)}",
        "workspace_id": workspace_id,
        **payload.model_dump(),
        "status": "ACTIVE",
        "created_by": "owner",
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_contacts", row)
    return {"status": "created", "contact": row}


@app.post("/communication-platform/workspaces/{workspace_id}/contacts/{contact_id}/endpoints")
async def add_contact_endpoint(workspace_id: str, contact_id: str, payload: EndpointCreate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    await _contact(contact_id, workspace_id)
    ts = _now()
    if payload.preferred:
        await get_backend().patch("communication_contact_endpoints", {"preferred": False, "updated_at": ts}, params={"contact_id": f"eq.{contact_id}", "channel": f"eq.{payload.channel}"})
    row = {
        "endpoint_id": f"cep_{secrets.token_urlsafe(12)}",
        "contact_id": contact_id,
        **payload.model_dump(),
        "normalized_destination": _normalize_destination(payload.channel, payload.destination),
        "verified_at": ts if payload.verified else None,
        "consented_at": ts if payload.consent_status in {"CONSENTED", "TRANSACTIONAL_ONLY"} else None,
        "revoked_at": ts if payload.consent_status in {"REVOKED", "DO_NOT_CONTACT"} else None,
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_contact_endpoints", row)
    return {"status": "created", "endpoint": row}


@app.post("/communication-platform/workspaces/{workspace_id}/relationships")
async def link_contact_context(workspace_id: str, payload: ContactContextLink, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    await _contact(payload.contact_id, workspace_id)
    await _context(payload.context_id, workspace_id)
    ts = _now()
    row = {
        "link_id": f"ccl_{secrets.token_urlsafe(12)}",
        "workspace_id": workspace_id,
        **payload.model_dump(),
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_contact_contexts", row)
    return {"status": "created", "relationship": row}


@app.get("/communication-platform/workspaces/{workspace_id}/contacts/{contact_id}")
async def contact_360(workspace_id: str, contact_id: str, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    contact = await _contact(contact_id, workspace_id)
    endpoints = await get_backend().select("communication_contact_endpoints", params={"contact_id": f"eq.{contact_id}", "order": "preferred.desc,updated_at.desc", "limit": "100"}) or []
    links = await get_backend().select("communication_contact_contexts", params={"contact_id": f"eq.{contact_id}", "workspace_id": f"eq.{workspace_id}", "limit": "100"}) or []
    contexts = []
    for link in links:
        try:
            contexts.append({"relationship": link, "context": await _context(str(link.get("context_id")), workspace_id)})
        except HTTPException:
            continue
    missions = await get_backend().select("communication_missions", params={"workspace_id": f"eq.{workspace_id}", "contact_id": f"eq.{contact_id}", "order": "updated_at.desc", "limit": "100"}) or []
    notes = await get_backend().select("communication_agent_notes", params={"workspace_id": f"eq.{workspace_id}", "contact_id": f"eq.{contact_id}", "order": "created_at.desc", "limit": "100"}) or []
    return {"status": "ok", "contact": contact, "endpoints": endpoints, "relationships": contexts, "missions": missions, "notes": notes, "route": await _routes(contact_id, workspace_id)}


@app.get("/communication-platform/workspaces/{workspace_id}/contacts/{contact_id}/route")
async def route_contact(workspace_id: str, contact_id: str, marketing: bool = False, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    return await _routes(contact_id, workspace_id, marketing=marketing)


@app.get("/communication-platform/workspaces/{workspace_id}/capabilities/{capability_key}")
async def capability_policy(workspace_id: str, capability_key: str, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    await _workspace(workspace_id)
    return await _capability_policy(workspace_id, capability_key)


@app.post("/communication-platform/workspaces/{workspace_id}/missions")
async def create_mission(workspace_id: str, payload: MissionCreate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    await _workspace(workspace_id)
    if payload.contact_id:
        await _contact(payload.contact_id, workspace_id)
    if payload.context_id:
        await _context(payload.context_id, workspace_id)
    ts = _now()
    row = {
        "mission_id": f"cmis_{secrets.token_urlsafe(12)}",
        "workspace_id": workspace_id,
        "contact_id": payload.contact_id,
        "context_id": payload.context_id,
        "conversation_id": payload.conversation_id,
        "trade_case_id": None,
        "objective": payload.objective,
        "success_criteria": payload.success_criteria,
        "status": "READY",
        "priority": payload.priority,
        "autonomy_mode": payload.autonomy_mode,
        "allowed_channels": payload.allowed_channels,
        "max_outbound_attempts": payload.max_outbound_attempts,
        "binding_actions_allowed": False,
        "owner_approved": True,
        "approved_at": ts,
        "created_by": "owner",
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_missions", row)
    return {"status": "created", "mission": row, "binding_actions_allowed": False}


async def _sol_plan(workspace: dict[str, Any], pack: dict[str, Any], mission: dict[str, Any], contact: dict[str, Any] | None, context: dict[str, Any] | None, route: dict[str, Any], extra: str | None) -> dict[str, Any] | None:
    if not _openai_key():
        return None
    instructions = (
        "You are GPT-5.6 Sol planning the next non-binding communication action for an industry-agnostic enterprise communications platform. "
        "Use the workspace Industry Pack as the domain vocabulary and policy boundary. Return strict JSON with keys summary, recommended_channel, action_type, message_objective, human_review_reason. "
        "Never infer authority. Never execute or recommend bypassing binding, regulated, financial, legal, clinical, compliance, credential, security, or account-control decisions. "
        "Choose only from provided consent-compatible routes. If policy or evidence is insufficient, choose HUMAN_HANDOFF. "
        + str(pack.get("system_instructions") or "")[:5000]
    )
    prompt = {
        "workspace": {"name": workspace.get("name"), "industry_pack_id": workspace.get("industry_pack_id")},
        "mission": {k: mission.get(k) for k in ("objective", "success_criteria", "priority", "autonomy_mode", "context_id")},
        "contact": {k: contact.get(k) for k in ("display_name", "company", "title", "country_code", "preferred_language")} if contact else None,
        "context": {k: context.get(k) for k in ("context_type", "external_id", "display_name", "status", "metadata")} if context else None,
        "available_routes": route.get("routes", [])[:8],
        "extra_context": extra,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {_openai_key()}", "Content-Type": "application/json"},
                json={"model": _reasoning_model(), "instructions": instructions, "input": json.dumps(prompt), "max_output_tokens": 500},
            )
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
            value = json.loads(text[start:end + 1])
            return value if isinstance(value, dict) else None
    except Exception:
        return None
    return None


@app.post("/communication-platform/workspaces/{workspace_id}/missions/{mission_id}/plan")
async def plan_mission(workspace_id: str, mission_id: str, payload: MissionPlan, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    workspace = await _workspace(workspace_id)
    pack = await _industry_pack(str(workspace.get("industry_pack_id")))
    rows = await get_backend().select("communication_missions", params={"workspace_id": f"eq.{workspace_id}", "mission_id": f"eq.{mission_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(404, "Communication mission not found")
    mission = rows[0]
    contact = await _contact(str(mission.get("contact_id")), workspace_id) if mission.get("contact_id") else None
    context = await _context(str(mission.get("context_id")), workspace_id) if mission.get("context_id") else None
    route = await _routes(str(mission.get("contact_id")), workspace_id, marketing=payload.marketing) if mission.get("contact_id") else {"routes": [], "route_ready": False}
    plan = await _sol_plan(workspace, pack, mission, contact, context, route, payload.extra_context)
    if not plan:
        first = next(iter(route.get("routes") or []), None)
        plan = {
            "summary": "Use the highest-confidence consent-compatible route for a non-binding follow-up." if first else "No safe route is available; require human review.",
            "recommended_channel": first.get("channel") if first else None,
            "action_type": "FOLLOW_UP_TASK" if first else "HUMAN_HANDOFF",
            "message_objective": mission.get("objective"),
            "human_review_reason": None if first else "No usable endpoint/consent route",
            "planner": "deterministic_fallback",
        }
    else:
        plan["planner"] = _reasoning_model()

    requested_action = str(plan.get("action_type") or "FOLLOW_UP_TASK").upper()
    action_capability = {
        "FOLLOW_UP_TASK": "create_follow_up",
        "INTERNAL_NOTE": "record_internal_note",
        "HUMAN_HANDOFF": "request_human_handoff",
        "EMAIL_DRAFT": "send_external_message",
        "WHATSAPP_DRAFT": "send_external_message",
        "SMS_DRAFT": "send_external_message",
        "PORTAL_MESSAGE": "send_external_message",
        "PRIVATE_ROOM_INVITE": "send_external_message",
        "AI_ROOM_INVITE": "send_external_message",
        "CALL_INVITE": "place_outbound_call",
    }.get(requested_action, "create_follow_up")
    policy = await _capability_policy(workspace_id, action_capability)
    safe_action = requested_action if requested_action in {"FOLLOW_UP_TASK","HUMAN_HANDOFF","EMAIL_DRAFT","WHATSAPP_DRAFT","SMS_DRAFT","PORTAL_MESSAGE","PRIVATE_ROOM_INVITE","AI_ROOM_INVITE","CALL_INVITE","INTERNAL_NOTE"} else "FOLLOW_UP_TASK"
    if policy["decision"] == "DENY":
        safe_action = "HUMAN_HANDOFF"
        action_capability = "request_human_handoff"
        policy = await _capability_policy(workspace_id, action_capability)
    requires_approval = policy["decision"] == "REQUIRE_APPROVAL"
    ts = _now()
    action = {
        "action_id": f"cact_{secrets.token_urlsafe(12)}",
        "workspace_id": workspace_id,
        "mission_id": mission_id,
        "contact_id": mission.get("contact_id"),
        "context_id": mission.get("context_id"),
        "conversation_id": mission.get("conversation_id"),
        "trade_case_id": None,
        "action_type": safe_action,
        "channel": plan.get("recommended_channel"),
        "destination": None,
        "payload": {"plan": plan, "objective": mission.get("objective"), "capability": action_capability, "policy": policy},
        "status": "WAITING_APPROVAL" if requires_approval else "QUEUED",
        "requires_owner_approval": requires_approval,
        "owner_approved": False,
        "attempt_count": 0,
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_action_queue", action)
    await get_backend().patch("communication_missions", {"status": "RUNNING", "updated_at": ts}, params={"mission_id": f"eq.{mission_id}"})
    await _record_policy_event(workspace_id, action_capability, policy["decision"], policy["reason"], contact_id=mission.get("contact_id"), context_id=mission.get("context_id"), mission_id=mission_id, payload={"action_type": safe_action})
    return {"status": "planned", "workspace_id": workspace_id, "mission_id": mission_id, "plan": plan, "policy": policy, "action": action, "binding_actions_allowed": False}


async def _mcp_contact_context(args: dict[str, Any]) -> dict[str, Any]:
    workspace_id = str(args.get("workspace_id") or DEFAULT_WORKSPACE_ID)
    contact_id = str(args.get("contact_id") or "").strip()
    if not contact_id:
        return {"error": "contact_id_required"}
    try:
        contact = await _contact(contact_id, workspace_id)
        route = await _routes(contact_id, workspace_id)
    except HTTPException:
        return {"error": "contact_not_found"}
    links = await get_backend().select("communication_contact_contexts", params={"workspace_id": f"eq.{workspace_id}", "contact_id": f"eq.{contact_id}", "limit": "50"}) or []
    return {"workspace_id": workspace_id, "contact": contact, "relationships": links, "route": route}


async def _mcp_business_context(args: dict[str, Any]) -> dict[str, Any]:
    workspace_id = str(args.get("workspace_id") or DEFAULT_WORKSPACE_ID)
    context_id = str(args.get("context_id") or "").strip()
    if not context_id:
        return {"error": "context_id_required"}
    try:
        context = await _context(context_id, workspace_id)
    except HTTPException:
        return {"error": "context_not_found"}
    workspace = await _workspace(workspace_id)
    pack = await _industry_pack(str(workspace.get("industry_pack_id")))
    return {"workspace": workspace, "industry_pack": {"pack_id": pack.get("pack_id"), "name": pack.get("name"), "system_instructions": pack.get("system_instructions")}, "context": context, "binding_decisions": "authorized_human_or_governed_backend_only"}


async def _mcp_route(args: dict[str, Any]) -> dict[str, Any]:
    workspace_id = str(args.get("workspace_id") or DEFAULT_WORKSPACE_ID)
    contact_id = str(args.get("contact_id") or "").strip()
    if not contact_id:
        return {"error": "contact_id_required"}
    try:
        return await _routes(contact_id, workspace_id, marketing=bool(args.get("marketing")))
    except HTTPException:
        return {"error": "contact_not_found"}


async def _mcp_follow_up(args: dict[str, Any]) -> dict[str, Any]:
    workspace_id = str(args.get("workspace_id") or DEFAULT_WORKSPACE_ID)
    policy = await _capability_policy(workspace_id, "create_follow_up")
    if policy["decision"] != "ALLOW":
        return {"error": "policy_blocked", "policy": policy}
    objective = str(args.get("objective") or "").strip()[:3000]
    if not objective:
        return {"error": "objective_required"}
    ts = _now()
    row = {
        "action_id": f"cact_{secrets.token_urlsafe(12)}",
        "workspace_id": workspace_id,
        "mission_id": args.get("mission_id"),
        "contact_id": args.get("contact_id"),
        "context_id": args.get("context_id"),
        "conversation_id": args.get("conversation_id"),
        "trade_case_id": None,
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
    await _record_policy_event(workspace_id, "create_follow_up", "ALLOW", "workspace_policy_allows", contact_id=args.get("contact_id"), context_id=args.get("context_id"), mission_id=args.get("mission_id"))
    return {"status": "queued", "action_id": row["action_id"], "binding": False}


async def _mcp_note(args: dict[str, Any]) -> dict[str, Any]:
    workspace_id = str(args.get("workspace_id") or DEFAULT_WORKSPACE_ID)
    policy = await _capability_policy(workspace_id, "record_internal_note")
    if policy["decision"] != "ALLOW":
        return {"error": "policy_blocked", "policy": policy}
    content = str(args.get("content") or "").strip()[:8000]
    if not content:
        return {"error": "content_required"}
    note_type = str(args.get("note_type") or "SUMMARY").upper()
    if note_type not in {"SUMMARY", "FOLLOW_UP", "QUALIFICATION", "RISK", "HANDOFF", "CUSTOMER_REQUEST", "SUPPLIER_REQUEST"}:
        note_type = "SUMMARY"
    row = {
        "note_id": f"can_{secrets.token_urlsafe(12)}",
        "workspace_id": workspace_id,
        "contact_id": args.get("contact_id"),
        "context_id": args.get("context_id"),
        "conversation_id": args.get("conversation_id"),
        "room_id": args.get("room_id"),
        "trade_case_id": None,
        "note_type": note_type,
        "content": content,
        "source": "industry_agnostic_realtime_agent",
        "contains_recording": False,
        "created_at": _now(),
    }
    await get_backend().insert("communication_agent_notes", row)
    await _record_policy_event(workspace_id, "record_internal_note", "ALLOW", "workspace_policy_allows", contact_id=args.get("contact_id"), context_id=args.get("context_id"))
    return {"status": "recorded", "note_id": row["note_id"], "recording_created": False}


async def _mcp_handoff(args: dict[str, Any]) -> dict[str, Any]:
    workspace_id = str(args.get("workspace_id") or DEFAULT_WORKSPACE_ID)
    policy = await _capability_policy(workspace_id, "request_human_handoff")
    if policy["decision"] != "ALLOW":
        return {"error": "policy_blocked", "policy": policy}
    reason = str(args.get("reason") or "Human review requested").strip()[:1200]
    urgency = str(args.get("urgency") or "high").lower()
    if urgency not in {"urgent", "high", "normal", "low"}:
        urgency = "high"
    ts = _now()
    row = {
        "handoff_id": f"handoff_{secrets.token_urlsafe(12)}",
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
    await _record_policy_event(workspace_id, "request_human_handoff", "ALLOW", "workspace_policy_allows", contact_id=args.get("contact_id"), context_id=args.get("context_id"))
    return {"status": "requested", "handoff_id": row["handoff_id"]}


_MCP_TOOLS = [
    {"name": "get_contact_context", "description": "Read workspace-scoped contact context and consent-compatible routes.", "inputSchema": {"type": "object", "properties": {"workspace_id": {"type": "string"}, "contact_id": {"type": "string"}}, "required": ["contact_id"]}},
    {"name": "get_business_context", "description": "Read a generic workspace context such as a deal, matter, property, order, project, ticket, appointment or custom object.", "inputSchema": {"type": "object", "properties": {"workspace_id": {"type": "string"}, "context_id": {"type": "string"}}, "required": ["context_id"]}},
    {"name": "route_contact", "description": "Return consent-compatible communication routes without sending anything.", "inputSchema": {"type": "object", "properties": {"workspace_id": {"type": "string"}, "contact_id": {"type": "string"}, "marketing": {"type": "boolean"}}, "required": ["contact_id"]}},
    {"name": "create_follow_up", "description": "Create an internal non-binding follow-up task. Never sends or commits externally.", "inputSchema": {"type": "object", "properties": {"workspace_id": {"type": "string"}, "objective": {"type": "string"}, "contact_id": {"type": "string"}, "context_id": {"type": "string"}, "conversation_id": {"type": "string"}, "mission_id": {"type": "string"}}, "required": ["objective"]}},
    {"name": "record_note", "description": "Store a text-only internal note. Never stores call audio or video.", "inputSchema": {"type": "object", "properties": {"workspace_id": {"type": "string"}, "content": {"type": "string"}, "note_type": {"type": "string"}, "contact_id": {"type": "string"}, "context_id": {"type": "string"}, "conversation_id": {"type": "string"}, "room_id": {"type": "string"}}, "required": ["content"]}},
    {"name": "request_human_handoff", "description": "Request authorized human takeover for sensitive, binding, regulated, uncertain or escalated matters.", "inputSchema": {"type": "object", "properties": {"workspace_id": {"type": "string"}, "reason": {"type": "string"}, "urgency": {"type": "string"}, "contact_id": {"type": "string"}, "context_id": {"type": "string"}, "conversation_id": {"type": "string"}, "room_id": {"type": "string"}}, "required": ["reason"]}},
]


@app.api_route("/communication-platform/mcp", methods=["GET", "POST"])
async def platform_mcp(request: Request):
    authorization = request.headers.get("Authorization", "")
    expected = _mcp_token()
    supplied = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(401, "Invalid communications-platform MCP credential")
    if request.method == "GET":
        return {"status": "ok", "server": "sahjony-communications-platform", "version": "3.0.0", "tools": [tool["name"] for tool in _MCP_TOOLS], "binding_tools": False, "regulated_tools": False}
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid MCP JSON-RPC payload")
    method = str(payload.get("method") or "")
    request_id = payload.get("id")
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        result: Any = {"protocolVersion": str((payload.get("params") or {}).get("protocolVersion") or "2025-03-26"), "capabilities": {"tools": {}}, "serverInfo": {"name": "sahjony-communications-platform", "version": "3.0.0"}}
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
        elif name == "get_business_context":
            value = await _mcp_business_context(args)
        elif name == "route_contact":
            value = await _mcp_route(args)
        elif name == "create_follow_up":
            value = await _mcp_follow_up(args)
        elif name == "record_note":
            value = await _mcp_note(args)
        elif name == "request_human_handoff":
            value = await _mcp_handoff(args)
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
        result = {"content": [{"type": "text", "text": json.dumps(value, default=str)}], "structuredContent": value, "isError": bool(value.get("error")) if isinstance(value, dict) else False}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}
