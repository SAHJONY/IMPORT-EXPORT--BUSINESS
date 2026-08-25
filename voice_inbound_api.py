from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token

app = FastAPI(title="SAHJONY Inbound Voice Transport", version="1.3.0", docs_url=None, redoc_url=None)
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


def _outbound_number() -> str:
    return _env("BLAND_OUTBOUND_NUMBER", "BLAND_PHONE_NUMBER", "OUTBOUND_PHONE_NUMBER")


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
        raise HTTPException(422, "Phone number must be valid E.164")
    if not re.fullmatch(r"\+[1-9]\d{6,14}", normalized):
        raise HTTPException(422, "Phone number must be valid E.164")
    return normalized


def _sip_endpoint(project_id: str) -> str:
    return f"sip:{project_id}@sip.api.openai.com;transport=tls"


def _sip_direction(project_id: str) -> dict[str, Any]:
    return {
        "type": "inbound",
        "auth_mode": "ip",
        "sip_endpoint": _sip_endpoint(project_id),
        "options": {"port": 5061, "transport": "tls", "secure_media": True},
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
        return "update", "https://api.bland.ai/v1/sip/update", {"phone_number": number, "updates": direction}
    return "attach", "https://api.bland.ai/v1/sip/attach", {"phone_number": number, "service": "sip", "directions": [direction]}


async def _read_config(client: httpx.AsyncClient, key: str, number: str) -> tuple[httpx.Response, Any]:
    response = await client.get("https://api.bland.ai/v1/sip", headers={"authorization": key}, params={"phone_number": number})
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


def _number_set(payload: Any, field: str) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    rows = payload.get(field)
    if not isinstance(rows, list):
        return set()
    return {str(row.get("phone_number") or "") for row in rows if isinstance(row, dict) and row.get("phone_number")}


def _sip_number_health(payload: Any, number: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    rows = data.get("numbers")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and str(row.get("phone_number") or "") == number:
            return str(row.get("health_status") or "") or None
    return None


async def bland_account_snapshot() -> dict[str, Any]:
    """Server-side account/number reconciliation. Never returns the API key."""
    key = _bland_key()
    inbound_raw = _inbound_number()
    outbound_raw = _outbound_number()
    if not key:
        return {"status": "configuration_required", "api_key_configured": False, "production_ready": False, "fail_closed": True}

    inbound = _normalize_phone(inbound_raw) if inbound_raw else None
    outbound = _normalize_phone(outbound_raw) if outbound_raw else None
    headers = {"authorization": key}
    async with httpx.AsyncClient(timeout=20) as client:
        me_r, in_r, out_r, sip_r = await asyncio.gather(
            client.get("https://api.bland.ai/v1/me", headers=headers),
            client.get("https://api.bland.ai/v1/inbound", headers=headers),
            client.get("https://api.bland.ai/v1/outbound", headers=headers),
            client.get("https://api.bland.ai/v1/sip/numbers", headers=headers),
        )

    responses = {"account": me_r, "inbound": in_r, "outbound": out_r, "sip": sip_r}
    provider_errors = {name: {"status": resp.status_code, "message": _provider_message(resp)} for name, resp in responses.items() if resp.status_code >= 400}
    if me_r.status_code >= 400:
        return {
            "status": "blocked",
            "api_key_configured": True,
            "api_key_valid": False,
            "production_ready": False,
            "provider_errors": provider_errors,
            "fail_closed": True,
        }

    me = me_r.json() if me_r.content else {}
    inbound_payload = in_r.json() if in_r.status_code < 400 and in_r.content else {}
    outbound_payload = out_r.json() if out_r.status_code < 400 and out_r.content else {}
    sip_payload = sip_r.json() if sip_r.status_code < 400 and sip_r.content else {}
    billing = me.get("billing") if isinstance(me, dict) and isinstance(me.get("billing"), dict) else {}
    balance = billing.get("current_balance")
    try:
        balance_number = float(balance)
    except (TypeError, ValueError):
        balance_number = 0.0

    inbound_numbers = _number_set(inbound_payload, "inbound_numbers")
    outbound_numbers = _number_set(outbound_payload, "outbound_numbers")
    inbound_owned = bool(inbound and inbound in inbound_numbers)
    outbound_owned = bool(outbound and outbound in outbound_numbers)
    inbound_sip_health = _sip_number_health(sip_payload, inbound) if inbound else None
    outbound_sip_health = _sip_number_health(sip_payload, outbound) if outbound else None
    account_active = str(me.get("status") or "").lower() == "active"
    balance_ok = balance_number > 0
    numbers_ok = (not inbound or inbound_owned) and (not outbound or outbound_owned)
    provider_reads_ok = not provider_errors
    production_ready = bool(account_active and balance_ok and numbers_ok and provider_reads_ok and (inbound or outbound))

    return {
        "status": "ready" if production_ready else "blocked",
        "api_key_configured": True,
        "api_key_valid": True,
        "account_status": me.get("status"),
        "balance": balance_number,
        "balance_ok": balance_ok,
        "auto_refill_to": billing.get("refill_to"),
        "total_calls": me.get("total_calls"),
        "configured_inbound_number": inbound,
        "configured_outbound_number": outbound,
        "inbound_number_belongs_to_account": inbound_owned if inbound else None,
        "outbound_number_belongs_to_account": outbound_owned if outbound else None,
        "inbound_sip_health": inbound_sip_health,
        "outbound_sip_health": outbound_sip_health,
        "provider_errors": provider_errors,
        "production_ready": production_ready,
        "failure_reasons": [
            reason for condition, reason in (
                (not account_active, "BLAND_ACCOUNT_NOT_ACTIVE"),
                (not balance_ok, "BLAND_BALANCE_NOT_POSITIVE"),
                (bool(inbound and not inbound_owned), "INBOUND_NUMBER_NOT_IN_THIS_ACCOUNT"),
                (bool(outbound and not outbound_owned), "OUTBOUND_NUMBER_NOT_IN_THIS_ACCOUNT"),
                (bool(provider_errors), "BLAND_ACCOUNT_RECONCILIATION_INCOMPLETE"),
            ) if condition
        ],
        "fail_closed": True,
    }


async def bland_account_preflight(*, require_inbound: bool = False, require_outbound: bool = False) -> dict[str, Any]:
    snapshot = await bland_account_snapshot()
    if not snapshot.get("production_ready"):
        raise HTTPException(503, {"code": "BLAND_ACCOUNT_PREFLIGHT_FAILED", "reasons": snapshot.get("failure_reasons") or ["BLAND_ACCOUNT_NOT_READY"]})
    if require_inbound and not snapshot.get("inbound_number_belongs_to_account"):
        raise HTTPException(503, {"code": "BLAND_INBOUND_ACCOUNT_MISMATCH"})
    if require_outbound and not snapshot.get("outbound_number_belongs_to_account"):
        raise HTTPException(503, {"code": "BLAND_OUTBOUND_ACCOUNT_MISMATCH"})
    return snapshot


@app.get("/voice/bland/account")
async def bland_account_status(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    return await bland_account_snapshot()


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

    account = await bland_account_preflight(require_inbound=True)
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
        "bland_account_ready": account.get("production_ready"),
        "openai_incoming_webhook_path": "/voice/openai/sip/incoming",
        "fail_closed": True,
    }


@app.get("/voice/inbound/doctor")
async def inbound_doctor(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    key = _bland_key()
    number_raw = _inbound_number()
    project_id = _openai_project_id()
    missing = [name for name, value in (("BLAND_API_KEY", key), ("BLAND_INBOUND_NUMBER", number_raw), ("OPENAI_PROJECT_ID", project_id)) if not value]
    if missing:
        return {"status": "blocked", "service": "inbound_voice_doctor", "missing": missing, "preflight_ok": False, "fail_closed": True}

    account = await bland_account_snapshot()
    if not account.get("production_ready") or not account.get("inbound_number_belongs_to_account"):
        return {
            "status": "blocked",
            "service": "inbound_voice_doctor",
            "account_reconciliation": account,
            "preflight_ok": False,
            "fail_closed": True,
        }

    number = _normalize_phone(number_raw)
    endpoint = _sip_endpoint(project_id)
    async with httpx.AsyncClient(timeout=20) as client:
        read, current = await _read_config(client, key, number)
        if read.status_code >= 400:
            return {"status": "blocked", "service": "inbound_voice_doctor", "read_status": read.status_code, "provider_message": _provider_message(read) or None, "preflight_ok": False, "fail_closed": True}
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
        "account_reconciliation": account,
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

    account = await bland_account_preflight(require_inbound=True)
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
        write = await client.post(url, headers={"authorization": key, "Content-Type": "application/json"}, json=body)
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
        "bland_account_ready": account.get("production_ready"),
        "openai_incoming_webhook_path": "/voice/openai/sip/incoming",
        "next_gate": "OpenAI project webhook must deliver realtime.call.incoming events to the incoming webhook path",
        "fail_closed": True,
    }
