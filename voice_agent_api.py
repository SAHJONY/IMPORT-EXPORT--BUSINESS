from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Voice Agent", version="1.2.0", docs_url=None, redoc_url=None)
Direction = Literal["inbound", "outbound"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _inbound_number() -> str:
    return _env("BLAND_INBOUND_NUMBER", "INBOUND_PHONE_NUMBER")


def _base_url() -> str:
    return _env("BUSINESS_CANONICAL_WEBSITE", "APP_URL") or "https://www.sahjony.com"


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


def _normalize_language(value: str | None) -> str:
    language = (value or "auto").strip()
    return language[:35] or "auto"


def _task(context: str | None = None, language: str = "auto", direction: Direction = "outbound") -> str:
    extra = (context or "").strip()[:4000]
    requested = _normalize_language(language)
    opening = (
        "For an inbound call, open naturally with: Thank you for calling SAHJONY Global Trade. My name is Juan Gonzalez. How may I help you? "
        if direction == "inbound"
        else "For an outbound call, open naturally with: Hello, my name is Juan Gonzalez calling from SAHJONY Global Trade. "
    )
    return (
        "You are the worldwide business phone agent for SAHJONY Global Trade. Your agent name is Juan Gonzalez. "
        "Use only SAHJONY Global Trade as the customer-facing business name. " + opening +
        "Do not spontaneously introduce yourself as AI, a bot, virtual assistant, automated system, or language model. "
        "If the person directly asks whether you are AI, automated, a bot, or a human, answer truthfully that you are an AI business assistant for SAHJONY Global Trade; never falsely claim to be human. "
        "Support callers worldwide in their preferred language. Detect the language spoken and respond naturally in that same language. If the person changes languages, follow them. "
        "Preserve names, company names, product specifications, quantities, currencies, Incoterms, addresses, ports, legal terms, and numbers accurately. "
        "If audio, dialect, terminology, or speech support is insufficient, ask the person to repeat, slow down, or spell critical details; never guess. "
        "The requested language/locale hint is '" + requested + "'; treat auto as automatic detection. "
        "For buyers collect company, product, quantity/volume, destination, timing, Incoterm preference, payment capability, documentation readiness, and decision authority. "
        "For suppliers collect company, product/specification, capacity, MOQ, certifications, indicative FOB/CIF pricing, lead time, warranty when relevant, payment terms, and availability. "
        "Never claim QUALIFIED, APPROVED, CONTRACTED, PROVIDER_READY, sanctions-cleared, or credit-approved solely from the call. "
        "Never bind SAHJONY Global Trade to price, purchase, sale, financing, payment, exclusivity, contract, KYC approval, sanctions approval, or another legal/commercial commitment. Escalate those matters to an authorized human. "
        "Respect do-not-call requests immediately. Do not intentionally record the call. End with a concise confirmed next step in the person's language. "
        + (f"Call context: {extra}" if extra else "")
    )


class OutboundCall(BaseModel):
    phone_number: str = Field(min_length=7, max_length=32)
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


@app.get("/voice/health")
async def health() -> dict[str, Any]:
    key, outbound, inbound = bool(_bland_key()), bool(_outbound_number()), bool(_inbound_number())
    return {
        "status": "ok" if key and outbound and inbound else "configuration_required",
        "service": "sahjony-voice-agent", "version": "1.2.0", "provider": "bland_ai",
        "business_identity": "SAHJONY Global Trade", "agent_name": "Juan Gonzalez",
        "bland_api_configured": key, "outbound_number_configured": outbound, "inbound_number_configured": inbound,
        "openai_configured": bool(_env("OPENAI_API_KEY")),
        "openai_primary_model": _env("OPENAI_PRIMARY_MODEL") or "gpt-5.6-sol",
        "openai_realtime_model": _env("OPENAI_REALTIME_MODEL") or "gpt-realtime-2.1",
        "language_mode": "worldwide_auto_detect", "recording_enabled": False,
        "human_approval_gates": ["price_commitment", "contract", "payment", "credit", "exclusivity", "kyc", "sanctions"],
        "fail_closed": True,
    }


@app.post("/voice/outbound")
async def outbound(payload: OutboundCall, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _bland_key() or not _outbound_number():
        raise HTTPException(503, "Bland AI outbound calling is not configured")
    language = _normalize_language(payload.language)
    metadata = {"lead_id": payload.lead_id, "trade_case_id": payload.trade_case_id, "contact_name": payload.contact_name, "company": payload.company, "language_hint": language, "source": "sahjony_global_trade_os"}
    body: dict[str, Any] = {"phone_number": payload.phone_number, "from": _outbound_number(), "task": _task(payload.context, language, "outbound"), "record": False, "metadata": metadata, "webhook": f"{_base_url().rstrip('/')}/voice/webhook"}
    if language.lower() != "auto":
        body["language"] = language
    pathway = _env("BLAND_PATHWAY_ID")
    if pathway:
        body["pathway_id"] = pathway
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://api.bland.ai/v1/calls", headers={"authorization": _bland_key(), "Content-Type": "application/json"}, json=body)
    if response.status_code >= 400:
        raise HTTPException(502, f"Bland AI rejected outbound call ({response.status_code})")
    data = response.json()
    call_id = str(data.get("call_id") or data.get("id") or f"call_{secrets.token_urlsafe(12)}")
    await _store({"call_id": call_id, "direction": "outbound", "phone_number": payload.phone_number, "contact_name": payload.contact_name, "company": payload.company, "lead_id": payload.lead_id, "trade_case_id": payload.trade_case_id, "language_hint": language, "status": "queued", "provider": "bland_ai", "recording_enabled": False, "created_at": _now(), "updated_at": _now()})
    return {"status": "queued", "call_id": call_id, "provider": "bland_ai", "language_mode": language, "recording_enabled": False}


@app.post("/voice/webhook")
async def webhook(request: Request, x_bland_signature: str | None = Header(None, alias="X-Bland-Signature")):
    raw = await request.body()
    secret = _env("BLAND_WEBHOOK_SECRET")
    if secret:
        digest = hashlib.sha256(secret.encode() + raw).hexdigest()
        supplied = (x_bland_signature or request.headers.get("X-Webhook-Secret") or "").strip()
        if not supplied or not (secrets.compare_digest(supplied, secret) or secrets.compare_digest(supplied, digest)):
            raise HTTPException(401, "Invalid voice webhook signature")
    try:
        payload = json.loads(raw.decode() or "{}")
    except Exception:
        payload = {}
    call_id = str(payload.get("call_id") or payload.get("id") or f"call_{secrets.token_urlsafe(12)}")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    await _store({"call_id": call_id, "direction": payload.get("direction") or "unknown", "status": payload.get("disposition") or payload.get("status") or "completed", "provider": "bland_ai", "lead_id": metadata.get("lead_id"), "trade_case_id": metadata.get("trade_case_id"), "contact_name": metadata.get("contact_name"), "company": metadata.get("company"), "language_hint": metadata.get("language_hint"), "summary": payload.get("summary") or payload.get("call_summary"), "transcript": payload.get("concatenated_transcript") or payload.get("transcript"), "recording_enabled": False, "provider_payload": payload, "created_at": payload.get("created_at") or _now(), "updated_at": _now()})
    return {"status": "accepted", "call_id": call_id}


@app.post("/voice/inbound")
async def inbound_event(request: Request):
    payload = await request.json()
    call_id = str(payload.get("call_id") or payload.get("id") or f"call_{secrets.token_urlsafe(12)}")
    language = _normalize_language(payload.get("language") or payload.get("locale") or "auto")
    await _store({"call_id": call_id, "direction": "inbound", "phone_number": payload.get("from") or payload.get("phone_number"), "language_hint": language, "status": payload.get("status") or "received", "provider": "bland_ai", "recording_enabled": False, "provider_payload": payload, "created_at": _now(), "updated_at": _now()})
    return {"status": "accepted", "call_id": call_id, "language_mode": "worldwide_auto_detect", "agent_policy": _task(language=language, direction="inbound")}
