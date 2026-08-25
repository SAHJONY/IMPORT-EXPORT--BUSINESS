from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Bland Outbound Transport", version="1.0.0", docs_url=None, redoc_url=None)


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _bland_key() -> str:
    return _env("BLAND_API_KEY", "BLAND_AI_API_KEY")


def _outbound_number() -> str:
    return _env("BLAND_OUTBOUND_NUMBER", "BLAND_PHONE_NUMBER", "OUTBOUND_PHONE_NUMBER")


def _base_url() -> str:
    return _env("BUSINESS_CANONICAL_WEBSITE", "APP_URL") or "https://www.sahjony.com"


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


def _normalize_phone(value: str) -> str:
    value = value.strip()
    digits = re.sub(r"\D", "", value)
    if value.startswith("+"):
        normalized = "+" + digits
    elif len(digits) == 10:
        normalized = "+1" + digits
    elif 11 <= len(digits) <= 15:
        normalized = "+" + digits
    else:
        raise HTTPException(422, "Phone number must be a valid E.164 number")
    if not re.fullmatch(r"\+[1-9]\d{6,14}", normalized):
        raise HTTPException(422, "Phone number must be a valid E.164 number")
    return normalized


def _normalize_language(value: str | None) -> str | None:
    raw = (value or "auto").strip()
    if not raw or raw.lower() == "auto":
        return None
    key = raw.lower().replace("_", "-")
    aliases = {
        "english": "en-US", "en": "en-US", "en-us": "en-US",
        "spanish": "es", "español": "es", "es": "es",
        "french": "fr", "français": "fr", "fr": "fr",
        "portuguese": "pt", "português": "pt", "pt": "pt",
        "german": "de", "deutsch": "de", "de": "de",
        "italian": "it", "italiano": "it", "it": "it",
        "arabic": "ar", "العربية": "ar", "ar": "ar",
        "babel": "babel", "multilingual": "babel",
    }
    return aliases.get(key, raw)


def _task(context: str | None, language: str | None) -> str:
    extra = (context or "").strip()[:4000]
    language_hint = language or "automatic detection"
    return (
        "You are the business phone agent for SAHJONY Global Trade. "
        "Open naturally: Hello, this is SAHJONY Global Trade. "
        "Detect the person's language and respond naturally in that language. "
        f"Initial language hint: {language_hint}. "
        "For buyers, collect company, product, quantity, destination, timing, Incoterm preference, payment capability, documentation readiness, and decision authority. "
        "For suppliers, collect company, product specification, capacity, MOQ, certifications, indicative FOB/CIF pricing, lead time, payment terms, and availability. "
        "Preserve exact names, companies, product specifications, quantities, currencies, Incoterms, ports, legal terms, and numbers. "
        "Never claim a party is qualified, approved, contracted, provider-ready, sanctions-cleared, or credit-approved solely from the call. "
        "Never bind SAHJONY to price, purchase, sale, financing, payment, exclusivity, contract, KYC approval, or sanctions approval. "
        "Respect do-not-call requests immediately. Do not intentionally record the call. End with a concise confirmed next step. "
        + (f"Call context: {extra}" if extra else "")
    )


class OutboundCall(BaseModel):
    phone_number: str = Field(min_length=7, max_length=64)
    contact_name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=240)
    context: str | None = Field(default=None, max_length=4000)
    lead_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    language: str = Field(default="auto", max_length=35)


async def _store(row: dict[str, Any]) -> None:
    try:
        await get_backend().insert("voice_calls", row)
    except Exception:
        pass


@app.post("/voice/outbound")
async def outbound(payload: OutboundCall, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    api_key = _bland_key()
    from_number_raw = _outbound_number()
    if not api_key or not from_number_raw:
        raise HTTPException(503, "Bland AI outbound calling is not configured")

    phone_number = _normalize_phone(payload.phone_number)
    from_number = _normalize_phone(from_number_raw)
    language = _normalize_language(payload.language)
    metadata = {
        "lead_id": payload.lead_id,
        "trade_case_id": payload.trade_case_id,
        "contact_name": payload.contact_name,
        "company": payload.company,
        "language_hint": language or "auto",
        "source": "sahjony_global_trade_os",
    }

    # Keep this payload intentionally conservative. This exact shape is compatible
    # with Bland's current Send Call API and mirrors the last production request
    # shape that successfully queued an outbound call.
    body: dict[str, Any] = {
        "phone_number": phone_number,
        "from": from_number,
        "task": _task(payload.context, language),
        "record": False,
        "metadata": metadata,
        "webhook": f"{_base_url().rstrip('/')}/voice/webhook",
    }
    if language:
        body["language"] = language

    pathway = _env("BLAND_PATHWAY_ID")
    if pathway:
        body["pathway_id"] = pathway

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.bland.ai/v1/calls",
            headers={"authorization": api_key, "Content-Type": "application/json"},
            json=body,
        )

    if response.status_code >= 400:
        provider_message = ""
        try:
            data = response.json()
            provider_message = str(data.get("message") or data.get("error") or data.get("errors") or "")[:500]
        except Exception:
            provider_message = response.text[:500]
        detail = f"Bland AI rejected outbound call ({response.status_code})"
        if provider_message:
            detail += f": {provider_message}"
        raise HTTPException(502, detail)

    data = response.json()
    call_id = str(data.get("call_id") or data.get("id") or f"call_{secrets.token_urlsafe(12)}")
    now = datetime.now(timezone.utc).isoformat()
    await _store({
        "call_id": call_id,
        "direction": "outbound",
        "phone_number": phone_number,
        "contact_name": payload.contact_name,
        "company": payload.company,
        "lead_id": payload.lead_id,
        "trade_case_id": payload.trade_case_id,
        "language_hint": language or "auto",
        "status": "queued",
        "provider": "bland_ai",
        "recording_enabled": False,
        "created_at": now,
        "updated_at": now,
    })
    return {
        "status": "queued",
        "call_id": call_id,
        "provider": "bland_ai",
        "language_mode": language or "auto",
        "recording_enabled": False,
    }
