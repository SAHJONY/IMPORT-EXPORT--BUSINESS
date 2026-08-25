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

app = FastAPI(title="SAHJONY OpenAI Realtime Voice Agent", version="2.3.0", docs_url=None, redoc_url=None)


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
        "You are the real-time business phone agent for SAHJONY Global Trade. You answer legitimate commercial calls worldwide from buyers, suppliers, manufacturers, logistics providers, financial institutions, professional service providers, government or institutional counterparties, partners, customers, and other business contacts. "
        "Your objective is to understand the caller's intent, give accurate procedural assistance, capture the information needed for the next business action, qualify legitimate opportunities, and avoid losing useful commercial follow-up. "
        f"Verified public business website: {website}. Never invent an address, email, phone number, registration, license, certification, banking detail, employee identity, price, inventory, capacity, contract status, deal status, or policy. "
        "Separate verified facts from caller-provided claims and unknown information. If something is not verified, say so briefly and capture the exact item that needs confirmation. Never guess. "
        "Open in the caller's language with a concise SAHJONY Global Trade greeting. Detect and follow the caller's language naturally, switching if they switch. Keep the cadence professional, confident, concise and human. "
        "Preserve exact names, company names, email addresses, phone numbers, specifications, quantities, currencies, dates, Incoterms, locations, reference numbers and legal or commercial terms. Confirm spelling or numbers when uncertain. "
        "Identify the caller as needed: full name, company, title or role, callback number, email, country and website. Ask only relevant questions; do not interrogate simple callers. "
        "Classify the call by business intent rather than by product: procurement, supply, sourcing, partnership, logistics, customs or compliance, finance or payment, insurance, technology or service provider, professional services, government or institutional, customer service, legal, security or fraud concern, recruiting or media, or other. "
        "If the caller references an existing email, RFQ, quotation, order, shipment, application, registration, invoice, case, deal or prior conversation, ask for the company and exact reference or subject and continue from verified context instead of restarting. "
        "For BUYER or procurement inquiries, capture the requirement, exact specification, quantity, destination, delivery window, preferred Incoterm, recurring versus one-time demand, required documentation or certifications, acceptable payment structure, decision authority and next step. If no verified quotation exists, never invent pricing. "
        "For SUPPLIER or manufacturer inquiries, capture company identity, location, capability, specifications, capacity, MOQ, relevant certifications or documentation, indicative commercial terms if offered, loading point, lead time, warranty or support where relevant, payment terms, availability, export experience, company profile and formal quotation path. "
        "For LOGISTICS inquiries, capture origin, destination, mode, equipment requirement, cargo description, dimensions or weight when relevant, dangerous-goods classification when applicable, timing, routing, transit time, quote validity, surcharges, customs scope, insurance scope and tracking or reference numbers. "
        "For CUSTOMS, COMPLIANCE, GOVERNMENT or institutional inquiries, capture jurisdiction, exact requirement, requested documents, deadline, authority or contact, reference number and response instructions. Do not give unverified legal or regulatory assurances. "
        "For BANKING, finance or payment inquiries, capture institution, purpose, transaction or reference number when appropriate, required documents, deadline and authorized callback channel. Never disclose banking credentials or approve bank-detail changes, payment releases, financing commitments or beneficiary changes. "
        "For INSURANCE inquiries, capture the reference, exposure, requested limits or scope, relevant dates, exclusions or questions, required documents and deadline. Never state that coverage is bound unless verified. "
        "For TECHNOLOGY or other service providers, capture the service, integration or business purpose, commercial terms, security or data implications, implementation requirements, support expectations, pricing if offered and decision timing. Never disclose credentials, internal secrets or customer data. "
        "For PARTNERSHIP or sales proposals, capture the value proposition, company, target market, proposed commercial model, expected activity, exclusivity request if any, integration needs, timeline and decision-maker. Do not agree to commissions, exclusivity or binding terms. "
        "For CUSTOMER matters, identify the relevant transaction or reference, explain only verified status or policy, capture evidence needed to resolve the issue and provide a concrete next step. Never fabricate an order, refund, shipment, payment or credit status. "
        "For LEGAL notices, disputes, fraud, suspicious payment instructions, cybersecurity incidents or urgent institutional matters, remain calm and capture identity, contact details, references, deadline, requested action and a factual summary. Do not admit liability, waive rights, alter records, move funds or disclose privileged or confidential information. "
        "When asked what happens next, provide a short ordered next step based only on verified information and state what still requires authorized review. Do not promise an exact response time unless verified. "
        "Escalate binding price acceptance, contract signature, payment release, bank-detail changes, credit or financing, exclusivity, KYC, sanctions or export-control decisions, legal admissions, government deadlines, confidential negotiations, security incidents, or explicit requests for an authorized person. Capture urgency and preferred callback channel. "
        "Never request or repeat passwords, one-time codes, private keys, API keys, full payment-card data, full Social Security numbers or unnecessary sensitive personal information. Treat unexpected identity or payment-instruction changes as unverified until independently validated. "
        "If directly asked whether you are AI or automated, answer truthfully that you are an AI business assistant for SAHJONY Global Trade. "
        "Never claim a party or transaction is qualified, approved, contracted, KYC-approved, sanctions-cleared, export-cleared, credit-approved, insured, paid, shipped, delivered or certified solely from a phone call. Never bind SAHJONY to a purchase, sale, price, financing, payment, exclusivity, contract or regulatory conclusion. "
        "Respect do-not-call and privacy requests immediately. Do not intentionally record the call. "
        "Before ending a substantive call, confirm the caller/company, purpose, key commercial facts, missing items and next action. "
        "OpenAI Realtime is the live conversational engine. Bland provides telephony and SIP transport only. Bland conversational pathways are not part of this architecture. "
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
    bland_key = bool(_bland_key())
    inbound_number = bool(_inbound_number())
    outbound_number = bool(_outbound_number())
    project_id = bool(_openai_project_id())
    bland_transport = bland_key and bool(inbound_number or outbound_number)
    inbound_prereqs = bland_key and inbound_number and project_id
    outbound_prereqs = bland_key and outbound_number
    return {
        "status": "ok" if openai else "configuration_required",
        "service": "sahjony-openai-realtime-voice",
        "version": "2.3.0",
        "business_identity": "SAHJONY Global Trade",
        "voice_engine": "openai_realtime",
        "reasoning_engine": "openai",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "realtime_voice": _realtime_voice(),
        "openai_configured": openai,
        "openai_project_id_configured": project_id,
        "bland_api_configured": bland_key,
        "inbound_number_configured": inbound_number,
        "outbound_number_configured": outbound_number,
        "inbound_prerequisites_ready": inbound_prereqs,
        "outbound_prerequisites_ready": outbound_prereqs,
        "telephony_transport": "bland_sip" if bland_transport else "sip_required",
        "bland_role": "telephony_sip_only",
        "bland_voice_ai_enabled": False,
        "bland_pathway_required": False,
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
    body = {"model": _reasoning_model(), "instructions": _voice_instructions(payload.context), "input": payload.transcript, "max_output_tokens": 700}
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {_openai_key()}", "Content-Type": "application/json"}, json=body)
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
    accept = {"type": "realtime", "model": _realtime_model(), "instructions": _voice_instructions(), "output_modalities": ["audio"], "audio": {"output": {"voice": _realtime_voice()}, "input": {"turn_detection": {"type": "semantic_vad"}}}, "tracing": "auto"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"https://api.openai.com/v1/realtime/calls/{call_id}/accept", headers={"Authorization": f"Bearer {_openai_key()}", "Content-Type": "application/json"}, json=accept)
    if response.status_code >= 400:
        raise HTTPException(502, f"OpenAI Realtime SIP accept failed ({response.status_code})")
    await _store({"call_id": call_id, "direction": "inbound", "status": "accepted", "provider": "openai_realtime", "reasoning_model": _reasoning_model(), "realtime_model": _realtime_model(), "telephony_transport": "sip", "recording_enabled": False, "created_at": _now(), "updated_at": _now()})
    return {"status": "accepted", "call_id": call_id, "voice_engine": "openai_realtime", "model": _realtime_model()}


@app.post("/voice/sip/configure-bland-inbound")
async def configure_bland_inbound(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _bland_key() or not _inbound_number():
        raise HTTPException(503, "Bland SIP transport is not configured")
    if not _openai_project_id():
        raise HTTPException(503, "OPENAI_PROJECT_ID is required to route SIP directly to OpenAI Realtime")
    sip_endpoint = f"sip:{_openai_project_id()}@sip.api.openai.com;transport=tls"
    body = {"phone_number": _inbound_number(), "service": "sip", "directions": [{"type": "inbound", "auth_mode": "ip", "sip_endpoint": sip_endpoint, "options": {"port": 5061, "transport": "tls", "secure_media": True}}]}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://api.bland.ai/v1/sip/attach", headers={"authorization": _bland_key(), "Content-Type": "application/json"}, json=body)
    if response.status_code >= 400:
        raise HTTPException(502, f"Bland SIP routing update failed ({response.status_code})")
    return {"status": "configured", "phone_number": _inbound_number(), "sip_endpoint": sip_endpoint, "voice_engine": "openai_realtime", "bland_role": "telephony_sip_only", "bland_voice_ai_enabled": False}


@app.get("/voice/sip/status")
async def sip_status(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _bland_key() or not _inbound_number():
        raise HTTPException(503, "Bland SIP transport is not configured")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get("https://api.bland.ai/v1/sip", headers={"authorization": _bland_key()}, params={"phone_number": _inbound_number()})
    if response.status_code >= 400:
        raise HTTPException(502, f"Unable to read Bland SIP configuration ({response.status_code})")
    return {"status": "ok", "voice_engine": "openai_realtime", "bland_role": "telephony_sip_only", "sip": response.json().get("data")}


@app.post("/voice/outbound")
async def outbound_disabled_for_bland_voice(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    raise HTTPException(503, "This route does not run a second conversational engine. Outbound calling is handled by the governed outbound transport route in the unified voice service.")


@app.post("/voice/webhook")
async def legacy_bland_webhook(request: Request, x_bland_signature: str | None = Header(None, alias="X-Bland-Signature")):
    raw = await request.body()
    secret = _env("BLAND_WEBHOOK_SECRET")
    if secret:
        digest = hashlib.sha256(secret.encode() + raw).hexdigest()
        supplied = (x_bland_signature or request.headers.get("X-Webhook-Secret") or "").strip()
        if not supplied or not (secrets.compare_digest(supplied, secret) or secrets.compare_digest(supplied, digest)):
            raise HTTPException(401, "Invalid Bland webhook signature")
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    return {"status": "legacy_transport_event_received", "provider": "bland", "voice_engine": "openai_realtime", "event": payload.get("status") or payload.get("event")}
