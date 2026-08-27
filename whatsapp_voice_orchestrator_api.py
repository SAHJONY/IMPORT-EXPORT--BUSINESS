from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend
from voice_agent_api import _reasoning_model, _realtime_model, _realtime_voice

app = FastAPI(title="SAHJONY WhatsApp Voice Orchestrator", version="1.0.0", docs_url=None, redoc_url=None)

US_BIC_BLOCKED_COUNTRY_CODES = {"1"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _owner(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if not verify_owner_token(token):
        raise HTTPException(403, "Invalid owner credential")
    return authorization


def _base_url() -> str:
    return _env("BUSINESS_CANONICAL_WEBSITE", "APP_URL") or "https://www.sahjony.com"


def _whatsapp_business_country_code() -> str:
    return _env("WHATSAPP_BUSINESS_COUNTRY_CODE").lstrip("+")


def _whatsapp_business_initiated_voice_allowed() -> bool | None:
    cc = _whatsapp_business_country_code()
    if not cc:
        return None
    return cc not in US_BIC_BLOCKED_COUNTRY_CODES


@app.get("/voice/whatsapp/health")
async def whatsapp_voice_health() -> dict[str, Any]:
    allowed = _whatsapp_business_initiated_voice_allowed()
    return {
        "status": "ok",
        "service": "sahjony-whatsapp-voice-orchestrator",
        "version": "1.0.0",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "realtime_voice": _realtime_voice(),
        "whatsapp_messaging_route": "/whatsapp/send",
        "whatsapp_inbound_webhook": "/whatsapp/webhook",
        "direct_voice_url": f"{_base_url().rstrip('/')}/call-sahjony.html",
        "whatsapp_user_initiated_call_target": "openai_realtime",
        "whatsapp_business_initiated_call_allowed": allowed,
        "whatsapp_business_country_code_configured": bool(_whatsapp_business_country_code()),
        "us_business_number_outbound_whatsapp_call_policy": "blocked_by_meta_current_availability",
        "pstn_outbound_fallback": "tmobile_devedge_byon",
        "bland_voice_ai_enabled": False,
        "recording_enabled": False,
        "crm_unification": True,
        "fail_closed": True,
    }


class WhatsAppVoiceInvite(BaseModel):
    to: str = Field(min_length=8, max_length=32)
    contact_name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=240)
    lead_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    context: str | None = Field(default=None, max_length=4000)
    language: str = Field(default="auto", max_length=35)


@app.post("/voice/whatsapp/invite")
async def send_whatsapp_voice_invite(payload: WhatsAppVoiceInvite, authorization: str | None = Header(None, alias="Authorization")):
    bearer = _owner(authorization)
    invite_id = f"vinv_{secrets.token_urlsafe(12)}"
    call_url = f"{_base_url().rstrip('/')}/call-sahjony.html?invite={invite_id}"
    name = (payload.contact_name or "").strip()
    greeting = f"Hello {name}," if name else "Hello,"
    body = (
        f"{greeting} SAHJONY Global Trade is ready for a secure live voice conversation. "
        f"Tap this link to connect directly with our OpenAI Realtime business voice agent: {call_url} "
        "No app installation is required."
    )
    row = {
        "invite_id": invite_id,
        "status": "ACTIVE",
        "channel": "whatsapp",
        "transport": "direct_webrtc",
        "destination": payload.to,
        "contact_name": payload.contact_name,
        "company": payload.company,
        "lead_id": payload.lead_id,
        "customer_id": payload.customer_id,
        "trade_case_id": payload.trade_case_id,
        "context": payload.context,
        "language": payload.language,
        "call_url": call_url,
        "voice_engine": "openai_realtime",
        "reasoning_model": _reasoning_model(),
        "recording_enabled": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await get_backend().insert("voice_invites", row)
    send_payload = {
        "to": payload.to,
        "body": body,
        "preview_url": True,
        "lead_id": payload.lead_id,
        "customer_id": payload.customer_id,
        "source_url": call_url,
    }
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            f"{_base_url().rstrip('/')}/whatsapp/send",
            headers={"Authorization": bearer, "Content-Type": "application/json"},
            json=send_payload,
        )
    if response.status_code >= 400:
        await get_backend().patch(
            "voice_invites",
            {"status": "WHATSAPP_SEND_FAILED", "updated_at": _now()},
            params={"invite_id": f"eq.{invite_id}"},
        )
        detail = response.text[:800]
        raise HTTPException(502, f"WhatsApp voice invitation could not be sent ({response.status_code}): {detail}")
    try:
        provider = response.json()
    except Exception:
        provider = {}
    return {
        "status": "sent",
        "invite_id": invite_id,
        "call_url": call_url,
        "whatsapp_message_id": provider.get("message_id"),
        "voice_engine": "openai_realtime",
        "reasoning_model": _reasoning_model(),
        "carrier_per_minute_charge": False,
        "openai_usage_cost_applies": True,
        "recording_enabled": False,
    }


class WhatsAppCallEvent(BaseModel):
    call_id: str = Field(min_length=1, max_length=240)
    from_number: str | None = Field(default=None, max_length=32)
    status: str = Field(default="received", max_length=80)
    event_type: str = Field(default="whatsapp_call", max_length=120)
    lead_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    raw: dict[str, Any] = Field(default_factory=dict)


@app.post("/voice/whatsapp/call-event")
async def register_whatsapp_call_event(payload: WhatsAppCallEvent, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    row = {
        "event_id": f"wacall_{secrets.token_urlsafe(12)}",
        "call_id": payload.call_id,
        "direction": "inbound_whatsapp",
        "provider": "meta_whatsapp_calling",
        "from_number": payload.from_number,
        "status": payload.status,
        "event_type": payload.event_type,
        "lead_id": payload.lead_id,
        "customer_id": payload.customer_id,
        "trade_case_id": payload.trade_case_id,
        "voice_engine": "openai_realtime",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "raw": payload.raw,
        "recording_enabled": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await get_backend().insert("voice_network_events", row)
    return {"status": "recorded", "call_id": payload.call_id, "next_route": "openai_realtime_when_meta_calling_is_enabled"}
