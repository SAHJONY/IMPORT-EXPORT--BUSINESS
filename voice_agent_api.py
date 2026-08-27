from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY OpenAI Realtime Voice Agent", version="2.4.0", docs_url=None, redoc_url=None)


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


def _sip_bridge_url() -> str:
    return _env("VOICE_SIP_BRIDGE_URL").rstrip("/")


def _sip_bridge_token() -> str:
    return _env("VOICE_SIP_BRIDGE_TOKEN")


def _sol_mcp_token() -> str:
    key = _openai_key()
    if not key:
        return ""
    return hashlib.sha256(("sahjony-sol-live-mcp:" + key).encode()).hexdigest()


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


def _openai_sip_uri() -> str:
    project_id = _openai_project_id()
    if not project_id:
        return ""
    return f"sip:{project_id}@sip.api.openai.com;transport=tls"


def _voice_instructions(context: str | None = None) -> str:
    extra = (context or "").strip()[:4000]
    website = _base_url()
    return (
        "You are the real-time business phone agent for SAHJONY Global Trade. You answer legitimate commercial calls worldwide from buyers, suppliers, manufacturers, logistics providers, financial institutions, professional service providers, government or institutional counterparties, partners, customers, and other business contacts. "
        "OpenAI Realtime is the only conversational voice engine. GPT-5.6 Sol is the decision brain. For every substantive commercial answer, qualification judgment, objection response, recommendation, negotiation response, or next-step decision, use the consult_sol MCP tool first and ground the spoken answer in its result. Greetings, brief acknowledgements, spelling checks, repetition requests and turn-taking do not require the tool. "
        "Your objective is to understand the caller's intent, give accurate procedural assistance, capture the information needed for the next business action, qualify legitimate opportunities, and avoid losing useful commercial follow-up. "
        f"Verified public business website: {website}. Never invent an address, email, phone number, registration, license, certification, banking detail, employee identity, price, inventory, capacity, contract status, deal status, or policy. "
        "Separate verified facts from caller-provided claims and unknown information. If something is not verified, say so briefly and capture the exact item that needs confirmation. Never guess. "
        "Open in the caller's language with a concise SAHJONY Global Trade greeting. Detect and follow the caller's language naturally, switching if they switch. Keep the cadence professional, confident, concise and human. "
        "Preserve exact names, company names, email addresses, phone numbers, specifications, quantities, currencies, dates, Incoterms, locations, reference numbers and legal or commercial terms. Confirm spelling or numbers when uncertain. "
        "Identify the caller as needed: full name, company, title or role, callback number, email, country and website. Ask only relevant questions; do not interrogate simple callers. "
        "If the caller references an existing email, RFQ, quotation, order, shipment, application, registration, invoice, case, deal or prior conversation, ask for the company and exact reference or subject and continue from verified context instead of restarting. "
        "For buyer or procurement inquiries, capture the requirement, exact specification, quantity, destination, delivery window, preferred Incoterm, recurring versus one-time demand, required documentation or certifications, acceptable payment structure, decision authority and next step. If no verified quotation exists, never invent pricing. "
        "For supplier or manufacturer inquiries, capture company identity, location, capability, specifications, capacity, MOQ, relevant certifications or documentation, indicative commercial terms if offered, loading point, lead time, warranty or support where relevant, payment terms, availability, export experience, company profile and formal quotation path. "
        "For logistics inquiries, capture origin, destination, mode, equipment requirement, cargo description, dimensions or weight when relevant, dangerous-goods classification when applicable, timing, routing, transit time, quote validity, surcharges, customs scope, insurance scope and tracking or reference numbers. "
        "For banking, finance or payment inquiries, capture institution, purpose, transaction or reference number when appropriate, required documents, deadline and authorized callback channel. Never disclose banking credentials or approve bank-detail changes, payment releases, financing commitments or beneficiary changes. "
        "For legal notices, disputes, fraud, suspicious payment instructions, cybersecurity incidents or urgent institutional matters, remain calm and capture identity, contact details, references, deadline, requested action and a factual summary. Do not admit liability, waive rights, alter records, move funds or disclose privileged or confidential information. "
        "Escalate binding price acceptance, contract signature, payment release, bank-detail changes, credit or financing, exclusivity, KYC, sanctions or export-control decisions, legal admissions, government deadlines, confidential negotiations, security incidents, or explicit requests for an authorized person. Capture urgency and preferred callback channel. "
        "Never request or repeat passwords, one-time codes, private keys, API keys, full payment-card data, full Social Security numbers or unnecessary sensitive personal information. Treat unexpected identity or payment-instruction changes as unverified until independently validated. "
        "If directly asked whether you are AI or automated, answer truthfully that you are an AI business assistant for SAHJONY Global Trade. "
        "Never claim a party or transaction is qualified, approved, contracted, KYC-approved, sanctions-cleared, export-cleared, credit-approved, insured, paid, shipped, delivered or certified solely from a phone call. Never bind SAHJONY to a purchase, sale, price, financing, payment, exclusivity, contract or regulatory conclusion. "
        "Respect do-not-call and privacy requests immediately. Do not intentionally record the call. Before ending a substantive call, confirm the caller/company, purpose, key commercial facts, missing items and next action. "
        "Bland provides telephony/SIP transport only. Bland conversational pathways, Bland language models and Bland speech generation are not part of this architecture. "
        + (f"Verified call/deal context: {extra}" if extra else "")
    )


def _realtime_mcp_tool() -> dict[str, Any]:
    return {
        "type": "mcp",
        "server_label": "sahjony_sol_brain",
        "server_description": "GPT-5.6 Sol decision brain for SAHJONY live business calls.",
        "server_url": f"{_base_url().rstrip('/')}/voice/mcp/sol",
        "headers": {"Authorization": f"Bearer {_sol_mcp_token()}"},
        "allowed_tools": ["consult_sol"],
        "require_approval": "never",
    }


def _realtime_session(context: str | None = None) -> dict[str, Any]:
    return {
        "type": "realtime",
        "model": _realtime_model(),
        "instructions": _voice_instructions(context),
        "output_modalities": ["audio"],
        "audio": {
            "output": {"voice": _realtime_voice()},
            "input": {"turn_detection": {"type": "semantic_vad"}},
        },
        "tools": [_realtime_mcp_tool()],
        "tool_choice": "auto",
        "tracing": "auto",
    }


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


async def _consult_sol(arguments: dict[str, Any]) -> str:
    if not _openai_key():
        raise RuntimeError("OpenAI is not configured")
    latest = str(arguments.get("latest_utterance") or arguments.get("caller_message") or "").strip()[:8000]
    summary = str(arguments.get("conversation_summary") or "").strip()[:12000]
    context = str(arguments.get("context") or "").strip()[:6000]
    language = str(arguments.get("language") or "auto").strip()[:40]
    instructions = (
        "You are GPT-5.6 Sol, the decision brain for SAHJONY Global Trade's live phone agent. "
        "Return only the exact concise spoken content the OpenAI Realtime voice should say next. Use the caller's language. "
        "Be commercially sharp and natural. Preserve exact facts and clearly distinguish verified facts, caller claims and unknowns. "
        "Never fabricate pricing, authority, verification, inventory, payment status, compliance status or deal status. "
        "Never bind SAHJONY to pricing, contracts, payments, financing, exclusivity, KYC, sanctions, export control, legal admissions or other regulated/binding decisions."
    )
    prompt = f"Language: {language}\nVerified context: {context}\nConversation summary: {summary}\nCaller just said: {latest}"
    body = {
        "model": _reasoning_model(),
        "instructions": instructions,
        "input": prompt,
        "max_output_tokens": 320,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {_openai_key()}", "Content-Type": "application/json"},
            json=body,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Sol reasoning failed ({response.status_code})")
    reply = _extract_response_text(response.json())
    if not reply:
        raise RuntimeError("Sol returned no spoken reply")
    return reply


@app.api_route("/voice/mcp/sol", methods=["GET", "POST"])
async def sol_mcp(request: Request):
    authorization = request.headers.get("Authorization", "")
    expected = _sol_mcp_token()
    supplied = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if not expected or not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid Sol MCP credential")
    if request.method == "GET":
        return {"status": "ok", "server": "sahjony-sol-brain", "tool": "consult_sol", "model": _reasoning_model()}
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid MCP JSON-RPC payload")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid MCP JSON-RPC payload")
    method = str(payload.get("method") or "")
    request_id = payload.get("id")
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        result = {
            "protocolVersion": str((payload.get("params") or {}).get("protocolVersion") or "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sahjony-sol-brain", "version": "1.0.0"},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {
            "tools": [{
                "name": "consult_sol",
                "description": "Use GPT-5.6 Sol to decide the exact grounded spoken answer for a substantive SAHJONY business call turn.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "latest_utterance": {"type": "string"},
                        "conversation_summary": {"type": "string"},
                        "context": {"type": "string"},
                        "language": {"type": "string"},
                    },
                    "required": ["latest_utterance"],
                },
                "annotations": {"readOnlyHint": True},
            }]
        }
    elif method == "tools/call":
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        if str(params.get("name") or "") != "consult_sol":
            result = {"content": [{"type": "text", "text": "Unknown tool"}], "isError": True}
        else:
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            try:
                reply = await _consult_sol(arguments)
                result = {"content": [{"type": "text", "text": reply}], "isError": False}
            except Exception as exc:
                result = {"content": [{"type": "text", "text": f"Sol unavailable: {type(exc).__name__}"}], "isError": True}
    else:
        return JSONResponse(status_code=200, content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}})
    return JSONResponse(content={"jsonrpc": "2.0", "id": request_id, "result": result})


@app.get("/voice/health")
async def health() -> dict[str, Any]:
    openai = bool(_openai_key())
    bland_key = bool(_bland_key())
    inbound_number = bool(_inbound_number())
    outbound_number = bool(_outbound_number())
    project_id = bool(_openai_project_id())
    bridge = bool(_sip_bridge_url() and _sip_bridge_token())
    bland_transport = bland_key and bool(inbound_number or outbound_number)
    inbound_prereqs = bool(openai and bland_key and inbound_number and project_id)
    outbound_prereqs = bool(openai and bland_key and outbound_number and project_id and bridge)
    return {
        "status": "ok" if openai else "configuration_required",
        "service": "sahjony-openai-realtime-voice",
        "version": "2.4.0",
        "business_identity": "SAHJONY Global Trade",
        "voice_engine": "openai_realtime",
        "reasoning_engine": "openai",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "realtime_voice": _realtime_voice(),
        "sol_live_mcp_enabled": openai,
        "openai_configured": openai,
        "openai_project_id_configured": project_id,
        "bland_api_configured": bland_key,
        "inbound_number_configured": inbound_number,
        "outbound_number_configured": outbound_number,
        "sip_bridge_configured": bridge,
        "inbound_prerequisites_ready": inbound_prereqs,
        "outbound_prerequisites_ready": outbound_prereqs,
        "outbound_blocker": None if outbound_prereqs else "SIP_B2BUA_BRIDGE_REQUIRED",
        "telephony_transport": "bland_sip" if bland_transport else "sip_required",
        "outbound_transport": "sip_b2bua_bridge" if bridge else "bridge_required",
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
    return {"status": "ok", "model": _reasoning_model(), "output_text": _extract_response_text(response.json()), "response_id": response.json().get("id")}


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
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"https://api.openai.com/v1/realtime/calls/{call_id}/accept",
            headers={"Authorization": f"Bearer {_openai_key()}", "Content-Type": "application/json"},
            json=_realtime_session(),
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
        "sol_live_mcp_enabled": True,
        "telephony_transport": "sip",
        "recording_enabled": False,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return {"status": "accepted", "call_id": call_id, "voice_engine": "openai_realtime", "reasoning_model": _reasoning_model(), "model": _realtime_model()}


@app.post("/voice/sip/configure-bland-inbound")
async def configure_bland_inbound(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _bland_key() or not _inbound_number():
        raise HTTPException(503, "Bland SIP transport is not configured")
    if not _openai_project_id():
        raise HTTPException(503, "OPENAI_PROJECT_ID is required to route SIP directly to OpenAI Realtime")
    body = {
        "phone_number": _normalize_phone(_inbound_number()),
        "service": "sip",
        "directions": [{
            "type": "inbound",
            "auth_mode": "ip",
            "sip_endpoint": _openai_sip_uri(),
            "options": {"port": 5061, "transport": "tls", "secure_media": True},
        }],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://api.bland.ai/v1/sip/attach", headers={"authorization": _bland_key(), "Content-Type": "application/json"}, json=body)
    if response.status_code >= 400:
        message = response.text[:600]
        raise HTTPException(502, f"Bland SIP routing update failed ({response.status_code}): {message}")
    return {"status": "configured", "phone_number": _normalize_phone(_inbound_number()), "sip_endpoint": _openai_sip_uri(), "voice_engine": "openai_realtime", "bland_role": "telephony_sip_only", "bland_voice_ai_enabled": False}


@app.get("/voice/sip/status")
async def sip_status(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _bland_key() or not _inbound_number():
        raise HTTPException(503, "Bland SIP transport is not configured")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get("https://api.bland.ai/v1/sip", headers={"authorization": _bland_key()}, params={"phone_number": _normalize_phone(_inbound_number())})
    if response.status_code >= 400:
        raise HTTPException(502, f"Unable to read Bland SIP configuration ({response.status_code})")
    return {"status": "ok", "voice_engine": "openai_realtime", "bland_role": "telephony_sip_only", "sip": response.json().get("data")}


class OutboundCall(BaseModel):
    phone_number: str = Field(min_length=7, max_length=32)
    contact_name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=240)
    context: str | None = Field(default=None, max_length=4000)
    lead_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    language: str = Field(default="auto", max_length=35)


@app.get("/voice/outbound/bridge-status")
async def outbound_bridge_status(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not _sip_bridge_url() or not _sip_bridge_token():
        return {"status": "configuration_required", "bridge_configured": False, "code": "SIP_B2BUA_BRIDGE_REQUIRED", "fail_closed": True}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{_sip_bridge_url()}/health", headers={"Authorization": f"Bearer {_sip_bridge_token()}"})
        return {"status": "ok" if response.status_code < 400 else "degraded", "bridge_configured": True, "bridge_reachable": response.status_code < 400, "http_status": response.status_code, "fail_closed": True}
    except Exception as exc:
        return {"status": "degraded", "bridge_configured": True, "bridge_reachable": False, "error": type(exc).__name__, "fail_closed": True}


@app.post("/voice/outbound")
async def outbound(payload: OutboundCall, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    missing: list[str] = []
    for name, value in (
        ("OPENAI_API_KEY", _openai_key()),
        ("OPENAI_PROJECT_ID", _openai_project_id()),
        ("BLAND_API_KEY", _bland_key()),
        ("BLAND_OUTBOUND_NUMBER", _outbound_number()),
        ("VOICE_SIP_BRIDGE_URL", _sip_bridge_url()),
        ("VOICE_SIP_BRIDGE_TOKEN", _sip_bridge_token()),
    ):
        if not value:
            missing.append(name)
    if missing:
        raise HTTPException(503, {"code": "SIP_B2BUA_BRIDGE_REQUIRED", "missing": missing, "message": "Outbound remains fail-closed until a SIP B2BUA bridges the Bland PSTN leg to OpenAI Realtime. Bland Voice AI will not be used."})
    to_number = _normalize_phone(payload.phone_number)
    from_number = _normalize_phone(_outbound_number())
    bridge_payload = {
        "to": to_number,
        "from": from_number,
        "openai_sip_uri": _openai_sip_uri(),
        "openai_realtime_model": _realtime_model(),
        "openai_voice": _realtime_voice(),
        "reasoning_model": _reasoning_model(),
        "context": (payload.context or "")[:4000],
        "language": payload.language,
        "recording_enabled": False,
        "transport_provider": "bland_sip",
        "voice_engine": "openai_realtime",
        "metadata": {
            "contact_name": payload.contact_name,
            "company": payload.company,
            "lead_id": payload.lead_id,
            "trade_case_id": payload.trade_case_id,
            "source": "sahjony_global_trade_os",
        },
        "callback_url": f"{_base_url().rstrip('/')}/voice/webhook",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{_sip_bridge_url()}/v1/calls",
            headers={"Authorization": f"Bearer {_sip_bridge_token()}", "Content-Type": "application/json"},
            json=bridge_payload,
        )
    if response.status_code >= 400:
        raise HTTPException(502, f"SIP bridge rejected outbound call ({response.status_code})")
    try:
        data = response.json()
    except Exception:
        data = {}
    call_id = str(data.get("call_id") or data.get("id") or f"call_{secrets.token_urlsafe(12)}")
    await _store({
        "call_id": call_id,
        "direction": "outbound",
        "phone_number": to_number,
        "contact_name": payload.contact_name,
        "company": payload.company,
        "lead_id": payload.lead_id,
        "trade_case_id": payload.trade_case_id,
        "status": "queued",
        "provider": "bland_sip",
        "voice_engine": "openai_realtime",
        "reasoning_model": _reasoning_model(),
        "realtime_model": _realtime_model(),
        "recording_enabled": False,
        "created_at": _now(),
        "updated_at": _now(),
    })
    return {"status": "queued", "call_id": call_id, "provider": "bland_sip", "voice_engine": "openai_realtime", "reasoning_model": _reasoning_model(), "realtime_model": _realtime_model(), "recording_enabled": False}


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
        event = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(400, "Invalid JSON payload")
    return {"status": "transport_event_received", "provider": "bland_sip", "voice_engine": "openai_realtime", "event": event.get("status") or event.get("event")}
