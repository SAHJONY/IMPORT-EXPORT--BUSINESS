from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from auth import verify_owner_token
from insforge_backend import get_backend
from voice_agent_api import (
    _openai_key,
    _reasoning_model,
    _realtime_model,
    _realtime_session,
    _realtime_voice,
    _store,
)

app = FastAPI(title="SAHJONY Direct Voice", version="1.2.0", docs_url=None, redoc_url=None)

_DIRECT_WINDOW_SECONDS = 600
_DIRECT_MAX_SESSIONS_PER_WINDOW = 6
_DIRECT_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
_AGENTIC_ALLOWED_TOOLS = [
    "get_contact_context",
    "get_trade_context",
    "route_contact",
    "create_follow_up",
    "record_note",
    "request_human_handoff",
]


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _base_url() -> str:
    return _env("BUSINESS_CANONICAL_WEBSITE", "APP_URL") or "https://www.sahjony.com"


def _direct_enabled() -> bool:
    return _env("DIRECT_WEBRTC_VOICE_ENABLED").lower() not in {"0", "false", "off", "disabled"}


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


def _fingerprint(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    ip = forwarded or (request.client.host if request.client else "unknown")
    ua = request.headers.get("user-agent", "")[:300]
    return hashlib.sha256(f"{ip}|{ua}".encode()).hexdigest()


def _origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin", "").strip()
    if not origin:
        return False
    expected = urlparse(_base_url()).netloc.lower()
    actual = urlparse(origin).netloc.lower()
    if actual == expected:
        return True
    if os.getenv("PRODUCTION_MODE", "").lower() not in {"1", "true", "yes"} and actual in {"localhost:3000", "localhost:8000", "127.0.0.1:8000"}:
        return True
    return False


def _rate_limit(request: Request) -> str:
    fingerprint = _fingerprint(request)
    now = time.time()
    queue = _DIRECT_ATTEMPTS[fingerprint]
    while queue and now - queue[0] > _DIRECT_WINDOW_SECONDS:
        queue.popleft()
    if len(queue) >= _DIRECT_MAX_SESSIONS_PER_WINDOW:
        raise HTTPException(429, {"code": "DIRECT_VOICE_RATE_LIMITED", "message": "Direct voice session limit reached. Please try again later."})
    queue.append(now)
    return fingerprint


def _agent_mcp_token() -> str:
    key = _openai_key()
    if not key:
        return ""
    return hashlib.sha256(("sahjony-agentic-communications:" + key).encode()).hexdigest()


def _agentic_mcp_tool() -> dict[str, Any] | None:
    token = _agent_mcp_token()
    if not token:
        return None
    return {
        "type": "mcp",
        "server_label": "sahjony_agentic_communications",
        "server_description": "Consent-aware SAHJONY Contact 360, trade context, routing, internal follow-up, note and human-handoff tools. No binding commercial tools are exposed.",
        "server_url": f"{_base_url().rstrip('/')}/communications-os/mcp/agent",
        "headers": {"Authorization": f"Bearer {token}"},
        "allowed_tools": _AGENTIC_ALLOWED_TOOLS,
        "require_approval": "never",
    }


async def _room_ai_context(request: Request) -> dict[str, Any] | None:
    room_id = request.headers.get("x-sahjony-room-id", "").strip()
    participant_id = request.headers.get("x-sahjony-participant-id", "").strip()
    if not room_id and not participant_id:
        return None
    if not room_id or not participant_id:
        raise HTTPException(403, {"code": "ROOM_CONTEXT_INCOMPLETE", "message": "AI room context is incomplete."})

    token = request.headers.get("x-room-token", "").strip()
    if not token:
        raise HTTPException(403, {"code": "ROOM_TOKEN_REQUIRED", "message": "A valid AI room token is required."})
    rows = await get_backend().select("communication_rooms", params={"room_id": f"eq.{room_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(404, {"code": "ROOM_NOT_FOUND", "message": "Communication room not found."})
    room = rows[0]
    expected = str(room.get("join_token") or "")
    if not expected or not secrets.compare_digest(expected, token):
        raise HTTPException(403, {"code": "ROOM_TOKEN_INVALID", "message": "Communication room token is invalid."})
    if str(room.get("status") or "") != "OPEN":
        raise HTTPException(410, {"code": "ROOM_CLOSED", "message": "Communication room is closed."})
    if str(room.get("privacy_mode") or "AI_ASSISTED").upper() != "AI_ASSISTED" or room.get("ai_enabled") is False:
        raise HTTPException(409, {"code": "PRIVATE_HUMAN_AI_BLOCKED", "message": "Private Human rooms do not permit AI processing."})

    consents = await get_backend().select(
        "communication_room_consents",
        params={"room_id": f"eq.{room_id}", "participant_id": f"eq.{participant_id}", "limit": "1"},
    ) or []
    if not consents:
        raise HTTPException(409, {"code": "AI_CONSENT_REQUIRED", "message": "Explicit AI audio consent is required before starting this room."})
    consent = consents[0]
    if bool(consent.get("revoked_at")) or not bool(consent.get("ai_audio_consent")):
        raise HTTPException(409, {"code": "AI_CONSENT_REQUIRED", "message": "Explicit AI audio consent is required before starting this room."})
    return {
        "room_id": room_id,
        "participant_id": participant_id,
        "conversation_id": room.get("conversation_id"),
        "lead_id": room.get("lead_id"),
        "customer_id": room.get("customer_id"),
        "trade_case_id": room.get("trade_case_id"),
        "context": room.get("context"),
        "language": room.get("language"),
        "vision_consented": bool(consent.get("ai_vision_consent")) and not bool(consent.get("revoked_at")),
    }


def _provider_error(response: httpx.Response) -> HTTPException:
    raw = response.text[:2000]
    lowered = raw.lower()
    if response.status_code == 429 and any(x in lowered for x in ("credit_balance_exhausted", "insufficient_quota", "no credits remaining")):
        return HTTPException(503, {
            "code": "AI_CAPACITY_EXHAUSTED",
            "message": "AI-assisted calling is temporarily unavailable because API capacity is exhausted. Private Human rooms remain available without OpenAI credits.",
            "retryable": True,
        })
    if response.status_code == 429:
        return HTTPException(503, {"code": "AI_PROVIDER_RATE_LIMITED", "message": "AI-assisted calling is temporarily rate limited. Please retry shortly.", "retryable": True})
    if response.status_code in {401, 403}:
        return HTTPException(503, {"code": "AI_PROVIDER_AUTHORIZATION_REQUIRED", "message": "AI-assisted calling requires provider authorization to be restored.", "retryable": False})
    if response.status_code >= 500:
        return HTTPException(503, {"code": "AI_PROVIDER_UNAVAILABLE", "message": "AI-assisted calling is temporarily unavailable. Private Human rooms remain available.", "retryable": True})
    return HTTPException(502, {"code": "AI_SESSION_REJECTED", "message": "The AI-assisted session could not be started.", "retryable": False})


@app.get("/voice/direct/health")
async def direct_health() -> dict[str, Any]:
    openai = bool(_openai_key())
    enabled = _direct_enabled()
    return {
        "status": "ok" if openai and enabled else "configuration_required",
        "service": "sahjony-direct-webrtc-voice",
        "version": "1.2.0",
        "enabled": enabled,
        "openai_configured": openai,
        "voice_engine": "openai_realtime",
        "realtime_model": _realtime_model(),
        "realtime_voice": _realtime_voice(),
        "reasoning_model": _reasoning_model(),
        "sol_brain_enabled": openai,
        "agentic_communication_tools": bool(_agent_mcp_token()),
        "agentic_binding_tools_exposed": False,
        "room_ai_consent_enforced": True,
        "transport": "browser_webrtc",
        "pstn": False,
        "carrier_required": False,
        "carrier_per_minute_charge": False,
        "openai_usage_cost_applies": True,
        "recording_enabled": False,
        "public_url": f"{_base_url().rstrip('/')}/call-sahjony.html",
        "fail_closed": True,
    }


@app.post("/voice/direct/session")
async def direct_session(request: Request):
    if not _direct_enabled():
        raise HTTPException(503, {"code": "DIRECT_WEBRTC_DISABLED", "message": "Direct WebRTC voice is disabled."})
    if not _openai_key():
        raise HTTPException(503, {"code": "AI_PROVIDER_NOT_CONFIGURED", "message": "AI-assisted calling is not configured. Private Human rooms remain available."})
    if not _origin_allowed(request):
        raise HTTPException(403, "Direct voice sessions must originate from the canonical SAHJONY website")
    fingerprint = _rate_limit(request)
    room_context = await _room_ai_context(request)
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/sdp":
        raise HTTPException(415, "Content-Type must be application/sdp")
    raw = await request.body()
    if not raw or len(raw) > 200_000:
        raise HTTPException(422, "Invalid SDP offer")
    try:
        sdp_offer = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(422, "SDP offer must be UTF-8")

    verified_context = (
        "This is a consented AI-assisted SAHJONY communication room. "
        f"Room ID: {room_context.get('room_id')}. Conversation ID: {room_context.get('conversation_id') or 'unlinked'}. "
        f"Lead ID: {room_context.get('lead_id') or 'unlinked'}. Customer ID: {room_context.get('customer_id') or 'unlinked'}. "
        f"Trade case ID: {room_context.get('trade_case_id') or 'unlinked'}. Preferred language: {room_context.get('language') or 'auto'}. "
        f"Vision consent: {'yes' if room_context.get('vision_consented') else 'no'}. Verified room context: {str(room_context.get('context') or '')[:3000]}"
        if room_context
        else "This is a direct internet voice call initiated from the official SAHJONY website. Treat the caller as unverified until they identify themselves. Do not expose internal system details, credentials, private customer data, or confidential deal information."
    )
    session = _realtime_session(verified_context)
    agentic_tool = _agentic_mcp_tool()
    if agentic_tool:
        session.setdefault("tools", []).append(agentic_tool)
    multipart = {
        "sdp": (None, sdp_offer),
        "session": (None, __import__("json").dumps(session)),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={
                "Authorization": f"Bearer {_openai_key()}",
                "OpenAI-Safety-Identifier": fingerprint,
            },
            files=multipart,
        )
    if response.status_code >= 400:
        raise _provider_error(response)

    call_id = f"web_{secrets.token_urlsafe(12)}"
    await _store({
        "call_id": call_id,
        "direction": "inbound_web",
        "status": "connected",
        "provider": "openai_realtime_direct",
        "voice_engine": "openai_realtime",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "transport": "browser_webrtc",
        "recording_enabled": False,
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    })
    return Response(content=response.text, media_type="application/sdp", headers={"X-Sahjony-Call-Id": call_id})


def _tmobile_client_id() -> str:
    return _env("TMOBILE_BYON_CLIENT_ID")


def _tmobile_client_secret() -> str:
    return _env("TMOBILE_BYON_CLIENT_SECRET")


def _tmobile_redirect_uri() -> str:
    return _env("TMOBILE_BYON_REDIRECT_URI") or f"{_base_url().rstrip('/')}/voice/byon/callback"


def _tmobile_base() -> str:
    return (_env("TMOBILE_BYON_API_BASE") or "https://naas.t-mobile.com/cpaas").rstrip("/")


def _tmobile_state() -> str:
    secret = _tmobile_client_secret()
    stamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    payload = f"{stamp}.{nonce}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _validate_tmobile_state(value: str) -> bool:
    secret = _tmobile_client_secret()
    if not secret:
        return False
    parts = value.split(".")
    if len(parts) != 3:
        return False
    stamp, nonce, supplied = parts
    try:
        if abs(time.time() - int(stamp)) > 900:
            return False
    except ValueError:
        return False
    payload = f"{stamp}.{nonce}"
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return secrets.compare_digest(supplied, expected)


@app.get("/voice/byon/health")
async def byon_health(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    client_id = bool(_tmobile_client_id())
    client_secret = bool(_tmobile_client_secret())
    redirect = bool(_tmobile_redirect_uri())
    configured = client_id and client_secret and redirect
    return {
        "status": "ready_for_line_authorization" if configured else "configuration_required",
        "service": "tmobile-byon-adapter",
        "configured": configured,
        "client_id_configured": client_id,
        "client_secret_configured": client_secret,
        "redirect_uri_configured": redirect,
        "redirect_uri": _tmobile_redirect_uri() if configured else None,
        "provider": "tmobile_devedge_byon",
        "transport": "tmobile_webrtc_gateway",
        "requires_devedge_account": True,
        "requires_active_byon_subscription": True,
        "requires_tmobile_line_authorization": True,
        "metro_line_eligibility": "must_be_confirmed_by_tmobile_authorization",
        "bland_required": False,
        "google_voice_required": False,
        "fail_closed": True,
    }


@app.get("/voice/byon/link")
async def byon_link(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _tmobile_client_id() or not _tmobile_client_secret():
        raise HTTPException(503, "T-Mobile BYON application credentials are not configured")
    state = _tmobile_state()
    device_id = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, _base_url() + '/tmobile-byon-owner')}"
    params = {
        "client_id": _tmobile_client_id(),
        "client_secret": _tmobile_client_secret(),
        "device_id": device_id,
        "state": state,
        "redirect_uri": _tmobile_redirect_uri(),
    }
    return RedirectResponse(url=f"{_tmobile_base()}/v1/account-mgmt/linkAccount?{urlencode(params)}", status_code=307)


@app.get("/voice/byon/callback")
async def byon_callback(request: Request):
    code = request.query_params.get("code") or request.query_params.get("auth_code") or ""
    state = request.query_params.get("state") or ""
    if not code or not state or not _validate_tmobile_state(state):
        raise HTTPException(400, "Invalid or expired T-Mobile BYON authorization callback")
    await _store({
        "call_id": f"byon_auth_{secrets.token_urlsafe(10)}",
        "direction": "configuration",
        "status": "authorization_code_received",
        "provider": "tmobile_devedge_byon",
        "recording_enabled": False,
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "updated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    })
    return {
        "status": "authorization_code_received",
        "next_gate": "TMOBILE_POP_TOKEN_EXCHANGE",
        "message": "The T-Mobile line authorization returned successfully. Complete the supported DevEdge proof-of-possession token exchange before enabling PSTN calls.",
        "bland_required": False,
        "fail_closed": True,
    }
