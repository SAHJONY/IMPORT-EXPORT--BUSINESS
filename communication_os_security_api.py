from __future__ import annotations

import secrets
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Communication OS Security Guard", version="1.0.0", docs_url=None, redoc_url=None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _room(room_id: str) -> dict:
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


async def _authorized_room(request: Request, room_id: str) -> dict:
    room = await _room(room_id)
    expected = str(room.get("join_token") or "")
    supplied = _token_from_request(request)
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(403, "Valid room token required")
    if room.get("status") != "OPEN":
        raise HTTPException(410, "Room is closed")
    return room


class Presence(BaseModel):
    participant_type: Literal["customer", "lead", "owner", "employee", "ai"]
    participant_id: str = Field(min_length=1, max_length=180)
    state: Literal["joining", "online", "speaking", "viewing", "away", "left"] = "online"
    device: str | None = Field(default=None, max_length=120)


@app.post("/communications-os/rooms/{room_id}/presence")
async def secured_room_presence(room_id: str, payload: Presence, request: Request):
    await _authorized_room(request, room_id)
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
    return {"status": "ok", "room_id": room_id}


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
    owner_ok = False
    if authorization and authorization.startswith("Bearer "):
        owner_ok = bool(verify_owner_token(authorization.removeprefix("Bearer ").strip()))
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
