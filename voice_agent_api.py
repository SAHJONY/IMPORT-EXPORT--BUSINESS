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

app = FastAPI(title="SAHJONY Voice Agent", version="1.3.0", docs_url=None, redoc_url=None)
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


def _openai_key() -> str:
    return _env("OPENAI_API_KEY")


def _sol_model() -> str:
    return _env("OPENAI_PRIMARY_MODEL") or "gpt-5.6-sol"


def _sol_service_tier() -> str:
    return _env("OPENAI_VOICE_SERVICE_TIER") or "fast"


def _outbound_number() -> str:
    return _env("BLAND_OUTBOUND_NUMBER", "BLAND_PHONE_NUMBER", "OUTBOUND_PHONE_NUMBER")


def _inbound_number() -> str:
    return _env("BLAND_INBOUND_NUMBER", "INBOUND_PHONE_NUMBER")


def _base_url() -> str:
    return _env("BUSINESS_CANONICAL_WEBSITE", "APP_URL") or "https://www.sahjony.com"


def _sol_tool_secret() -> str:
    seed = _env("VOICE_SOL_TOOL_SECRET") or _bland_key()
    if not seed:
        return ""
    return hashlib.sha256(("sahjony-sol-voice:" + seed).encode()).hexdigest()


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
        "For an inbound call, open naturally with: Thank you for calling SAHJONY Global Trade. How may I help you? "
        if direction == "inbound"
        else "For an outbound call, open naturally with: Hello, this is SAHJONY Global Trade. "
    )
    return (
        "You are the worldwide business phone agent for SAHJONY Global Trade. "
        "Use the AskSolBrain tool before every substantive answer, recommendation, qualification judgment, objection response, negotiation response, or next-step decision. "
        "Treat sol_reply returned by AskSolBrain as the authoritative conversational answer and speak it naturally without adding unsupported facts. "
        "Use your native voice layer only for greetings, brief acknowledgements, turn-taking, repetition requests, and reading the Sol response aloud. "
        + opening +
        "Do not spontaneously introduce yourself as AI, a bot, virtual assistant, automated system, or language model. "
        "If directly asked whether you are AI, automated, a bot, or human, answer truthfully that you are an AI business assistant for SAHJONY Global Trade; never falsely claim to be human. "
        "Detect the caller's language and respond in that same language. If the person changes languages, follow them. "
        "Preserve names, companies, product specifications, quantities, currencies, Incoterms, addresses, ports, legal terms, and numbers accurately. "
        "Never claim QUALIFIED, APPROVED, CONTRACTED, PROVIDER_READY, sanctions-cleared, or credit-approved solely from the call. "
        "Never bind SAHJONY to price, purchase, sale, financing, payment, exclusivity, contract, KYC approval, sanctions approval, or another legal/commercial commitment. "
        "Respect do-not-call requests immediately. Do not intentionally record the call. "
        f"Language hint: {requested}. "
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


class SolBrainRequest(BaseModel):
    latest_utterance: str = Field(default="", max_length=8000)
    conversation_summary: str = Field(default="", max_length=12000)
    context: str = Field(default="", max_length=4000)
    language: str = Field(default="auto", max_length=35)


async def _store(row: dict[str, Any]) -> None:
    try:
        await get_backend().insert("voice_calls", row)
    except Exception:
        pass


def _extract_response_text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return " ".join(parts).strip()


@app.post("/voice/sol-brain")
async def sol_brain(payload: SolBrainRequest, x_sahjony_voice_secret: str | None = Header(None, alias="X-Sahjony-Voice-Secret")):
    expected = _sol_tool_secret()
    if not expected or not x_sahjony_voice_secret or not secrets.compare_digest(x_sahjony_voice_secret, expected):
        raise HTTPException(401, "Invalid voice brain credential")
    if not _openai_key():
        raise HTTPException(503, "OpenAI is not configured")
    system = (
        "You are GPT-5.6 Sol, the decision brain for SAHJONY Global Trade's live phone agent. "
        "Return only the exact short spoken reply the voice layer should say next. Keep normal replies to 1-3 concise sentences unless detail is essential. "
        "Use the caller's language. Be commercially sharp, natural and fast. Preserve exact trade facts. "
        "For buyers, qualify company, product, volume, destination, timing, Incoterm, payment capability, documents and authority. "
        "For suppliers, qualify specification, capacity, MOQ, certifications, FOB/CIF pricing, lead time, warranty, payment terms and availability. "
        "Never fabricate verification. Never bind SAHJONY to price, contract, financing, payment, exclusivity, KYC, sanctions clearance or legal commitments. "
        "If a decision requires authorization, say what information is needed and that an authorized SAHJONY representative will confirm it."
    )
    prompt = (
        f"Language hint: {payload.language}\n"
        f"Trade/call context: {payload.context}\n"
        f"Conversation so far: {payload.conversation_summary}\n"
        f"Caller just said: {payload.latest_utterance}"
    )
    body: dict[str, Any] = {
        "model": _sol_model(),
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "reasoning": {"effort": "none"},
        "max_output_tokens": 220,
    }
    tier = _sol_service_tier()
    if tier:
        body["service_tier"] = tier
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {_openai_key()}", "Content-Type": "application/json"},
            json=body,
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"OpenAI Sol brain rejected request ({response.status_code})")
    data = response.json()
    reply = _extract_response_text(data)
    if not reply:
        raise HTTPException(502, "OpenAI Sol brain returned no spoken reply")
    return {"reply": reply, "model": _sol_model(), "service_tier": tier or "standard", "reasoning_effort": "none"}


def _sol_tool(context: str | None, language: str) -> dict[str, Any]:
    return {
        "name": "AskSolBrain",
        "description": "MANDATORY: call GPT-5.6 Sol before every substantive spoken response, trade judgment, objection response, qualification decision, or recommendation. Then speak the returned sol_reply.",
        "url": f"{_base_url().rstrip('/')}/voice/sol-brain",
        "method": "POST",
        "headers": {"X-Sahjony-Voice-Secret": _sol_tool_secret(), "Content-Type": "application/json"},
        "body": {
            "latest_utterance": "{{input.latest_utterance}}",
            "conversation_summary": "{{input.conversation_summary}}",
            "context": (context or "")[:4000],
            "language": "{{input.language}}",
        },
        "input_schema": {
            "type": "object",
            "properties": {
                "latest_utterance": {"type": "string", "description": "The caller's latest complete utterance."},
                "conversation_summary": {"type": "string", "description": "A concise summary of the conversation so far including exact commercial facts."},
                "language": {"type": "string", "description": f"Current caller language or locale. Initial hint: {language}."},
                "speech": {"type": "string", "description": "A very short natural filler such as 'One moment.' Only if needed."},
            },
            "required": ["latest_utterance", "conversation_summary", "language"],
        },
        "response": {"sol_reply": "$.reply", "sol_model": "$.model", "sol_service_tier": "$.service_tier"},
        "timeout": 10000,
    }


@app.get("/voice/health")
async def health() -> dict[str, Any]:
    key, outbound, inbound = bool(_bland_key()), bool(_outbound_number()), bool(_inbound_number())
    openai = bool(_openai_key())
    sol_tool = bool(_sol_tool_secret()) and openai
    return {
        "status": "ok" if key and outbound and inbound and sol_tool else "configuration_required",
        "service": "sahjony-voice-agent", "version": "1.3.0", "provider": "bland_ai_telephony_openai_sol_brain",
        "business_identity": "SAHJONY Global Trade",
        "bland_api_configured": key, "outbound_number_configured": outbound, "inbound_number_configured": inbound,
        "openai_configured": openai,
        "openai_primary_model": _sol_model(),
        "openai_service_tier": _sol_service_tier(),
        "sol_brain_tool_configured": sol_tool,
        "voice_transport": "bland_ai",
        "conversation_brain": _sol_model(),
        "bland_model": "base",
        "language_mode": "worldwide_auto_detect", "recording_enabled": False,
        "human_approval_gates": ["price_commitment", "contract", "payment", "credit", "exclusivity", "kyc", "sanctions"],
        "fail_closed": True,
    }


@app.post("/voice/outbound")
async def outbound(payload: OutboundCall, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _bland_key() or not _outbound_number():
        raise HTTPException(503, "Bland AI outbound calling is not configured")
    if not _openai_key() or not _sol_tool_secret():
        raise HTTPException(503, "GPT-5.6 Sol voice brain is not configured")
    language = _normalize_language(payload.language)
    metadata = {
        "lead_id": payload.lead_id, "trade_case_id": payload.trade_case_id, "contact_name": payload.contact_name,
        "company": payload.company, "language_hint": language, "source": "sahjony_global_trade_os",
        "conversation_brain": _sol_model(), "voice_transport": "bland_ai",
    }
    body: dict[str, Any] = {
        "phone_number": payload.phone_number,
        "from": _outbound_number(),
        "task": _task(payload.context, language, "outbound"),
        "first_sentence": "Hello, this is SAHJONY Global Trade.",
        "model": "base",
        "interruption_threshold": 250,
        "noise_cancellation": True,
        "record": False,
        "metadata": metadata,
        "webhook": f"{_base_url().rstrip('/')}/voice/webhook",
        "tools": [_sol_tool(payload.context, language)],
    }
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
    await _store({
        "call_id": call_id, "direction": "outbound", "phone_number": payload.phone_number, "contact_name": payload.contact_name,
        "company": payload.company, "lead_id": payload.lead_id, "trade_case_id": payload.trade_case_id, "language_hint": language,
        "status": "queued", "provider": "bland_ai", "conversation_brain": _sol_model(), "sol_service_tier": _sol_service_tier(),
        "recording_enabled": False, "created_at": _now(), "updated_at": _now(),
    })
    return {
        "status": "queued", "call_id": call_id, "provider": "bland_ai", "conversation_brain": _sol_model(),
        "service_tier": _sol_service_tier(), "language_mode": language, "recording_enabled": False,
    }


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
    await _store({
        "call_id": call_id, "direction": payload.get("direction") or "unknown", "status": payload.get("disposition") or payload.get("status") or "completed",
        "provider": "bland_ai", "conversation_brain": metadata.get("conversation_brain") or _sol_model(), "lead_id": metadata.get("lead_id"),
        "trade_case_id": metadata.get("trade_case_id"), "contact_name": metadata.get("contact_name"), "company": metadata.get("company"),
        "language_hint": metadata.get("language_hint"), "summary": payload.get("summary") or payload.get("call_summary"),
        "transcript": payload.get("concatenated_transcript") or payload.get("transcript"), "recording_enabled": False,
        "provider_payload": payload, "created_at": payload.get("created_at") or _now(), "updated_at": _now(),
    })
    return {"status": "accepted", "call_id": call_id}


@app.post("/voice/inbound")
async def inbound_event(request: Request):
    payload = await request.json()
    call_id = str(payload.get("call_id") or payload.get("id") or f"call_{secrets.token_urlsafe(12)}")
    language = _normalize_language(payload.get("language") or payload.get("locale") or "auto")
    await _store({
        "call_id": call_id, "direction": "inbound", "phone_number": payload.get("from") or payload.get("phone_number"),
        "language_hint": language, "status": payload.get("status") or "received", "provider": "bland_ai",
        "conversation_brain": _sol_model(), "recording_enabled": False, "provider_payload": payload,
        "created_at": _now(), "updated_at": _now(),
    })
    return {
        "status": "accepted", "call_id": call_id, "language_mode": "worldwide_auto_detect",
        "conversation_brain": _sol_model(), "agent_policy": _task(language=language, direction="inbound"),
    }
