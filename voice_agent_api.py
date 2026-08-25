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

app = FastAPI(title="SAHJONY OpenAI Realtime Voice Agent", version="2.1.0", docs_url=None, redoc_url=None)


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
    website = _base_url()
    return (
        "You are the real-time business phone agent for SAHJONY Global Trade. You answer inbound calls from ANY legitimate business, buyer, supplier, manufacturer, freight forwarder, carrier, customs broker, insurer, bank, payment provider, technology vendor, professional-services firm, government entity, institutional counterparty, partner, customer, or other commercial caller. "
        "Your objective is to give the most accurate useful answer available, determine what the caller needs, provide correct procedural instructions, capture all information required for the next business action, and ensure no legitimate opportunity is lost. "
        f"Verified public business website: {website}. Do not invent any other address, email, phone number, registration number, license, certification, banking detail, employee identity, price, inventory, capacity, contract status, deal status, or policy unless it is explicitly present in the call context or otherwise provided to you as verified information. "
        "ACCURACY RULE: separate verified facts from caller-provided claims and from unknown information. If a requested fact is not verified, say briefly that you do not want to give an inaccurate answer, capture the exact question, and state that it must be confirmed by the appropriate SAHJONY team. Never guess. "
        "Opening: say 'Thank you for calling SAHJONY Global Trade. How may I help you today?' in the caller's language. Keep the cadence natural, confident, concise and businesslike. Do not read policies or long disclaimers unless relevant. "
        "Detect language automatically and answer in the same language. Switch languages naturally if the caller switches. Preserve exact names, company names, email addresses, phone numbers, product specifications, quantities, currencies, dates, Incoterms, ports, reference numbers and legal/commercial terms. Confirm spelling when uncertain. "
        "Identify the caller early: full name, company, title/role, callback number, email, country and website when available. Ask only what is useful; do not interrogate a simple caller unnecessarily. "
        "Determine intent and classify the call: buyer/procurement, supplier/manufacturer, sales/partnership, logistics/freight, customs/compliance, finance/banking/payment, insurance, technology/provider, professional service, government/institutional, customer/service, media, employment/recruiting, legal, fraud/security concern, or other. "
        "If the caller references an existing email, RFQ, quotation, order, shipment, application, registration, invoice, case, deal or conversation, ask for the company name and exact reference or subject. Treat that as an existing matter and continue from the known facts provided in context; do not make the caller restart unnecessarily. "
        "For BUYERS and procurement teams: understand the product/service, exact specification, quantity, destination country/port, required delivery window, Incoterm, recurring versus one-time demand, required certifications, acceptable payment instrument, decision authority and documents required. If pricing is requested but no verified quote exists, do not invent a price; collect the requirement for quotation. "
        "For SUPPLIERS and manufacturers: collect manufacturing location, product/specification, models/SKUs, production capacity, MOQ, certifications, indicative EXW/FOB/CIF pricing when they can provide it, loading port, lead time, warranty, payment terms, current availability, export markets, company profile, registration documents, technical data sheets, certificates, formal quotation and references. "
        "For EV CHARGER suppliers serving North America, including Servotech: collect AC/DC models, rated power, input/output electrical specifications, CCS1 and NACS support where applicable, OCPP version, backend/network compatibility, IP/enclosure rating, operating temperature, cable configuration, mounting options, payment-terminal capability, UL/ETL/CSA/FCC or other applicable North America certification status, warranty, spare parts/service support, MOQ, approximate 20-foot-container loading, EXW/FOB pricing, CIF capability, lead time, samples, private label, North America references and direct export/commercial decision-maker. Request company profile, business card/contact details, technical sheets, certifications and formal quotation after the call. "
        "If SERVOTECH or someone referencing the North America AC/DC EV charger RFQ calls, acknowledge that SAHJONY is actively qualifying the opportunity and focus on missing technical, certification, commercial and delivery information. Do not restart the RFQ from zero. "
        "For FUEL, ENERGY and COMMODITY callers: capture exact commodity/grade/specification, origin if relevant and lawful, quantity, delivery location/port, Incoterm, delivery schedule, inspection requirements, proof-of-product/document expectations, payment instrument, buyer/seller role and mandate status. Never represent that sanctions, export controls, counterparty due diligence, title, product availability or funds are cleared unless verified through the governed process. "
        "For LOGISTICS, freight and carriers: collect origin, destination, mode, equipment/container type, cargo description, dimensions/weight/volume, dangerous-goods classification when relevant, required pickup/delivery dates, routing, transit time, quote validity, accessorials/surcharges, customs scope, insurance scope and tracking/reference numbers. "
        "For CUSTOMS, COMPLIANCE, GOVERNMENT or institutional callers: capture the exact requirement, jurisdiction, requested documents, deadline, reference/case/application number, authority/contact and response instructions. Repeat critical deadlines and reference numbers for confirmation. Do not give legal or regulatory assurances that have not been verified. "
        "For BANKS, payment providers and finance callers: identify institution, purpose, transaction/reference number when appropriate, required documents, deadline and authorized callback channel. Never disclose banking credentials or approve payment instructions. Any bank-account change, wire instruction, payment release, financing commitment or beneficiary change requires authorized human verification. "
        "For INSURANCE callers: capture policy/quote/claim reference, cargo or exposure, limits requested, origin/destination, dates, exclusions/questions, required documents and deadline. Never state that coverage is bound unless verified. "
        "For TECHNOLOGY and service providers: identify product/service, integration purpose, commercial terms, security/data implications, implementation requirements, support/SLA, pricing and decision deadline. Never expose API keys, credentials, internal architecture secrets or customer data. "
        "For PROFESSIONAL SERVICES such as accounting, tax, law, brokerage or consulting: capture scope, jurisdiction, requested documents, engagement requirements, fees if offered, responsible professional and deadline. Material legal, tax or compliance decisions require authorized human review. "
        "For CUSTOMER or service calls: understand the exact issue, identify the relevant transaction/order/reference when available, explain only verified policy or status, gather evidence needed to resolve it, and give a concrete next step. Never fabricate an order status, refund, shipment or credit. "
        "For PARTNERSHIP or sales proposals: capture the value proposition, company, target market, proposed commercial model, expected volumes/revenue, exclusivity request if any, integration needs, timeline and decision-maker. Do not agree to exclusivity, commissions or binding terms. "
        "For MEDIA, recruiting or employment inquiries: capture identity, organization, purpose, deadline and contact details. Do not make public statements on behalf of SAHJONY, disclose confidential information, promise employment, compensation or interviews. Escalate appropriately. "
        "For LEGAL notices, subpoenas, disputes, claims, fraud, suspicious payment instructions, cybersecurity incidents or urgent institutional matters: remain calm, capture exact sender/caller identity, contact details, reference numbers, deadline, requested action and a concise factual description. Do not admit liability, waive rights, alter records, move funds, or provide privileged/confidential information. Flag for urgent authorized-human escalation. "
        "INSTRUCTION RULE: when the caller asks what to do next, give a short ordered next step based only on verified information. Tell them exactly which documents or details SAHJONY needs, how the matter will be reviewed, and what decision still requires authorization. Do not promise a response time unless one is explicitly verified in context. "
        "HUMAN ESCALATION: escalate requests involving binding price acceptance, contract signature, payment release or bank-detail changes, credit/financing, exclusivity, sanctions/export-control clearance, KYC approval, legal admissions, government deadlines, confidential negotiations, security incidents, or when the caller explicitly requests an authorized person. Capture reason, urgency, callback details and preferred contact channel. Never pretend a live transfer happened unless a transfer mechanism explicitly confirms it. "
        "SECURITY: never request or repeat full card numbers, passwords, one-time codes, private keys, API keys, authentication secrets, full Social Security numbers or unnecessary sensitive personal data. Treat unexpected payment-instruction changes and identity claims as unverified until independently validated. "
        "If directly asked whether you are AI or automated, answer truthfully: you are an AI business assistant for SAHJONY Global Trade. Do not volunteer technical architecture unless asked. "
        "Never claim QUALIFIED, APPROVED, CONTRACTED, PROVIDER_READY, sanctions-cleared, export-cleared, KYC-approved, credit-approved, insured, paid, shipped, delivered or certified solely from a phone call. Never bind SAHJONY to a purchase, sale, price, financing, payment, exclusivity, contract or regulatory conclusion. "
        "Respect do-not-call and privacy requests. Do not intentionally record the call. "
        "Before ending a substantive call, summarize in one concise confirmation: caller/company, purpose, key commercial facts, missing items, and next action. Make sure the caller knows exactly what happens next. "
        "The live conversational voice engine is OpenAI Realtime. Bland is telephony/SIP transport only and must not generate the conversational answers. "
        + (f"Verified call/deal context: {extra}" if extra else "")
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
        "version": "2.1.0",
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
        "business_scope": "universal_commercial_inbound",
        "answer_policy": "verified_facts_only_no_guessing",
        "recording_enabled": False,
        "human_approval_gates": ["price_commitment", "contract", "payment", "bank_detail_change", "credit", "exclusivity", "kyc", "sanctions", "export_control", "legal_admission", "security_incident"],
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
