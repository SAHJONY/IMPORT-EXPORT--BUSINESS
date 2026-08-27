from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend
from voice_agent_api import _openai_key, _reasoning_model, _realtime_model, _realtime_voice

app = FastAPI(title="SAHJONY Communication OS Security Guard", version="1.2.0", docs_url=None, redoc_url=None)

PRIVACY_NOTICE_VERSION = "2026-08-27-v1"
PrivacyMode = Literal["PRIVATE_HUMAN", "AI_ASSISTED"]
ParticipantType = Literal["customer", "lead", "owner", "employee"]


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _base_url() -> str:
    return (os.getenv("BUSINESS_CANONICAL_WEBSITE", "").strip() or os.getenv("APP_URL", "").strip() or "https://www.sahjony.com").rstrip("/")


def _owner_ok(authorization: str | None) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        return False
    return bool(verify_owner_token(authorization.removeprefix("Bearer ").strip()))


def _require_owner(authorization: str | None) -> None:
    if not _owner_ok(authorization):
        raise HTTPException(403, "Owner authorization required")


async def _room(room_id: str) -> dict[str, Any]:
    rows = await get_backend().select("communication_rooms", params={"room_id": f"eq.{room_id}", "limit": "1"})
    if not rows:
        raise HTTPException(404, "Room not found")
    return rows[0]


def _token_from_request(request: Request) -> str:
    token = request.query_params.get("token") or request.headers.get("X-Room-Token", "")
    if token:
        return token
    referer = request.headers.get("referer", "")
    if referer:
        try:
            values = parse_qs(urlparse(referer).query).get("token") or []
            if values:
                return values[0]
        except Exception:
            pass
    return ""


def _room_not_expired(room: dict[str, Any]) -> None:
    try:
        expires_at = datetime.fromisoformat(str(room.get("expires_at") or "").replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= _now_dt():
            raise HTTPException(410, "Room expired")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(410, "Room expiry is invalid")


async def _authorized_room(request: Request, room_id: str) -> dict[str, Any]:
    room = await _room(room_id)
    expected = str(room.get("join_token") or "")
    supplied = _token_from_request(request)
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(403, "Valid room token required")
    if room.get("status") != "OPEN":
        raise HTTPException(410, "Room is closed")
    _room_not_expired(room)
    return room


def _privacy_mode(room: dict[str, Any]) -> str:
    return str(room.get("privacy_mode") or "AI_ASSISTED").upper()


def _participant_authorized(participant_type: str, authorization: str | None) -> None:
    if participant_type == "owner" and not _owner_ok(authorization):
        raise HTTPException(403, "Owner participant identity requires owner authorization")


class SecureRoomCreate(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=180)
    mode: Literal["voice", "video", "video_screen"] = "video"
    privacy_mode: PrivacyMode = "PRIVATE_HUMAN"
    lead_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    context: str | None = Field(default=None, max_length=6000)
    language: str = Field(default="auto", max_length=35)
    expires_minutes: int = Field(default=1440, ge=15, le=10080)


@app.post("/communications-os/rooms")
async def secure_create_room(payload: SecureRoomCreate, authorization: str | None = Header(None, alias="Authorization")):
    _require_owner(authorization)
    ai_assisted = payload.privacy_mode == "AI_ASSISTED"
    if ai_assisted and not _openai_key():
        raise HTTPException(503, {"code": "AI_PROVIDER_NOT_CONFIGURED", "message": "AI-assisted rooms are unavailable until the AI provider is configured."})

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
        "ai_voice_engine": "openai_realtime" if ai_assisted else None,
        "ai_reasoning_model": _reasoning_model() if ai_assisted else None,
        "camera_frame_analysis": ai_assisted and payload.mode in {"video", "video_screen"},
        "screen_share_analysis": ai_assisted and payload.mode == "video_screen",
        "privacy_mode": payload.privacy_mode,
        "ai_enabled": ai_assisted,
        "ai_consent_required": ai_assisted,
        "human_webrtc_enabled": not ai_assisted,
        "privacy_notice_version": PRIVACY_NOTICE_VERSION,
        "recording_enabled": False,
        "expires_at": expires_at.isoformat(),
        "created_at": _now(),
        "updated_at": _now(),
    }
    await get_backend().insert("communication_rooms", row)
    guest_url = f"{_base_url()}/live-communications.html?room={room_id}&token={token}"
    owner_url = guest_url + "&role=owner"
    return {
        "status": "created",
        "room_id": room_id,
        "mode": payload.mode,
        "privacy_mode": payload.privacy_mode,
        "url": guest_url,
        "guest_url": guest_url,
        "owner_url": owner_url,
        "expires_at": row["expires_at"],
        "recording_enabled": False,
        "ai_processing": ai_assisted,
        "ai_consent_required": ai_assisted,
        "server_media_access": ai_assisted,
        "human_media_path": "peer_to_peer_webrtc" if not ai_assisted else None,
    }


@app.get("/communications-os/rooms/{room_id}/join")
async def secure_join_room(room_id: str, token: str):
    rows = await get_backend().select("communication_rooms", params={"room_id": f"eq.{room_id}", "limit": "1"})
    if not rows:
        raise HTTPException(404, "Room not found")
    room = rows[0]
    if not secrets.compare_digest(str(room.get("join_token") or ""), token):
        raise HTTPException(403, "Invalid room token")
    if room.get("status") != "OPEN":
        raise HTTPException(410, "Room is closed")
    _room_not_expired(room)
    privacy = _privacy_mode(room)
    ai_assisted = privacy == "AI_ASSISTED"
    return {
        "status": "ok",
        "room_id": room_id,
        "mode": room.get("mode"),
        "context": room.get("context"),
        "language": room.get("language"),
        "privacy_mode": privacy,
        "ai_enabled": ai_assisted,
        "ai_consent_required": ai_assisted,
        "privacy_notice_version": room.get("privacy_notice_version") or PRIVACY_NOTICE_VERSION,
        "recording_enabled": False,
        "realtime_model": _realtime_model() if ai_assisted else None,
        "realtime_voice": _realtime_voice() if ai_assisted else None,
        "reasoning_model": _reasoning_model() if ai_assisted else None,
        "media_path": "openai_realtime" if ai_assisted else "browser_peer_to_peer_webrtc",
        "media_encryption": "webrtc_dtls_srtp",
        "server_media_access": ai_assisted,
        "vision_available": ai_assisted and bool(room.get("camera_frame_analysis") or room.get("screen_share_analysis")),
        "privacy_notice": (
            "AI-assisted room: audio is processed by OpenAI Realtime only after explicit consent; visual frames are sent only after separate Vision consent. No intentional recording."
            if ai_assisted
            else "Private Human room: AI and Vision are disabled. Audio/video media is exchanged between browser peers using WebRTC; SAHJONY stores only short-lived signaling metadata and does not intentionally record media."
        ),
    }


class Presence(BaseModel):
    participant_type: Literal["customer", "lead", "owner", "employee", "ai"]
    participant_id: str = Field(min_length=1, max_length=180)
    state: Literal["joining", "online", "speaking", "viewing", "away", "left"] = "online"
    device: str | None = Field(default=None, max_length=120)


@app.post("/communications-os/rooms/{room_id}/presence")
async def secured_room_presence(
    room_id: str,
    payload: Presence,
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
):
    await _authorized_room(request, room_id)
    if payload.participant_type == "owner":
        _participant_authorized("owner", authorization)
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
    existing = await get_backend().select("communication_presence", params={"presence_id": f"eq.{row['presence_id']}", "limit": "1"}) or []
    if existing:
        await get_backend().patch("communication_presence", row, params={"presence_id": f"eq.{row['presence_id']}"})
    else:
        await get_backend().insert("communication_presence", row)
    return {"status": "ok", "room_id": room_id}


class ConsentIn(BaseModel):
    participant_id: str = Field(min_length=1, max_length=180)
    participant_type: ParticipantType
    ai_audio_consent: bool = False
    ai_vision_consent: bool = False


@app.post("/communications-os/rooms/{room_id}/consent")
async def room_consent(
    room_id: str,
    payload: ConsentIn,
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
):
    room = await _authorized_room(request, room_id)
    _participant_authorized(payload.participant_type, authorization)
    if _privacy_mode(room) != "AI_ASSISTED":
        raise HTTPException(409, "Private Human rooms do not permit AI processing")
    if payload.ai_vision_consent and not payload.ai_audio_consent:
        raise HTTPException(422, "Vision consent requires AI-assisted session consent")

    ts = _now()
    active = payload.ai_audio_consent or payload.ai_vision_consent
    existing = await get_backend().select(
        "communication_room_consents",
        params={"room_id": f"eq.{room_id}", "participant_id": f"eq.{payload.participant_id}", "limit": "1"},
    ) or []
    values = {
        "participant_type": payload.participant_type,
        "ai_audio_consent": payload.ai_audio_consent,
        "ai_vision_consent": payload.ai_vision_consent,
        "notice_version": str(room.get("privacy_notice_version") or PRIVACY_NOTICE_VERSION),
        "consented_at": ts if active else None,
        "revoked_at": None if active else ts,
        "updated_at": ts,
    }
    if existing:
        await get_backend().patch(
            "communication_room_consents",
            values,
            params={"room_id": f"eq.{room_id}", "participant_id": f"eq.{payload.participant_id}"},
        )
        consent_id = existing[0].get("consent_id")
    else:
        consent_id = f"crc_{secrets.token_urlsafe(12)}"
        await get_backend().insert(
            "communication_room_consents",
            {"consent_id": consent_id, "room_id": room_id, "participant_id": payload.participant_id, "created_at": ts, **values},
        )
    return {
        "status": "consented" if active else "revoked",
        "consent_id": consent_id,
        "room_id": room_id,
        "participant_id": payload.participant_id,
        "ai_audio_consent": payload.ai_audio_consent,
        "ai_vision_consent": payload.ai_vision_consent,
        "recording_enabled": False,
    }


@app.get("/communications-os/rooms/{room_id}/consent/{participant_id}")
async def room_consent_status(room_id: str, participant_id: str, request: Request):
    room = await _authorized_room(request, room_id)
    if _privacy_mode(room) != "AI_ASSISTED":
        return {"room_id": room_id, "participant_id": participant_id, "ai_audio_consent": False, "ai_vision_consent": False, "ai_enabled": False}
    rows = await get_backend().select(
        "communication_room_consents",
        params={"room_id": f"eq.{room_id}", "participant_id": f"eq.{participant_id}", "limit": "1"},
    ) or []
    if not rows:
        return {"room_id": room_id, "participant_id": participant_id, "ai_audio_consent": False, "ai_vision_consent": False, "ai_enabled": True}
    row = rows[0]
    active = not bool(row.get("revoked_at"))
    return {
        "room_id": room_id,
        "participant_id": participant_id,
        "ai_audio_consent": active and bool(row.get("ai_audio_consent")),
        "ai_vision_consent": active and bool(row.get("ai_vision_consent")),
        "ai_enabled": True,
    }


class SignalIn(BaseModel):
    participant_id: str = Field(min_length=1, max_length=180)
    participant_type: ParticipantType
    signal_type: Literal["offer", "answer", "ice", "hangup"]
    payload: dict[str, Any] = Field(default_factory=dict)


@app.post("/communications-os/rooms/{room_id}/signals")
async def post_room_signal(
    room_id: str,
    payload: SignalIn,
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
):
    room = await _authorized_room(request, room_id)
    _participant_authorized(payload.participant_type, authorization)
    if _privacy_mode(room) != "PRIVATE_HUMAN":
        raise HTTPException(409, "Human peer signaling is available only in Private Human rooms")
    if len(json.dumps(payload.payload, separators=(",", ":"))) > 120_000:
        raise HTTPException(413, "WebRTC signaling payload is too large")
    ts = _now_dt()
    row = {
        "signal_id": f"sig_{secrets.token_urlsafe(14)}",
        "room_id": room_id,
        "sender_participant_id": payload.participant_id,
        "sender_type": payload.participant_type,
        "signal_type": payload.signal_type,
        "payload": payload.payload,
        "created_at": ts.isoformat(),
        "expires_at": (ts + timedelta(minutes=15)).isoformat(),
    }
    await get_backend().insert("communication_room_signals", row)
    return {"status": "accepted", "signal_id": row["signal_id"], "media_stored": False}


@app.get("/communications-os/rooms/{room_id}/signals")
async def get_room_signals(room_id: str, participant_id: str, request: Request):
    room = await _authorized_room(request, room_id)
    if _privacy_mode(room) != "PRIVATE_HUMAN":
        raise HTTPException(409, "Human peer signaling is available only in Private Human rooms")
    rows = await get_backend().select(
        "communication_room_signals",
        params={"room_id": f"eq.{room_id}", "order": "created_at.asc", "limit": "200"},
    ) or []
    now_dt = _now_dt()
    visible = []
    for row in rows:
        if str(row.get("sender_participant_id") or "") == participant_id:
            continue
        try:
            expiry = datetime.fromisoformat(str(row.get("expires_at") or "").replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= now_dt:
                continue
        except Exception:
            continue
        visible.append({
            "signal_id": row.get("signal_id"),
            "sender_participant_id": row.get("sender_participant_id"),
            "sender_type": row.get("sender_type"),
            "signal_type": row.get("signal_type"),
            "payload": row.get("payload") or {},
            "created_at": row.get("created_at"),
        })
    return {"status": "ok", "signals": visible[-100:], "media_stored": False}


class HandoffRequest(BaseModel):
    conversation_id: str | None = Field(default=None, max_length=180)
    room_id: str | None = Field(default=None, max_length=180)
    reason: str = Field(min_length=3, max_length=1200)
    urgency: Literal["urgent", "high", "normal", "low"] = "high"
    requested_by: Literal["ai", "customer", "lead", "employee", "owner"] = "ai"


@app.post("/communications-os/handoffs")
async def secured_handoff(
    payload: HandoffRequest,
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
):
    owner_ok = _owner_ok(authorization)
    if not owner_ok:
        if not payload.room_id:
            raise HTTPException(403, "Owner authorization or a valid room token is required")
        await _authorized_room(request, payload.room_id)
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
        await get_backend().patch(
            "communication_conversations",
            {"human_takeover": True, "updated_at": _now()},
            params={"conversation_id": f"eq.{payload.conversation_id}"},
        )
    return {"status": "requested", "handoff_id": handoff_id, "secured": True}
