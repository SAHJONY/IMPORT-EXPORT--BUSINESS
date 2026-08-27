from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status
from voice_agent_api import _openai_key, _reasoning_model, _realtime_model, _realtime_voice

app = FastAPI(title="SAHJONY Autonomous Voice Operations", version="1.0.0", docs_url=None, redoc_url=None)

ALLOWED_OUTREACH_BASES = {
    "requested_callback",
    "active_rfq",
    "existing_business_relationship",
    "customer_service",
    "supplier_followup",
    "partner_followup",
    "logistics_coordination",
    "transaction_followup",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _direct_ready() -> bool:
    enabled = _env("DIRECT_WEBRTC_VOICE_ENABLED").lower() not in {"0", "false", "off", "disabled"}
    return bool(_openai_key() and enabled)


def _byon_credentials_configured() -> bool:
    return bool(_env("TMOBILE_BYON_CLIENT_ID") and _env("TMOBILE_BYON_CLIENT_SECRET"))


def _byon_runtime_ready() -> bool:
    # These values are intentionally explicit. A client id/secret alone does not mean
    # that a subscriber line has authorized the app or that a RACM session is active.
    required = (
        "TMOBILE_BYON_ACCESS_TOKEN",
        "TMOBILE_BYON_REGISTERED_MSISDN",
        "TMOBILE_BYON_CHANNEL_ID",
        "TMOBILE_BYON_RACM_SESSION_ID",
        "TMOBILE_BYON_SESSION_CLIENT_ID",
    )
    return _byon_credentials_configured() and all(_env(name) for name in required)


def _pstn_state() -> tuple[str, str | None]:
    if _byon_runtime_ready():
        return "READY", None
    if _byon_credentials_configured():
        return "WAITING_LINE_AUTHORIZATION", "TMOBILE_BYON_LINE_AUTH_OR_RACM_REQUIRED"
    return "WAITING_PROVIDER_APPROVAL", "TMOBILE_BYON_CREDENTIALS_REQUIRED"


@app.get("/voice/autonomous/health")
async def autonomous_health() -> dict[str, Any]:
    pstn_state, blocker = _pstn_state()
    persistence = persistent_backend_status()
    return {
        "status": "ok" if _direct_ready() and persistence.get("configured") else "configuration_required",
        "service": "sahjony-autonomous-voice-operations",
        "version": "1.0.0",
        "operating_mode": "24x7_event_driven",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "realtime_voice": _realtime_voice(),
        "direct_webrtc_ready": _direct_ready(),
        "direct_voice_public_url": "https://www.sahjony.com/call-sahjony.html",
        "pstn_provider": "tmobile_devedge_byon",
        "pstn_state": pstn_state,
        "pstn_blocker": blocker,
        "tmobile_bylon_credentials_configured": _byon_credentials_configured(),
        "tmobile_byon_runtime_ready": _byon_runtime_ready(),
        "legacy_bland_voice_ai_enabled": False,
        "persistence_configured": persistence.get("configured", False),
        "inbound_policy": "auto_answer_when_transport_ready",
        "outbound_policy": "queue_only_with_valid_business_basis_and_dnc_clear",
        "recording_enabled": False,
        "binding_decisions_fail_closed": True,
        "fail_closed": True,
    }


class VoiceInviteRequest(BaseModel):
    contact_name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=240)
    lead_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    context: str | None = Field(default=None, max_length=4000)
    language: str = Field(default="auto", max_length=35)
    expires_minutes: int = Field(default=1440, ge=15, le=10080)


@app.post("/voice/autonomous/invites")
async def create_voice_invite(payload: VoiceInviteRequest, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _direct_ready():
        raise HTTPException(503, "Direct OpenAI Realtime voice is not ready")
    invite_id = f"vinv_{secrets.token_urlsafe(12)}"
    row = {
        "invite_id": invite_id,
        "status": "ACTIVE",
        "transport": "direct_webrtc",
        "contact_name": payload.contact_name,
        "company": payload.company,
        "lead_id": payload.lead_id,
        "trade_case_id": payload.trade_case_id,
        "context": payload.context,
        "language": payload.language,
        "expires_minutes": payload.expires_minutes,
        "created_at": _now(),
        "updated_at": _now(),
        "recording_enabled": False,
    }
    await get_backend().insert("voice_invites", row)
    return {
        "status": "created",
        "invite_id": invite_id,
        "url": f"https://www.sahjony.com/call-sahjony.html?invite={invite_id}",
        "transport": "direct_webrtc",
        "carrier_per_minute_charge": False,
        "openai_usage_cost_applies": True,
        "recording_enabled": False,
    }


class OutboundQueueRequest(BaseModel):
    phone_number: str = Field(min_length=7, max_length=32)
    contact_name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=240)
    lead_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    context: str | None = Field(default=None, max_length=4000)
    language: str = Field(default="auto", max_length=35)
    outreach_basis: str = Field(min_length=3, max_length=80)
    do_not_call: bool = False
    priority: Literal["urgent", "high", "normal", "low"] = "normal"


@app.post("/voice/autonomous/outbound/queue")
async def queue_outbound(payload: OutboundQueueRequest, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    basis = payload.outreach_basis.strip().lower()
    if payload.do_not_call:
        raise HTTPException(409, {"code": "DO_NOT_CALL", "message": "Outbound calling is prohibited for this contact."})
    if basis not in ALLOWED_OUTREACH_BASES:
        raise HTTPException(422, {"code": "OUTREACH_BASIS_REQUIRED", "allowed": sorted(ALLOWED_OUTREACH_BASES)})
    pstn_state, blocker = _pstn_state()
    job_id = f"vjob_{secrets.token_urlsafe(12)}"
    job_status = "QUEUED" if pstn_state == "READY" else "WAITING_PSTN_AUTH"
    row = {
        "job_id": job_id,
        "status": job_status,
        "phone_number": payload.phone_number,
        "contact_name": payload.contact_name,
        "company": payload.company,
        "lead_id": payload.lead_id,
        "trade_case_id": payload.trade_case_id,
        "context": payload.context,
        "language": payload.language,
        "outreach_basis": basis,
        "do_not_call": False,
        "priority": payload.priority,
        "transport": "tmobile_devedge_byon",
        "voice_engine": "openai_realtime",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "pstn_blocker": blocker,
        "attempts": 0,
        "created_at": _now(),
        "updated_at": _now(),
        "recording_enabled": False,
    }
    await get_backend().insert("voice_outbound_queue", row)
    return {
        "status": job_status,
        "job_id": job_id,
        "pstn_state": pstn_state,
        "blocker": blocker,
        "direct_voice_alternative": "https://www.sahjony.com/call-sahjony.html",
        "fail_closed": True,
    }


@app.get("/voice/autonomous/outbound/queue")
async def list_outbound_queue(
    authorization: str | None = Header(None, alias="Authorization"),
    status: str | None = None,
    limit: int = 100,
):
    _owner(authorization)
    params: dict[str, str] = {"limit": str(max(1, min(limit, 500))), "order": "created_at.desc"}
    if status:
        params["status"] = f"eq.{status}"
    rows = await get_backend().select("voice_outbound_queue", params=params)
    return {"status": "ok", "count": len(rows), "jobs": rows}


@app.post("/voice/autonomous/outbound/reconcile")
async def reconcile_outbound_queue(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    pstn_state, blocker = _pstn_state()
    waiting = await get_backend().select("voice_outbound_queue", params={"status": "eq.WAITING_PSTN_AUTH", "limit": "500"})
    changed = 0
    if pstn_state == "READY":
        for row in waiting:
            job_id = row.get("job_id")
            if not job_id:
                continue
            updated = await get_backend().patch(
                "voice_outbound_queue",
                {"status": "QUEUED", "pstn_blocker": None, "updated_at": _now()},
                params={"job_id": f"eq.{job_id}"},
            )
            changed += len(updated or [])
    return {
        "status": "ok",
        "pstn_state": pstn_state,
        "pstn_blocker": blocker,
        "jobs_released": changed,
        "queued_jobs_are_not_dialed_until_tmobile_runtime_is_verified": True,
        "fail_closed": True,
    }


@app.post("/voice/autonomous/events/inbound")
async def register_inbound_event(
    event: dict[str, Any],
    x_voice_event_secret: str | None = Header(None, alias="X-Voice-Event-Secret"),
):
    expected = _env("VOICE_EVENT_WEBHOOK_SECRET")
    if not expected or not x_voice_event_secret or not secrets.compare_digest(expected, x_voice_event_secret):
        raise HTTPException(401, "Invalid voice event credential")
    event_id = str(event.get("event_id") or event.get("id") or f"vevt_{secrets.token_urlsafe(10)}")[:180]
    row = {
        "event_id": event_id,
        "direction": "inbound",
        "provider": str(event.get("provider") or "tmobile_devedge_byon")[:80],
        "event_type": str(event.get("type") or event.get("event_type") or "unknown")[:120],
        "session_id": str(event.get("vvoipSessionId") or event.get("session_id") or "")[:240] or None,
        "status": str(event.get("status") or "RECEIVED")[:80],
        "payload": event,
        "received_at": _now(),
        "recording_enabled": False,
    }
    await get_backend().insert("voice_network_events", row)
    return {"status": "received", "event_id": event_id}
