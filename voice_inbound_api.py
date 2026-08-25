from __future__ import annotations

import os
import re
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token

app = FastAPI(title="SAHJONY Inbound Voice Transport", version="1.0.0", docs_url=None, redoc_url=None)


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


def _bland_key() -> str:
    return _env("BLAND_API_KEY", "BLAND_AI_API_KEY")


def _inbound_number() -> str:
    return _env("BLAND_INBOUND_NUMBER", "INBOUND_PHONE_NUMBER")


def _openai_project_id() -> str:
    return _env("OPENAI_PROJECT_ID")


def _normalize_phone(value: str) -> str:
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("+"):
        normalized = "+" + digits
    elif len(digits) == 10:
        normalized = "+1" + digits
    elif 11 <= len(digits) <= 15:
        normalized = "+" + digits
    else:
        raise HTTPException(422, "Inbound phone number must be valid E.164")
    if not re.fullmatch(r"\+[1-9]\d{6,14}", normalized):
        raise HTTPException(422, "Inbound phone number must be valid E.164")
    return normalized


def _sip_endpoint(project_id: str) -> str:
    return f"sip:{project_id}@sip.api.openai.com"


def _provider_error(response: httpx.Response, prefix: str) -> HTTPException:
    message = ""
    try:
        data = response.json()
        message = str(data.get("message") or data.get("error") or data.get("errors") or data.get("detail") or "")[:800]
    except Exception:
        message = response.text[:800]
    detail = f"{prefix} ({response.status_code})"
    if message:
        detail += f": {message}"
    return HTTPException(502, detail)


@app.get("/voice/inbound/status")
async def inbound_status(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    key = _bland_key()
    number_raw = _inbound_number()
    project_id = _openai_project_id()
    if not key or not number_raw or not project_id:
        return {
            "status": "configuration_required",
            "service": "inbound_voice_transport",
            "bland_api_configured": bool(key),
            "inbound_number_configured": bool(number_raw),
            "openai_project_id_configured": bool(project_id),
            "sip_verified": False,
            "fail_closed": True,
        }

    number = _normalize_phone(number_raw)
    expected_endpoint = _sip_endpoint(project_id)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://api.bland.ai/v1/sip",
            headers={"authorization": key},
            params={"phone_number": number},
        )
    if response.status_code >= 400:
        raise _provider_error(response, "Unable to read Bland inbound SIP configuration")

    payload = response.json()
    inbound = ((payload.get("data") or {}).get("inbound")) if isinstance(payload, dict) else None
    actual_endpoint = str((inbound or {}).get("sip_endpoint") or "")
    options = (inbound or {}).get("options") or {}
    endpoint_ok = expected_endpoint.lower() in actual_endpoint.lower() or project_id.lower() in actual_endpoint.lower()
    transport_ok = str(options.get("transport") or "tls").lower() == "tls"
    sip_verified = bool(inbound) and endpoint_ok and transport_ok

    return {
        "status": "ok" if sip_verified else "configuration_required",
        "service": "inbound_voice_transport",
        "phone_number": number,
        "provider": "bland_sip",
        "destination": "openai_realtime",
        "expected_sip_endpoint": expected_endpoint,
        "configured_sip_endpoint": actual_endpoint or None,
        "transport": options.get("transport"),
        "secure_media": options.get("secure_media"),
        "sip_verified": sip_verified,
        "openai_incoming_webhook_path": "/voice/openai/sip/incoming",
        "fail_closed": True,
    }


@app.post("/voice/inbound/configure")
async def configure_inbound(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    key = _bland_key()
    number_raw = _inbound_number()
    project_id = _openai_project_id()
    if not key:
        raise HTTPException(503, "BLAND_API_KEY is not configured")
    if not number_raw:
        raise HTTPException(503, "BLAND_INBOUND_NUMBER is not configured")
    if not project_id:
        raise HTTPException(503, "OPENAI_PROJECT_ID is not configured")

    number = _normalize_phone(number_raw)
    endpoint = _sip_endpoint(project_id)
    body = {
        "phone_number": number,
        "service": "sip",
        "directions": [
            {
                "type": "inbound",
                "auth_mode": "ip",
                "sip_endpoint": endpoint,
                "options": {
                    "port": 5061,
                    "transport": "tls",
                    "secure_media": True,
                },
            }
        ],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        attach = await client.post(
            "https://api.bland.ai/v1/sip/attach",
            headers={"authorization": key, "Content-Type": "application/json"},
            json=body,
        )
        if attach.status_code >= 400:
            raise _provider_error(attach, "Bland rejected inbound SIP configuration")

        attach_payload = attach.json()
        data = attach_payload.get("data") or {}
        configured = data.get("configured") or []
        failed = data.get("failed") or []
        if number not in configured or failed:
            raise HTTPException(502, f"Bland did not confirm inbound SIP configuration: failed={failed}")

        verify = await client.get(
            "https://api.bland.ai/v1/sip",
            headers={"authorization": key},
            params={"phone_number": number},
        )
        if verify.status_code >= 400:
            raise _provider_error(verify, "Inbound SIP attach succeeded but verification failed")

    verified_payload = verify.json()
    inbound = ((verified_payload.get("data") or {}).get("inbound")) if isinstance(verified_payload, dict) else None
    actual_endpoint = str((inbound or {}).get("sip_endpoint") or "")
    options = (inbound or {}).get("options") or {}
    endpoint_ok = endpoint.lower() in actual_endpoint.lower() or project_id.lower() in actual_endpoint.lower()
    transport_ok = str(options.get("transport") or "tls").lower() == "tls"
    if not inbound or not endpoint_ok or not transport_ok:
        raise HTTPException(502, "Bland returned success but inbound SIP verification did not match the expected OpenAI Realtime destination")

    return {
        "status": "configured",
        "phone_number": number,
        "provider": "bland_sip",
        "destination": "openai_realtime",
        "sip_endpoint": actual_endpoint,
        "transport": options.get("transport") or "tls",
        "secure_media": options.get("secure_media"),
        "openai_incoming_webhook_path": "/voice/openai/sip/incoming",
        "next_gate": "OpenAI project webhook must deliver realtime.call.incoming events to the incoming webhook path",
        "fail_closed": True,
    }
