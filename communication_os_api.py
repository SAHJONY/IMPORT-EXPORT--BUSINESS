from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status
from voice_agent_api import _openai_key, _reasoning_model, _realtime_model, _realtime_voice

app = FastAPI(title="SAHJONY Agentic Communication OS", version="1.0.0", docs_url=None, redoc_url=None)

Channel = Literal["web_voice", "web_video", "screen_share", "whatsapp", "email", "pstn", "portal"]
Priority = Literal["urgent", "high", "normal", "low"]


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


def _base_url() -> str:
    return _env("BUSINESS_CANONICAL_WEBSITE", "APP_URL") or "https://www.sahjony.com"


def _direct_voice_ready() -> bool:
    enabled = _env("DIRECT_WEBRTC_VOICE_ENABLED").lower() not in {"0", "false", "off", "disabled"}
    return bool(_openai_key() and enabled)


def _whatsapp_send_ready() -> bool:
    return bool(_env("WHATSAPP_ACCESS_TOKEN") and _env("WHATSAPP_PHONE_NUMBER_ID") and _env("WHATSAPP_GRAPH_API_VERSION"))


def _email_ready() -> bool:
    return bool(_env("GMAIL_SMTP_APP_PASSWORD") or _env("GMAIL_REFRESH_TOKEN") or _env("RESEND_API_KEY"))


def _tmobile_runtime_ready() -> bool:
    required = (
        "TMOBILE_BYON_CLIENT_ID",
        "TMOBILE_BYON_CLIENT_SECRET",
        "TMOBILE_BYON_ACCESS_TOKEN",
        "TMOBILE_BYON_REGISTERED_MSISDN",
        "TMOBILE_BYON_CHANNEL_ID",
        "TMOBILE_BYON_RACM_SESSION_ID",
        "TMOBILE_BYON_SESSION_CLIENT_ID",
    )
    return all(_env(name) for name in required)


def _channel_state() -> dict[str, dict[str, Any]]:
    direct = _direct_voice_ready()
    return {
        "web_voice": {"ready": direct, "transport": "browser_webrtc", "ai": "openai_realtime"},
        "web_video": {"ready": direct, "transport": "browser_webrtc_camera_plus_realtime_image_frames", "ai": "openai_realtime"},
        "screen_share": {"ready": direct, "transport": "browser_webrtc_screen_plus_realtime_image_frames", "ai": "openai_realtime"},
        "whatsapp": {"ready": _whatsapp_send_ready(), "transport": "meta_cloud", "voice_invite": direct},
        "email": {"ready": _email_ready(), "transport": "native_business_email"},
        "pstn": {"ready": _tmobile_runtime_ready(), "transport": "tmobile_devedge_byon"},
        "portal": {"ready": persistent_backend_status().get("configured", False), "transport": "native_portal"},
    }


@app.get("/communications-os/health")
async def health() -> dict[str, Any]:
    channels = _channel_state()
    persistence = persistent_backend_status()
    ready_count = sum(1 for value in channels.values() if value["ready"])
    return {
        "status": "ok" if persistence.get("configured") and _openai_key() else "configuration_required",
        "service": "sahjony-agentic-communication-os",
        "version": "1.0.0",
        "operating_mode": "24x7_event_driven",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "realtime_voice": _realtime_voice(),
        "conversation_graph": True,
        "agentic_routing": True,
        "multilingual": True,
        "vision_frames": True,
        "screen_share_frames": True,
        "human_takeover_bus": True,
        "crm_linkage": True,
        "recording_enabled": False,
        "channels_ready": ready_count,
        "channels_total": len(channels),
        "channels": channels,
        "binding_decisions_fail_closed": True,
        "bland_voice_ai_enabled": False,
        "fail_closed": True,
    }


class ConversationCreate(BaseModel):
    contact_name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=240)
    phone_number: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=320)
    lead_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    subject: str | None = Field(default=None, max_length=240)
    context: str | None = Field(default=None, max_length=6000)
    language: str = Field(default="auto", max_length=35)
    priority: Priority = "normal"
    preferred_channel: Channel = "web_voice"


@app.post("/communications-os/conversations")
async def create_conversation(payload: ConversationCreate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    conversation_id = f"conv_{secrets.token_urlsafe(14)}"
    ts = _now()
    row = {
        "conversation_id": conversation_id,
        "status": "OPEN",
        "contact_name": payload.contact_name,
        "company": payload.company,
        "phone_number": payload.phone_number,
        "email": payload.email,
        "lead_id": payload.lead_id,
        "customer_id": payload.customer_id,
        "trade_case_id": payload.trade_case_id,
        "subject": payload.subject,
        "context": payload.context,
        "language": payload.language,
        "priority": payload.priority,
        "preferred_channel": payload.preferred_channel,
        "last_channel": None,
        "human_takeover": False,
        "ai_owner": "gpt-5.6-sol",
        "voice_engine": "openai_realtime",
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_conversations", row)
    return {"status": "created", "conversation": row}


@app.get("/communications-os/conversations")
async def list_conversations(
    authorization: str | None = Header(None, alias="Authorization"),
    status: str | None = None,
    trade_case_id: str | None = None,
    limit: int = 100,
):
    _owner(authorization)
    params: dict[str, str] = {"order": "updated_at.desc", "limit": str(max(1, min(limit, 500)))}
    if status:
        params["status"] = f"eq.{status}"
    if trade_case_id:
        params["trade_case_id"] = f"eq.{trade_case_id}"
    rows = await get_backend().select("communication_conversations", params=params)
    return {"status": "ok", "count": len(rows or []), "conversations": rows or []}


class EventIngest(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=180)
    channel: Channel
    direction: Literal["inbound", "outbound", "internal"]
    event_type: str = Field(min_length=1, max_length=120)
    text: str | None = Field(default=None, max_length=12000)
    provider_id: str | None = Field(default=None, max_length=300)
    contact_name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=240)
    phone_number: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=320)
    lead_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.post("/communications-os/events")
async def ingest_event(payload: EventIngest, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    conversation_id = payload.conversation_id
    if not conversation_id:
        created = await create_conversation(ConversationCreate(
            contact_name=payload.contact_name,
            company=payload.company,
            phone_number=payload.phone_number,
            email=payload.email,
            lead_id=payload.lead_id,
            customer_id=payload.customer_id,
            trade_case_id=payload.trade_case_id,
            subject=payload.event_type,
            context=payload.text,
            preferred_channel=payload.channel,
        ), authorization)
        conversation_id = created["conversation"]["conversation_id"]
    event_id = f"cevt_{secrets.token_urlsafe(14)}"
    ts = _now()
    row = {
        "event_id": event_id,
        "conversation_id": conversation_id,
        "channel": payload.channel,
        "direction": payload.direction,
        "event_type": payload.event_type,
        "text": payload.text,
        "provider_id": payload.provider_id,
        "lead_id": payload.lead_id,
        "customer_id": payload.customer_id,
        "trade_case_id": payload.trade_case_id,
        "metadata": payload.metadata,
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("communication_events", row)
    await get_backend().patch(
        "communication_conversations",
        {"last_channel": payload.channel, "updated_at": ts},
        params={"conversation_id": f"eq.{conversation_id}"},
    )
    return {"status": "recorded", "event": row}


class RoomCreate(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=180)
    mode: Literal["voice", "video", "video_screen"] = "video"
    lead_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    context: str | None = Field(default=None, max_length=6000)
    language: str = Field(default="auto", max_length=35)
    expires_minutes: int = Field(default=1440, ge=15, le=10080)


@app.post("/communications-os/rooms")
async def create_room(payload: RoomCreate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _direct_voice_ready():
        raise HTTPException(503, "OpenAI Realtime is required before creating live rooms")
    room_id = f"room_{secrets.token_urlsafe(14)}"
    token = secrets.token_urlsafe(28)
    expires_at = _now_dt() + timedelta(minutes=payload.expires_minutes)
    row = {
        "room_id": room_id,
        "join_token": token,
        "status": "OPEN",
        "mode": payload.mode,
        "conversation_id": payload.conversation_id,
        "lead_id": payload.lead_id,
        "customer_id": payload.customer_id,
        "trade_case_id": payload.trade_case_id,
        "context": payload.context,
        "language": payload.language,
        "ai_voice_engine": "openai_realtime",
        "ai_reasoning_model": _reasoning_model(),
        "camera_frame_analysis": payload.mode in {"video", "video_screen"},
        "screen_share_analysis": payload.mode == "video_screen",
        "recording_enabled": False,
        "expires_at": expires_at.isoformat(),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await get_backend().insert("communication_rooms", row)
    url = f"{_base_url().rstrip('/')}/live-communications.html?room={room_id}&token={token}"
    return {"status": "created", "room_id": room_id, "mode": payload.mode, "url": url, "expires_at": row["expires_at"], "recording_enabled": False}


@app.get("/communications-os/rooms/{room_id}/join")
async def join_room(room_id: str, token: str):
    rows = await get_backend().select("communication_rooms", params={"room_id": f"eq.{room_id}", "limit": "1"})
    if not rows:
        raise HTTPException(404, "Room not found")
    room = rows[0]
    if not secrets.compare_digest(str(room.get("join_token") or ""), token):
        raise HTTPException(403, "Invalid room token")
    try:
        if datetime.fromisoformat(str(room.get("expires_at"))) < _now_dt():
            raise HTTPException(410, "Room expired")
    except ValueError:
        raise HTTPException(410, "Room expiry is invalid")
    if room.get("status") != "OPEN":
        raise HTTPException(410, "Room is closed")
    return {
        "status": "ok",
        "room_id": room_id,
        "mode": room.get("mode"),
        "context": room.get("context"),
        "language": room.get("language"),
        "realtime_model": _realtime_model(),
        "realtime_voice": _realtime_voice(),
        "reasoning_model": _reasoning_model(),
        "recording_enabled": False,
    }


class Presence(BaseModel):
    participant_type: Literal["customer", "lead", "owner", "employee", "ai"]
    participant_id: str = Field(min_length=1, max_length=180)
    state: Literal["joining", "online", "speaking", "viewing", "away", "left"] = "online"
    device: str | None = Field(default=None, max_length=120)


@app.post("/communications-os/rooms/{room_id}/presence")
async def room_presence(room_id: str, payload: Presence):
    row = {
        "presence_id": f"presence:{room_id}:{payload.participant_type}:{payload.participant_id}",
        "room_id": room_id,
        "participant_type": payload.participant_type,
        "participant_id": payload.participant_id,
        "state": payload.state,
        "device": payload.device,
        "heartbeat_at": _now(),
        "updated_at": _now(),
    }
    await get_backend().insert("communication_presence", row)
    return {"status": "ok"}


class HandoffRequest(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=180)
    room_id: str | None = Field(default=None, max_length=180)
    reason: str = Field(min_length=3, max_length=1200)
    urgency: Priority = "high"
    requested_by: Literal["ai", "customer", "lead", "employee", "owner"] = "ai"


@app.post("/communications-os/handoffs")
async def request_handoff(payload: HandoffRequest):
    handoff_id = f"handoff_{secrets.token_urlsafe(12)}"
    row = {
        "handoff_id": handoff_id,
        "status": "REQUESTED",
        "conversation_id": payload.conversation_id,
        "room_id": payload.room_id,
        "reason": payload.reason,
        "urgency": payload.urgency,
        "requested_by": payload.requested_by,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await get_backend().insert("communication_handoffs", row)
    if payload.conversation_id:
        await get_backend().patch("communication_conversations", {"human_takeover": True, "updated_at": _now()}, params={"conversation_id": f"eq.{payload.conversation_id}"})
    return {"status": "requested", "handoff_id": handoff_id}


@app.get("/communications-os/handoffs")
async def list_handoffs(authorization: str | None = Header(None, alias="Authorization"), status: str | None = "REQUESTED", limit: int = 100):
    _owner(authorization)
    params: dict[str, str] = {"order": "created_at.desc", "limit": str(max(1, min(limit, 500)))}
    if status:
        params["status"] = f"eq.{status}"
    rows = await get_backend().select("communication_handoffs", params=params)
    return {"status": "ok", "count": len(rows or []), "handoffs": rows or []}


@app.post("/communications-os/handoffs/{handoff_id}/accept")
async def accept_handoff(handoff_id: str, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    updated = await get_backend().patch("communication_handoffs", {"status": "ACCEPTED", "accepted_at": _now(), "updated_at": _now()}, params={"handoff_id": f"eq.{handoff_id}"})
    if not updated:
        raise HTTPException(404, "Handoff not found")
    return {"status": "accepted", "handoff_id": handoff_id}


@app.get("/communications-os/command-center")
async def command_center(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    conversations = await get_backend().select("communication_conversations", params={"order": "updated_at.desc", "limit": "80"})
    handoffs = await get_backend().select("communication_handoffs", params={"status": "eq.REQUESTED", "order": "created_at.desc", "limit": "80"})
    rooms = await get_backend().select("communication_rooms", params={"status": "eq.OPEN", "order": "created_at.desc", "limit": "80"})
    voice_queue = await get_backend().select("voice_outbound_queue", params={"order": "created_at.desc", "limit": "80"})
    return {
        "status": "ok",
        "health": await health(),
        "open_conversations": conversations or [],
        "requested_handoffs": handoffs or [],
        "open_rooms": rooms or [],
        "voice_queue": voice_queue or [],
        "public_voice_url": f"{_base_url().rstrip('/')}/call-sahjony.html",
        "live_room_base": f"{_base_url().rstrip('/')}/live-communications.html",
    }
