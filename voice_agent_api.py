from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY OpenAI Realtime Voice Agent", version="2.0.0", docs_url=None, redoc_url=None)


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


def _openai_key() -> str:
    return _env("OPENAI_API_KEY")


def _reasoning_model() -> str:
    return _env("OPENAI_PRIMARY_MODEL") or "gpt-5.6-sol"


def _realtime_model() -> str:
    return _env("OPENAI_REALTIME_MODEL") or "gpt-realtime-2.1"


def _openai_project_id() -> str:
    return _env("OPENAI_PROJECT_ID")


def _realtime_voice() -> str:
    return _env("OPENAI_REALTIME_VOICE") or "cedar"


def _bland_key() -> str:
    return _env("BLAND_API_KEY", "BLAND_AI_API_KEY")


def _outbound_number() -> str:
    return _env("BLAND_OUTBOUND_NUMBER", "BLAND_PHONE_NUMBER", "OUTBOUND_PHONE_NUMBER")


def _inbound_number() -> str:
    return _env("BLAND_INBOUND_NUMBER", "INBOUND_PHONE_NUMBER")


def _base_url() -> str:
    return _env("BUSINESS_CANONICAL_WEBSITE", "APP_URL") or "https://www.sahjony.com"


def _voice_instructions(context: str | None = None) -> str:
    extra = (context or "").strip()[:4000]
    return (
        "You are the real-time inbound and outbound business phone agent for SAHJONY Global Trade. "
        "Your job on inbound calls is to professionally answer the business line, identify the caller and company, understand the commercial purpose, qualify the opportunity, capture exact contact and trade details, and finish with a clear next step. "
        "Opening: greet the caller as SAHJONY Global Trade, offer assistance immediately, and do not use a long disclaimer. Use natural, fast, concise phone cadence. "
        "Detect the caller's language automatically and answer in that same language; switch when the caller switches. Preserve exact names, companies, email addresses, phone numbers, product specifications, quantities, currencies, Incoterms, ports, legal terms and numbers. "
        "Early in every commercial inbound call collect the caller's full name, company name, role/title, callback number, email address, country, and company website when available. Confirm critical spellings aloud when uncertain. "
        "Classify the caller as buyer, supplier/manufacturer, logistics/freight, customs/compliance, finance/payment, insurance, technology/provider, government/institutional, or other. "
        "For buyers collect company, product, exact specification, quantity, destination country and port, required timing, Incoterm preference, target or workable pricing only if volunteered, payment instrument/capability, documentation readiness, purchasing authority, and whether the requirement is immediate, recurring, or exploratory. "
        "For suppliers and manufacturers collect company, manufacturing location, product and exact specification, production capacity, MOQ, available models/SKUs, certifications, indicative EXW/FOB/CIF pricing, loading port, lead time, warranty, payment terms, current availability, export markets, and whether they can provide company profile, business registration, certifications, recent product data sheets, commercial quotation and references. "
        "For North America EV charger suppliers such as Servotech, treat the call as a priority sourcing opportunity. Collect AC and DC charger models, rated power options, input voltage/frequency, output voltage/current, connector support including CCS1 and NACS where applicable, OCPP version, network/backend compatibility, enclosure/IP rating, operating temperature, cable length, pedestal/wall-mount options, payment-terminal options if any, UL/ETL/CSA/FCC and other North America certifications or certification status, warranty, spare parts/service support, MOQ, 20-foot-container loading quantity, EXW and FOB pricing, CIF capability, production lead time, sample availability, private-label capability, North America references, and the direct export/commercial decision-maker. Ask them to send the company profile, business card/contact details, technical data sheets, certifications, and formal quotation after the call. "
        "If the caller is Servotech or references the existing North America AC/DC EV charger RFQ, acknowledge that SAHJONY is actively qualifying the opportunity and focus on completing missing technical, certification, commercial, and delivery information rather than restarting the conversation from zero. "
        "For logistics/freight callers collect origin, destination, mode, equipment/container type, cargo description, weight/volume, hazardous classification when relevant, routing, transit time, quote validity, surcharges and insurance/customs scope. "
        "For compliance, customs, financial, insurance or institutional callers capture the exact requested documents, deadlines, reference numbers and responsible contact. Do not interpret a regulator's or bank's requirement beyond what the caller states; escalate material decisions. "
        "If the caller asks for an authorized human, a binding decision, a confidential negotiation, an urgent institutional matter, or a material price/contract/payment decision, collect the reason, best callback details and requested timing and mark the matter for human escalation. Never pretend a live transfer occurred unless a transfer tool explicitly confirms it. "
        "Never request or repeat full card numbers, bank passwords, authentication codes, private keys, API keys, Social Security numbers, or other unnecessary secrets over the phone. "
        "If directly asked whether you are AI or automated, answer truthfully that you are an AI business assistant for SAHJONY Global Trade. "
        "Never claim QUALIFIED, APPROVED, CONTRACTED, PROVIDER_READY, sanctions-cleared or credit-approved solely from a call. Never bind SAHJONY to price, purchase, sale, financing, payment, exclusivity, contract, KYC approval or sanctions approval; escalate those decisions to an authorized human. "
        "Respect do-not-call requests immediately. Do not intentionally record the call. Before ending, summarize the caller's company, opportunity, the most important commercial facts and missing items in one concise confirmation, then state the next action and expected follow-up channel. "
        "The governed commercial reasoning model is GPT-5.6 Sol. The only live conversational voice engine is OpenAI Realtime; Bland must never generate the conversational voice or answers. "
        + (f"Call context: {extra}" if extra else "")
    )


async def _store(row: dict[str, Any]) -> None:
    try:
        await get_backend().insert("voice_calls", row)
    except Exception:
        pass


@app.get("/voice/health")
async def health() -> dict[str, Any]:
    openai = bool(_openai_key())
    bland_transport = bool(_bland_key()) and bool(_inbound_number() or _outbound_number())
    return {
        "status": "ok" if openai else "configuration_required",
        "service": "sahjony-openai-realtime-voice",
        "version": "2.0.0",
        "business_identity": "SAHJONY Global Trade",
        "voice_engine": "openai_realtime",
        "reasoning_engine": "openai",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "realtime_voice": _realtime_voice(),
        "openai_configured": openai,
        "openai_project_id_configured": bool(_openai_project_id()),
        "telephony_transport": "bland_sip" if bland_transport else "sip_required",
        "bland_role": "telephony_sip_only",
        "bland_voice_ai_enabled": False,
        "inbound_number_configured": bool(_inbound_number()),
        "outbound_number_configured": bool(_outbound_number()),
        "language_mode": "worldwide_auto_detect",
        "recording_enabled": False,
        "human_approval_gates": ["price_commitment", "contract", "payment", "credit", "exclusivity", "kyc", "sanctions"],
        "fail_closed": True,
    }


class SolReasoningRequest(BaseModel):
    transcript: str = Field(min_length=1, max_length=12000)
    context: str | None = Field(default=None, max_length=6000)


@app.post("/voice/sol/reason")
async def sol_reason(payload: SolReasoningRequest, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _openai_key():
        raise HTTPException(503, "OpenAI is not configured")
    body = {
        "model": _reasoning_model(),
        "instructions": _voice_instructions(payload.context),
        "input": payload.transcript,
        "max_output_tokens": 700,
    }
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {_openai_key()}", "Content-Type": "application/json"},
            json=body,
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"OpenAI Sol reasoning request failed ({response.status_code})")
    data = response.json()
    text = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    text += content.get("text", "")
    return {"status": "ok", "model": _reasoning_model(), "output_text": text.strip(), "response_id": data.get("id")}


@app.post("/voice/openai/sip/incoming")
async def openai_sip_incoming(request: Request):
    """OpenAI webhook target for realtime.call.incoming events."""
    if not _openai_key():
        raise HTTPException(503, "OpenAI is not configured")
    payload = await request.json()
    event_type = str(payload.get("type") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    call_id = str(data.get("call_id") or data.get("id") or "").strip()
    if event_type and event_type != "realtime.call.incoming":
        return {"status": "ignored", "event_type": event_type}
    if not call_id:
        raise HTTPException(400, "Missing OpenAI realtime call_id")
    accept = {
        "type": "realtime",
        "model": _realtime_model(),
        "instructions": _voice_instructions(),
        "output_modalities": ["audio"],
        "audio": {
            "output": {"voice": _realtime_voice()},
            "input": {"turn_detection": {"type": "semantic_vad"}},
        },
        "tracing": "auto",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.openai.com/v1/realtime/calls/{call_id}/accept",
            headers={"Authorization": f"Bearer {_openai_key()}", "Content-Type": "application/json"},
            json=accept,
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"OpenAI Realtime SIP accept failed ({response.status_code})")
    await _store({
        "call_id": call_id,
        "direction": "inbound",
        "status": "accepted",
        "provider": "openai_realtime",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "telephony_transport": "sip",
        "recording_enabled": False,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return {"status": "accepted", "call_id": call_id, "voice_engine": "openai_realtime", "model": _realtime_model()}


@app.post("/voice/sip/configure-bland-inbound")
async def configure_bland_inbound(authorization: str | None = Header(None, alias="Authorization")):
    """Use Bland only to forward its inbound number over SIP to OpenAI Realtime."""
    _owner(authorization)
    if not _bland_key() or not _inbound_number():
        raise HTTPException(503, "Bland SIP transport is not configured")
    if not _openai_project_id():
        raise HTTPException(503, "OPENAI_PROJECT_ID is required to route SIP directly to OpenAI Realtime")
    sip_endpoint = f"sip:{_openai_project_id()}@sip.api.openai.com;transport=tls"
    body = {
        "phone_number": _inbound_number(),
        "service": "sip",
        "directions": [{
            "type": "inbound",
            "auth_mode": "ip",
            "sip_endpoint": sip_endpoint,
            "options": {"port": 5061, "transport": "tls", "secure_media": True},
        }],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.bland.ai/v1/sip/attach",
            headers={"authorization": _bland_key(), "Content-Type": "application/json"},
            json=body,
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"Bland SIP routing update failed ({response.status_code})")
    return {
        "status": "configured",
        "phone_number": _inbound_number(),
        "sip_endpoint": sip_endpoint,
        "voice_engine": "openai_realtime",
        "bland_role": "telephony_sip_only",
        "bland_voice_ai_enabled": False,
    }


@app.get("/voice/sip/status")
async def sip_status(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _bland_key() or not _inbound_number():
        raise HTTPException(503, "Bland SIP transport is not configured")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://api.bland.ai/v1/sip",
            headers={"authorization": _bland_key()},
            params={"phone_number": _inbound_number()},
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"Unable to read Bland SIP configuration ({response.status_code})")
    return {"status": "ok", "voice_engine": "openai_realtime", "bland_role": "telephony_sip_only", "sip": response.json().get("data")}


@app.post("/voice/outbound")
async def outbound_disabled_for_bland_voice(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    raise HTTPException(
        503,
        "Bland Voice AI outbound calling is disabled by policy. Outbound must originate through an OpenAI-Realtime-compatible SIP carrier/PBX so OpenAI remains the exclusive conversational voice engine.",
    )


@app.post("/voice/webhook")
async def legacy_bland_webhook(request: Request, x_bland_signature: str | None = Header(None, alias="X-Bland-Signature")):
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
    await _store({
        "call_id": call_id,
        "direction": payload.get("direction") or "unknown",
        "status": payload.get("status") or "legacy_event",
        "provider": "bland_sip",
        "voice_engine": "openai_realtime",
        "recording_enabled": False,
        "provider_payload": payload,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return {"status": "accepted", "call_id": call_id, "bland_role": "telephony_sip_only"}
