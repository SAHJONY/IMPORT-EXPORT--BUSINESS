from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token

app = FastAPI(title="SAHJONY Inbound Voice Transport", version="1.1.0", docs_url=None, redoc_url=None)
logger = logging.getLogger("sahjony.voice.inbound")


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
    # OpenAI Realtime SIP destination. Transport is declared both in the URI
    # and in Bland options because carriers commonly canonicalize either form.
    return f"sip:{project_id}@sip.api.openai.com;transport=tls"


def _sip_direction(project_id: str) -> dict[str, Any]:
    return {
        "type": "inbound",
        "auth_mode": "ip",
        "sip_endpoint": _sip_endpoint(project_id),
        "options": {
            "port": 5061,
            "transport": "tls",
            "secure_media": True,
        },
    }


def _provider_message(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict):
            value = data.get("message") or data.get("error") or data.get("errors") or data.get("detail")
            if value:
                return str(value)[:800]
    except Exception:
        pass
    return response.text[:800]


def _provider_error(response: httpx.Response, prefix: str) -> HTTPException:
    message = _provider_message(response)
    detail = f"{prefix} ({response.status_code})"
    if message:
        detail += f": {message}"
    return HTTPException(502, detail)


def _inbound_from_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    inbound = data.get("inbound")
    return inbound if isinstance(inbound, dict) and inbound else None


def _build_write(current_payload: Any, number: str, project_id: str) -> tuple[str, str, dict[str, Any]]:
    direction = _sip_direction(project_id)
    if _inbound_from_payload(current_payload):
        return (
            "update",
            "https://api.bland.ai/v1/sip/update",
            {"phone_number": number, "updates": direction},
        )
    return (
        "attach",
        "https://api.bland.ai/v1/sip/attach",
        {"phone_number": number, "service": "sip", "directions": [direction]},
    )


async def _read_config(client: httpx.AsyncClient, key: str, number: str) -> tuple[httpx.Response, Any]:
    response = await client.get(
        "https://api.bland.ai/v1/sip",
        headers={"authorization": key},
        params={"phone_number": number},
    )
    payload: Any = {}
    if response.status_code < 400:
        try:
            payload = response.json()
        except Exception:
            payload = {}
    return response, payload


async def _validate_destination(client: httpx.AsyncClient, key: str, endpoint: str) -> tuple[bool, int, str | None]:
    response = await client.post(
        "https://api.bland.ai/v1/sip/parse-destination",
        headers={"authorization": key, "Content-Type": "application/json"},
        json={"input": endpoint},
    )
    if response.status_code < 400:
        return True, response.status_code, None
    return False, response.status_code, _provider_message(response) or None


def _verification(payload: Any, project_id: str) -> dict[str, Any]:
    inbound = _inbound_from_payload(payload)
    actual_endpoint = str((inbound or {}).get("sip_endpoint") or "")
    options = (inbound or {}).get("options") if isinstance((inbound or {}).get("options"), dict) else {}
    endpoint_ok = project_id.lower() in actual_endpoint.lower() and "sip.api.openai.com" in actual_endpoint.lower()
    transport_value = str(options.get("transport") or ("tls" if "transport=tls" in actual_endpoint.lower() else ""))
    transport_ok = transport_value.lower() == "tls"
    secure_media = options.get("secure_media")
    return {
        "inbound": inbound,
        "actual_endpoint": actual_endpoint,
        "options": options,
        "endpoint_ok": endpoint_ok,
        "transport_ok": transport_ok,
        "sip_verified": bool(inbound) and endpoint_ok and transport_ok,
        "secure_media": secure_media,
    }


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
    async with httpx.AsyncClient(timeout=20) as client:
        response, payload = await _read_config(client, key, number)
    if response.status_code >= 400:
        raise _provider_error(response, "Unable to read Bland inbound SIP configuration")

    check = _verification(payload, project_id)
    return {
        "status": "ok" if check["sip_verified"] else "configuration_required",
        "service": "inbound_voice_transport",
        "phone_number": number,
        "provider": "bland_sip",
        "destination": "openai_realtime",
        "expected_sip_endpoint": _sip_endpoint(project_id),
        "configured_sip_endpoint": check["actual_endpoint"] or None,
        "transport": check["options"].get("transport"),
        "secure_media": check["secure_media"],
        "sip_verified": check["sip_verified"],
        "openai_incoming_webhook_path": "/voice/openai/sip/incoming",
        "fail_closed": True,
    }


@app.get("/voice/inbound/doctor")
async def inbound_doctor(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    """Read-only preflight for Bland -> OpenAI Realtime SIP routing."""
    _owner(authorization)
    key = _bland_key()
    number_raw = _inbound_number()
    project_id = _openai_project_id()
    missing = [
        name for name, value in (
            ("BLAND_API_KEY", key),
            ("BLAND_INBOUND_NUMBER", number_raw),
            ("OPENAI_PROJECT_ID", project_id),
        ) if not value
    ]
    if missing:
        return {
            "status": "blocked",
            "service": "inbound_voice_doctor",
            "missing": missing,
            "preflight_ok": False,
            "fail_closed": True,
        }

    number = _normalize_phone(number_raw)
    endpoint = _sip_endpoint(project_id)
    async with httpx.AsyncClient(timeout=20) as client:
        read, current = await _read_config(client, key, number)
        if read.status_code >= 400:
            return {
                "status": "blocked",
                "service": "inbound_voice_doctor",
                "read_status": read.status_code,
                "provider_message": _provider_message(read) or None,
                "preflight_ok": False,
                "fail_closed": True,
            }
        parse_ok, parse_status, parse_message = await _validate_destination(client, key, endpoint)

    operation, _, _ = _build_write(current, number, project_id)
    check = _verification(current, project_id)
    data = current.get("data") if isinstance(current, dict) and isinstance(current.get("data"), dict) else {}
    return {
        "status": "ready" if parse_ok else "blocked",
        "service": "inbound_voice_doctor",
        "phone_number": number,
        "expected_sip_endpoint": endpoint,
        "current_inbound_exists": bool(_inbound_from_payload(current)),
        "current_sip_verified": check["sip_verified"],
        "recommended_operation": operation,
        "parse_destination_status": parse_status,
        "parse_destination_ok": parse_ok,
        "provider_message": parse_message,
        "provider_org_id": data.get("org_id") or data.get("organization_id"),
        "preflight_ok": parse_ok,
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
    async with httpx.AsyncClient(timeout=30) as client:
        read, current = await _read_config(client, key, number)
        if read.status_code >= 400:
            raise _provider_error(read, "Unable to read Bland SIP configuration before update")

        parse_ok, parse_status, parse_message = await _validate_destination(client, key, endpoint)
        if not parse_ok:
            logger.warning("Bland SIP destination preflight rejected status=%s message=%s", parse_status, parse_message)
            raise HTTPException(502, f"Bland rejected OpenAI SIP destination preflight ({parse_status}): {parse_message or 'no provider detail'}")

        operation, url, body = _build_write(current, number, project_id)
        write = await client.post(
            url,
            headers={"authorization": key, "Content-Type": "application/json"},
            json=body,
        )
        if write.status_code >= 400:
            message = _provider_message(write)
            logger.warning("Bland SIP %s rejected status=%s message=%s", operation, write.status_code, message)
            raise _provider_error(write, f"Bland rejected inbound SIP {operation}")

        verify, verified_payload = await _read_config(client, key, number)
        if verify.status_code >= 400:
            raise _provider_error(verify, "Inbound SIP write succeeded but verification failed")

    check = _verification(verified_payload, project_id)
    if not check["sip_verified"]:
        raise HTTPException(502, "Bland returned success but inbound SIP verification did not match the expected OpenAI Realtime destination")

    return {
        "status": "configured",
        "operation": operation,
        "phone_number": number,
        "provider": "bland_sip",
        "destination": "openai_realtime",
        "sip_endpoint": check["actual_endpoint"],
        "transport": check["options"].get("transport") or "tls",
        "secure_media": check["secure_media"],
        "openai_incoming_webhook_path": "/voice/openai/sip/incoming",
        "next_gate": "OpenAI project webhook must deliver realtime.call.incoming events to the incoming webhook path",
        "fail_closed": True,
    }
