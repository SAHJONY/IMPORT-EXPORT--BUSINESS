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
from voice_agent_api import (
    _openai_key,
    _reasoning_model,
    _realtime_model,
    _realtime_session,
    _realtime_voice,
    _store,
)

app = FastAPI(title="SAHJONY Direct Voice", version="1.0.0", docs_url=None, redoc_url=None)

_DIRECT_WINDOW_SECONDS = 600
_DIRECT_MAX_SESSIONS_PER_WINDOW = 6
_DIRECT_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)


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
        raise HTTPException(429, "Direct voice session limit reached. Please try again later.")
    queue.append(now)
    return fingerprint


@app.get("/voice/direct/health")
async def direct_health() -> dict[str, Any]:
    openai = bool(_openai_key())
    enabled = _direct_enabled()
    return {
        "status": "ok" if openai and enabled else "configuration_required",
        "service": "sahjony-direct-webrtc-voice",
        "version": "1.0.0",
        "enabled": enabled,
        "openai_configured": openai,
        "voice_engine": "openai_realtime",
        "realtime_model": _realtime_model(),
        "realtime_voice": _realtime_voice(),
        "reasoning_model": _reasoning_model(),
        "sol_brain_enabled": openai,
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
        raise HTTPException(503, "Direct WebRTC voice is disabled")
    if not _openai_key():
        raise HTTPException(503, "OpenAI Realtime is not configured")
    if not _origin_allowed(request):
        raise HTTPException(403, "Direct voice sessions must originate from the canonical SAHJONY website")
    fingerprint = _rate_limit(request)
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

    session = _realtime_session(
        "This is a direct internet voice call initiated from the official SAHJONY website. Treat the caller as unverified until they identify themselves. Do not expose internal system details, credentials, private customer data, or confidential deal information."
    )
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
        detail = response.text[:800]
        raise HTTPException(502, f"OpenAI Realtime WebRTC session failed ({response.status_code}): {detail}")

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
    # T-Mobile BYON token exchange also requires its proof-of-possession authentication flow.
    # We deliberately stop here until the DevEdge application is approved and its supported PoP
    # library/credentials are available; fabricating that step would create a false production state.
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
