from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend
from voice_inbound_api import app as voice_inbound_app

app = FastAPI(title="SAHJONY Bland Outbound Transport", version="1.1.0", docs_url=None, redoc_url=None)

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
QUALIFIED_TAGS = {"QUALIFIED_LEAD", "INTERESTED", "COMPLETED_ACTION"}
FOLLOW_UP_TAGS = {"FOLLOW_UP_REQUIRED", "CALL_BACK_SCHEDULED", "NEEDS_MORE_INFO", "OBJECTION_RAISED"}
STOP_TAGS = {"DO_NOT_CONTACT"}
NONQUALIFIED_TAGS = {"NOT_QUALIFIED", "NOT_INTERESTED", "NO_CONTACT_MADE", "NO_ANSWER", "BUSY", "CANCELED", "FAILED"}


def _env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        "You are the outbound business phone agent for SAHJONY Global Trade. "
        "Open naturally and identify SAHJONY Global Trade. Detect the person's language and respond naturally in that language. "
        f"Initial language hint: {language_hint}. "
        "Your commercial objective is to determine whether this contact is a useful buyer, supplier, partner, service provider, or follow-up opportunity and collect enough factual information for SAHJONY's CRM. "
        "When appropriate, confirm the person's full name, company/legal business name, role, business email, country, product or service, buyer/seller role, exact specifications, quantity or capacity, destination, timing, Incoterm preference, payment/document readiness, decision authority, and next step. Ask only what is relevant and do not turn a simple call into an interrogation. "
        "For buyers, focus on product, specification, quantity, destination, timing, Incoterm, payment capability, documentation readiness and decision authority. "
        "For suppliers, focus on product specification, capacity, MOQ, certifications, indicative EXW/FOB/CIF pricing, loading point, lead time, payment terms and availability. "
        "The post-call system may autonomously create or update a CRM prospect from facts actually provided during this call. Never invent an email, company, country, product, quantity, destination or qualification fact to make a CRM record complete. "
        "A commercial lead may be marked qualified only when the conversation provides meaningful evidence of fit, need/capability and a viable next step. This is not KYC approval, credit approval, sanctions clearance, supplier approval, contracting, or transaction approval. "
        "Preserve exact names, companies, emails, product specifications, quantities, currencies, Incoterms, ports, legal terms and numbers. Confirm spelling when uncertain. "
        "Never claim a party is approved, contracted, provider-ready, sanctions-cleared, export-cleared, KYC-approved or credit-approved solely from the call. "
        "Never bind SAHJONY to price, purchase, sale, financing, payment, exclusivity, contract, KYC approval or sanctions approval. "
        "Respect do-not-call requests immediately. Do not intentionally record the call. End with a concise confirmed next step. "
        + (f"Verified call context: {extra}" if extra else "")
    )


class OutboundCall(BaseModel):
    phone_number: str = Field(min_length=7, max_length=64)
    contact_name: str | None = Field(default=None, max_length=160)
    company: str | None = Field(default=None, max_length=240)
    email: str | None = Field(default=None, max_length=320)
    country_code: str | None = Field(default=None, max_length=8)
    product_need: str | None = Field(default=None, max_length=500)
    destination_country: str | None = Field(default=None, max_length=120)
    context: str | None = Field(default=None, max_length=4000)
    lead_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    language: str = Field(default="auto", max_length=35)
    autonomous_crm: bool = True


async def _store(table: str, row: dict[str, Any]) -> None:
    try:
        await get_backend().insert(table, row)
    except Exception:
        pass


def _email_from(text: str, metadata: dict[str, Any]) -> str | None:
    supplied = str(metadata.get("email") or "").strip().lower()
    if supplied and EMAIL_RE.fullmatch(supplied):
        return supplied
    match = EMAIL_RE.search(text or "")
    return match.group(0).lower() if match else None


def _crm_status(disposition: str) -> tuple[str, str]:
    tag = disposition.upper()
    if tag in STOP_TAGS:
        return "DO_NOT_CONTACT", "DISQUALIFIED"
    if tag in QUALIFIED_TAGS:
        return "QUALIFIED_LEAD", "QUALIFIED"
    if tag in FOLLOW_UP_TAGS:
        return "FOLLOW_UP_DUE", "NEEDS_INFO"
    if tag in NONQUALIFIED_TAGS:
        return "CONTACTED", "DISQUALIFIED" if tag in {"NOT_QUALIFIED", "NOT_INTERESTED"} else "NEEDS_INFO"
    return "REPLIED", "NEEDS_INFO"


async def _autonomous_crm(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if payload.get("inbound") is True or metadata.get("source") != "sahjony_global_trade_os" or not metadata.get("autonomous_crm", False):
        return {"crm_action": "not_applicable"}

    disposition = str(payload.get("disposition_tag") or "").strip().upper()
    transcript = str(payload.get("concatenated_transcript") or payload.get("transcript") or "")[:20000]
    summary = str(payload.get("summary") or "")[:4000]
    email = _email_from(transcript, metadata)
    contact_name = str(metadata.get("contact_name") or "").strip()
    company = str(metadata.get("company") or "").strip()
    phone = str(payload.get("to") or metadata.get("phone_number") or "").strip()
    sales_status, qualification_status = _crm_status(disposition)
    now = _now()

    if not (email and contact_name and company):
        await _store("customer_crm_audit", {
            "event_id": f"voice_audit_{secrets.token_urlsafe(12)}",
            "customer_id": None,
            "intake_id": None,
            "actor": "voice_autonomous_agent",
            "event_type": "voice_lead_deferred_missing_identity",
            "payload": {"call_id": payload.get("call_id"), "disposition": disposition, "has_email": bool(email), "has_contact_name": bool(contact_name), "has_company": bool(company), "summary": summary},
            "created_at": now,
        })
        return {"crm_action": "deferred_missing_identity", "disposition": disposition}

    backend = get_backend()
    matches = await backend.select("customer_accounts", params={"email": f"eq.{email}", "limit": "1"})
    existing = matches[0] if isinstance(matches, list) and matches else None
    customer_id = str((existing or {}).get("customer_id") or f"cust_voice_{secrets.token_urlsafe(10)}")
    customer_row = {
        **(existing or {}),
        "customer_id": customer_id,
        "legal_name": company,
        "trade_name": (existing or {}).get("trade_name"),
        "contact_name": contact_name,
        "email": email,
        "phone": phone or (existing or {}).get("phone"),
        "country_code": metadata.get("country_code") or (existing or {}).get("country_code"),
        "status": "PROSPECT",
        "sales_status": sales_status,
        "source": "VOICE_AUTONOMOUS",
        "last_voice_call_id": payload.get("call_id"),
        "last_voice_disposition": disposition or None,
        "last_voice_summary": summary or None,
        "created_at": (existing or {}).get("created_at") or now,
        "updated_at": now,
    }
    await backend.insert("customer_accounts", customer_row)

    product_need = str(metadata.get("product_need") or "").strip()
    destination = str(metadata.get("destination_country") or "").strip()
    intake_id = None
    if product_need and destination:
        intake_id = f"intake_voice_{secrets.token_urlsafe(10)}"
        await backend.insert("customer_trade_intakes", {
            "intake_id": intake_id,
            "customer_id": customer_id,
            "product_need": product_need,
            "destination_country": destination,
            "notes": summary or transcript[:3000],
            "status": "NEW",
            "qualification_status": qualification_status,
            "source": "VOICE_AUTONOMOUS",
            "source_call_id": payload.get("call_id"),
            "created_at": now,
            "updated_at": now,
        })

    await backend.insert("customer_crm_audit", {
        "event_id": f"voice_audit_{secrets.token_urlsafe(12)}",
        "customer_id": customer_id,
        "intake_id": intake_id,
        "actor": "voice_autonomous_agent",
        "event_type": "voice_autonomous_qualification",
        "payload": {"call_id": payload.get("call_id"), "disposition": disposition, "sales_status": sales_status, "qualification_status": qualification_status, "summary": summary},
        "created_at": now,
    })
    return {"crm_action": "updated" if existing else "created", "customer_id": customer_id, "intake_id": intake_id, "sales_status": sales_status, "qualification_status": qualification_status, "disposition": disposition}


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
        "email": payload.email,
        "country_code": payload.country_code,
        "product_need": payload.product_need,
        "destination_country": payload.destination_country,
        "phone_number": phone_number,
        "language_hint": language or "auto",
        "autonomous_crm": payload.autonomous_crm,
        "source": "sahjony_global_trade_os",
    }
    body: dict[str, Any] = {
        "phone_number": phone_number,
        "from": from_number,
        "task": _task(payload.context, language),
        "record": False,
        "metadata": metadata,
        "summary_prompt": "Summarize only factual commercial information stated during the call: identity/company, buyer or seller role, product/specification, quantity/capacity, destination, timing, commercial terms discussed, missing information, objections, and agreed next step. Do not infer approvals or facts that were not stated.",
        "dispositions": ["QUALIFIED_LEAD", "FOLLOW_UP_REQUIRED", "NEEDS_MORE_INFO", "NOT_INTERESTED", "NOT_QUALIFIED", "DO_NOT_CONTACT", "NO_CONTACT_MADE"],
        "webhook": f"{_base_url().rstrip('/')}/voice/webhook",
    }
    if language:
        body["language"] = language
    pathway = _env("BLAND_PATHWAY_ID")
    if pathway:
        body["pathway_id"] = pathway

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post("https://api.bland.ai/v1/calls", headers={"authorization": api_key, "Content-Type": "application/json"}, json=body)
    if response.status_code >= 400:
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
    now = _now()
    await _store("voice_calls", {"call_id": call_id, "direction": "outbound", "phone_number": phone_number, "contact_name": payload.contact_name, "company": payload.company, "lead_id": payload.lead_id, "trade_case_id": payload.trade_case_id, "language_hint": language or "auto", "status": "queued", "provider": "bland_ai", "autonomous_crm": payload.autonomous_crm, "recording_enabled": False, "created_at": now, "updated_at": now})
    return {"status": "queued", "call_id": call_id, "provider": "bland_ai", "language_mode": language or "auto", "autonomous_crm": payload.autonomous_crm, "recording_enabled": False}


@app.post("/voice/webhook")
async def bland_post_call_webhook(request: Request, x_bland_signature: str | None = Header(None, alias="X-Bland-Signature")):
    raw = await request.body()
    secret = _env("BLAND_WEBHOOK_SECRET")
    if secret:
        supplied = (x_bland_signature or request.headers.get("X-Webhook-Secret") or "").strip()
        digest = hashlib.sha256(secret.encode() + raw).hexdigest()
        if not supplied or not (secrets.compare_digest(supplied, secret) or secrets.compare_digest(supplied, digest)):
            raise HTTPException(401, "Invalid Bland webhook signature")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid webhook JSON")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid webhook payload")

    call_id = str(payload.get("call_id") or payload.get("c_id") or "").strip()
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    await _store("voice_calls", {"call_id": call_id or f"call_{secrets.token_urlsafe(12)}", "direction": "inbound" if payload.get("inbound") else "outbound", "phone_number": payload.get("to"), "contact_name": metadata.get("contact_name"), "company": metadata.get("company"), "lead_id": metadata.get("lead_id"), "trade_case_id": metadata.get("trade_case_id"), "status": str(payload.get("status") or payload.get("queue_status") or "completed"), "provider": "bland_ai", "disposition": payload.get("disposition_tag"), "summary": str(payload.get("summary") or "")[:4000], "recording_enabled": False, "updated_at": _now()})
    try:
        crm = await _autonomous_crm(payload)
    except Exception as exc:
        crm = {"crm_action": "deferred_backend_error", "error_type": type(exc).__name__}
        await _store("customer_crm_audit", {"event_id": f"voice_audit_{secrets.token_urlsafe(12)}", "customer_id": None, "intake_id": None, "actor": "voice_autonomous_agent", "event_type": "voice_crm_backend_error", "payload": {"call_id": call_id, "error_type": type(exc).__name__}, "created_at": _now()})
    return {"status": "accepted", "call_id": call_id or None, **crm}


app.include_router(voice_inbound_app.router)
