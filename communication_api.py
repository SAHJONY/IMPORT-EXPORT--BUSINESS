from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_customer_token, verify_owner_token
from insforge_backend import InsForgeConfigurationError, get_backend

app = FastAPI(
    title="SAHJONY Global Trade Communications Hub",
    description="Unified role-scoped communications, business events and participant notifications.",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)

Role = Literal["owner", "employee", "customer"]
Priority = Literal["normal", "high", "urgent"]
EventType = Literal["message", "document", "shipment", "payment", "compliance", "approval", "task", "system"]
Visibility = Literal["owner", "internal", "customer"]


class MessageCreate(BaseModel):
    thread_id: str | None = Field(default=None, max_length=120)
    recipient_role: Role
    recipient_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    subject: str = Field(min_length=2, max_length=240)
    body: str = Field(min_length=1, max_length=10000)
    priority: Priority = "normal"
    escalation_requested: bool = False


class MessageStatus(BaseModel):
    status: Literal["read", "resolved"]


class EventCreate(BaseModel):
    event_type: EventType
    source_type: str = Field(min_length=1, max_length=80)
    source_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    visibility: Visibility = "internal"
    title: str = Field(min_length=2, max_length=240)
    summary: str | None = Field(default=None, max_length=4000)
    action_required: bool = False
    action_label: str | None = Field(default=None, max_length=120)
    priority: Priority = "normal"
    payload: dict[str, Any] = Field(default_factory=dict)


class EventStatus(BaseModel):
    status: Literal["acknowledged", "resolved"]


class PreferenceUpdate(BaseModel):
    portal_enabled: bool = True
    email_enabled: bool = False
    sms_enabled: bool = False
    whatsapp_enabled: bool = False
    urgent_only_external: bool = False
    email_address: str | None = Field(default=None, max_length=320)
    phone_e164: str | None = Field(default=None, max_length=32)
    locale: str = Field(default="en", max_length=12)
    timezone: str = Field(default="America/Chicago", max_length=80)


def _employee_token() -> str:
    token = os.getenv("EMPLOYEE_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="Employee communications are not configured")
    return token


def _identity(role: str | None, authorization: str | None, employee_id: str | None) -> dict[str, str]:
    if role not in {"owner", "employee", "customer"}:
        raise HTTPException(status_code=400, detail="X-Role must be owner, employee or customer")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()

    if role == "owner":
        if not verify_owner_token(token):
            raise HTTPException(status_code=403, detail="Invalid owner credential")
        return {"role": "owner", "id": "owner"}
    if role == "employee":
        if not secrets.compare_digest(token, _employee_token()):
            raise HTTPException(status_code=403, detail="Invalid employee credential")
        safe_id = (employee_id or "staff").strip()[:160]
        return {"role": "employee", "id": safe_id or "staff"}

    customer = verify_customer_token(token)
    if not customer:
        raise HTTPException(status_code=403, detail="Invalid customer credential")
    return {"role": "customer", "id": str(customer["participant_id"])}


def _validate_route(sender: dict[str, str], payload: MessageCreate) -> None:
    if sender["role"] == "customer":
        if payload.recipient_role not in {"employee", "owner"}:
            raise HTTPException(status_code=403, detail="Customers may contact operations or request owner escalation")
        if payload.customer_id and payload.customer_id != sender["id"]:
            raise HTTPException(status_code=403, detail="Customer scope mismatch")
    if sender["role"] == "employee" and payload.recipient_role == "customer" and not payload.customer_id:
        raise HTTPException(status_code=400, detail="Customer recipient messages require customer_id")
    if payload.recipient_role == "customer" and not (payload.customer_id or payload.recipient_id):
        raise HTTPException(status_code=400, detail="Customer recipient must be explicitly scoped")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _visible_to(actor: dict[str, str], event: dict[str, Any]) -> bool:
    if actor["role"] == "owner":
        return True
    if actor["role"] == "customer":
        return event.get("visibility") == "customer" and event.get("customer_id") == actor["id"]
    return event.get("visibility") in {"internal", "customer"}


async def _record_event(*, event_type: str, source_type: str, source_id: str | None, trade_case_id: str | None,
                        customer_id: str | None, actor: dict[str, str], visibility: str, title: str,
                        summary: str | None, priority: str = "normal", action_required: bool = False,
                        action_label: str | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ts = _now()
    event = {
        "event_id": f"evt_{secrets.token_urlsafe(16)}",
        "event_type": event_type,
        "source_type": source_type,
        "source_id": source_id,
        "trade_case_id": trade_case_id,
        "customer_id": customer_id,
        "actor_role": actor["role"],
        "actor_id": actor["id"],
        "visibility": visibility,
        "title": title,
        "summary": summary,
        "action_required": action_required,
        "action_label": action_label,
        "priority": priority,
        "event_status": "open",
        "payload": payload or {},
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("business_events", event)
    return event


async def _queue_portal_notification(event: dict[str, Any], recipient_role: str, recipient_id: str) -> None:
    row = {
        "notification_id": f"ntf_{secrets.token_urlsafe(16)}",
        "event_id": event["event_id"],
        "recipient_role": recipient_role,
        "recipient_id": recipient_id,
        "channel": "portal",
        "destination": None,
        "subject": event["title"],
        "body": event.get("summary") or event["title"],
        "delivery_status": "delivered",
        "provider": "native_portal",
        "provider_message_id": None,
        "attempts": 1,
        "last_error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await get_backend().insert("outbound_notifications", row)


@app.get("/communications/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "business-communications-hub",
        "version": "2.0.0",
        "persistence": "insforge",
        "configured": bool(os.getenv("INSFORGE_BASE_URL") and os.getenv("INSFORGE_API_KEY")),
        "employee_auth_configured": bool(os.getenv("EMPLOYEE_TOKEN")),
        "native_portal_delivery": True,
        "external_delivery": "fail-closed-until-provider-configured",
        "roles": ["owner", "employee", "customer"],
        "tenant_policy": "customer-isolated",
    }


@app.post("/communications/messages")
async def create_message(payload: MessageCreate, x_role: str | None = Header(None, alias="X-Role"),
                         authorization: str | None = Header(None, alias="Authorization"),
                         x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    sender = _identity(x_role, authorization, x_employee_id)
    _validate_route(sender, payload)
    customer_id = sender["id"] if sender["role"] == "customer" else payload.customer_id
    thread_id = payload.thread_id or f"thr_{secrets.token_urlsafe(16)}"
    message_id = f"msg_{secrets.token_urlsafe(18)}"
    ts = _now()
    row = {
        "message_id": message_id, "thread_id": thread_id, "sender_role": sender["role"], "sender_id": sender["id"],
        "recipient_role": payload.recipient_role, "recipient_id": payload.recipient_id, "customer_id": customer_id,
        "trade_case_id": payload.trade_case_id, "subject": payload.subject, "body": payload.body,
        "priority": payload.priority, "status": "sent", "escalation_requested": payload.escalation_requested,
        "created_at": ts, "updated_at": ts,
    }
    try:
        result = await get_backend().insert("communications", row)
        visibility = "customer" if customer_id and (sender["role"] == "customer" or payload.recipient_role == "customer") else "internal"
        event = await _record_event(event_type="message", source_type="communication", source_id=message_id,
                                    trade_case_id=payload.trade_case_id, customer_id=customer_id, actor=sender,
                                    visibility=visibility, title=payload.subject, summary=payload.body,
                                    priority=payload.priority, action_required=payload.escalation_requested,
                                    action_label="Owner review" if payload.escalation_requested else None,
                                    payload={"thread_id": thread_id, "recipient_role": payload.recipient_role})
        recipient_id = payload.recipient_id or (customer_id if payload.recipient_role == "customer" else payload.recipient_role)
        await _queue_portal_notification(event, payload.recipient_role, recipient_id)
    except InsForgeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Communication persistence unavailable: {type(exc).__name__}") from exc
    return {"message": row, "event": event, "persistence": result}


@app.get("/communications/messages")
async def list_messages(thread_id: str | None = Query(default=None, max_length=120),
                        customer_id: str | None = Query(default=None, max_length=160),
                        trade_case_id: str | None = Query(default=None, max_length=160),
                        limit: int = Query(default=100, ge=1, le=250),
                        x_role: str | None = Header(None, alias="X-Role"),
                        authorization: str | None = Header(None, alias="Authorization"),
                        x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = _identity(x_role, authorization, x_employee_id)
    params: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
    if thread_id: params["thread_id"] = f"eq.{thread_id}"
    if trade_case_id: params["trade_case_id"] = f"eq.{trade_case_id}"
    if actor["role"] == "customer": params["customer_id"] = f"eq.{actor['id']}"
    elif customer_id: params["customer_id"] = f"eq.{customer_id}"
    try:
        rows = await get_backend().select("communications", params=params)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Communication persistence unavailable: {type(exc).__name__}") from exc
    rows = rows or []
    if actor["role"] == "employee":
        rows = [r for r in rows if r.get("sender_role") == "employee" or r.get("recipient_role") == "employee" or r.get("escalation_requested") is True]
    return {"messages": rows, "actor": actor}


@app.patch("/communications/messages/{message_id}")
async def update_message_status(message_id: str, payload: MessageStatus,
                                x_role: str | None = Header(None, alias="X-Role"),
                                authorization: str | None = Header(None, alias="Authorization"),
                                x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = _identity(x_role, authorization, x_employee_id)
    if actor["role"] == "customer" and payload.status == "resolved":
        raise HTTPException(status_code=403, detail="Customers cannot resolve operational threads")
    result = await get_backend().patch("communications", {"status": payload.status, "updated_at": _now()}, params={"message_id": f"eq.{message_id}"})
    return {"message_id": message_id, "status": payload.status, "actor": actor, "persistence": result}


@app.post("/communications/events")
async def create_business_event(payload: EventCreate, x_role: str | None = Header(None, alias="X-Role"),
                                authorization: str | None = Header(None, alias="Authorization"),
                                x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = _identity(x_role, authorization, x_employee_id)
    if actor["role"] == "customer":
        raise HTTPException(status_code=403, detail="Customers cannot create system business events")
    if payload.visibility == "customer" and not payload.customer_id:
        raise HTTPException(status_code=400, detail="Customer-visible events require customer_id")
    if payload.visibility == "owner" and actor["role"] != "owner":
        raise HTTPException(status_code=403, detail="Only owner can create owner-only events")
    event = await _record_event(event_type=payload.event_type, source_type=payload.source_type, source_id=payload.source_id,
                                trade_case_id=payload.trade_case_id, customer_id=payload.customer_id, actor=actor,
                                visibility=payload.visibility, title=payload.title, summary=payload.summary,
                                priority=payload.priority, action_required=payload.action_required,
                                action_label=payload.action_label, payload=payload.payload)
    if payload.visibility == "customer" and payload.customer_id:
        await _queue_portal_notification(event, "customer", payload.customer_id)
    return {"event": event}


@app.get("/communications/timeline")
async def timeline(trade_case_id: str | None = Query(default=None, max_length=160),
                   customer_id: str | None = Query(default=None, max_length=160),
                   action_required: bool | None = Query(default=None),
                   limit: int = Query(default=150, ge=1, le=300),
                   x_role: str | None = Header(None, alias="X-Role"),
                   authorization: str | None = Header(None, alias="Authorization"),
                   x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = _identity(x_role, authorization, x_employee_id)
    params: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
    if trade_case_id: params["trade_case_id"] = f"eq.{trade_case_id}"
    if actor["role"] == "customer": params["customer_id"] = f"eq.{actor['id']}"
    elif customer_id: params["customer_id"] = f"eq.{customer_id}"
    if action_required is not None: params["action_required"] = "eq.true" if action_required else "eq.false"
    rows = await get_backend().select("business_events", params=params)
    visible = [r for r in (rows or []) if _visible_to(actor, r)]
    return {"events": visible, "actor": actor}


@app.patch("/communications/events/{event_id}")
async def update_event(event_id: str, payload: EventStatus, x_role: str | None = Header(None, alias="X-Role"),
                       authorization: str | None = Header(None, alias="Authorization"),
                       x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = _identity(x_role, authorization, x_employee_id)
    if actor["role"] == "customer" and payload.status == "resolved":
        raise HTTPException(status_code=403, detail="Customers cannot resolve business control events")
    result = await get_backend().patch("business_events", {"event_status": payload.status, "updated_at": _now()}, params={"event_id": f"eq.{event_id}"})
    return {"event_id": event_id, "status": payload.status, "actor": actor, "persistence": result}


@app.put("/communications/preferences")
async def update_preferences(payload: PreferenceUpdate, x_role: str | None = Header(None, alias="X-Role"),
                             authorization: str | None = Header(None, alias="Authorization"),
                             x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = _identity(x_role, authorization, x_employee_id)
    if (payload.sms_enabled or payload.whatsapp_enabled) and not payload.phone_e164:
        raise HTTPException(status_code=400, detail="SMS/WhatsApp preference requires phone_e164")
    if payload.email_enabled and not payload.email_address:
        raise HTTPException(status_code=400, detail="Email preference requires email_address")
    values = {**payload.model_dump(), "updated_at": _now()}
    existing = await get_backend().select("communication_preferences", params={"participant_role": f"eq.{actor['role']}", "participant_id": f"eq.{actor['id']}", "limit": "1"})
    if existing:
        result = await get_backend().patch("communication_preferences", values, params={"participant_role": f"eq.{actor['role']}", "participant_id": f"eq.{actor['id']}"})
    else:
        result = await get_backend().insert("communication_preferences", {"participant_role": actor["role"], "participant_id": actor["id"], **values, "created_at": _now()})
    return {"actor": actor, "preferences": values, "persistence": result, "external_channels_note": "Preferences are stored; external delivery stays disabled until an approved provider is configured."}


@app.get("/communications/notifications")
async def notifications(limit: int = Query(default=100, ge=1, le=250), x_role: str | None = Header(None, alias="X-Role"),
                        authorization: str | None = Header(None, alias="Authorization"),
                        x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = _identity(x_role, authorization, x_employee_id)
    params = {"recipient_role": f"eq.{actor['role']}", "recipient_id": f"eq.{actor['id']}", "order": "created_at.desc", "limit": str(limit)}
    rows = await get_backend().select("outbound_notifications", params=params)
    return {"notifications": rows or [], "actor": actor}
