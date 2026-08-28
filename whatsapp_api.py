from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY WhatsApp Transport", version="3.0.0", docs_url=None, redoc_url=None)

PROVIDER = os.getenv("WHATSAPP_PROVIDER", "meta_cloud").strip().lower() or "meta_cloud"
CONFIG_TABLE = "system_integrations"
CONFIG_ID = "whatsapp_meta_cloud"


class WhatsAppSend(BaseModel):
    to: str = Field(min_length=8, max_length=32, description="Recipient phone number in E.164 digits, with or without leading +")
    body: str = Field(min_length=1, max_length=4096)
    preview_url: bool = False
    lead_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    source_url: str | None = Field(default=None, max_length=2000)


class WhatsAppSetup(BaseModel):
    app_id: str = Field(min_length=3, max_length=160)
    app_secret: str = Field(min_length=8, max_length=512)
    config_id: str = Field(min_length=3, max_length=160)
    verify_token: str | None = Field(default=None, min_length=12, max_length=256)
    graph_api_version: str = Field(min_length=2, max_length=32)


class EmbeddedSignupExchange(BaseModel):
    code: str = Field(min_length=4, max_length=4096)
    waba_id: str = Field(min_length=3, max_length=160)
    phone_number_id: str = Field(min_length=3, max_length=160)


class ManualWhatsAppConfig(BaseModel):
    access_token: str = Field(min_length=8, max_length=8192)
    phone_number_id: str = Field(min_length=3, max_length=160)
    business_account_id: str | None = Field(default=None, max_length=160)
    verify_token: str = Field(min_length=12, max_length=256)
    app_secret: str = Field(min_length=8, max_length=512)
    app_id: str | None = Field(default=None, max_length=160)
    config_id: str | None = Field(default=None, max_length=160)
    graph_api_version: str = Field(min_length=2, max_length=32)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


def _normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 8 or len(digits) > 15:
        raise HTTPException(status_code=400, detail="Recipient must be a valid international phone number")
    return digits


def _master_key() -> bytes:
    material = (
        os.getenv("WHATSAPP_CONFIG_ENCRYPTION_KEY", "").strip()
        or os.getenv("OWNER_SESSION_SECRET", "").strip()
        or os.getenv("OWNER_TOKEN", "").strip()
    )
    if not material:
        raise HTTPException(status_code=503, detail="Secure owner secret is required before WhatsApp credentials can be stored")
    return hashlib.sha256(("sahjony:whatsapp:v3:" + material).encode("utf-8")).digest()


def _encrypt_secret(value: str) -> str:
    nonce = secrets.token_bytes(12)
    cipher = AESGCM(_master_key()).encrypt(nonce, value.encode("utf-8"), CONFIG_ID.encode("utf-8"))
    return base64.urlsafe_b64encode(nonce + cipher).decode("ascii")


def _decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        return AESGCM(_master_key()).decrypt(raw[:12], raw[12:], CONFIG_ID.encode("utf-8")).decode("utf-8")
    except Exception:
        return ""


def _env_config() -> dict[str, str]:
    return {
        "provider": PROVIDER,
        "access_token": os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip(),
        "phone_number_id": os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip(),
        "business_account_id": os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip(),
        "verify_token": (
            os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "").strip()
            or os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
        ),
        "app_secret": os.getenv("WHATSAPP_APP_SECRET", "").strip(),
        "app_id": os.getenv("WHATSAPP_APP_ID", "").strip() or os.getenv("META_APP_ID", "").strip(),
        "config_id": os.getenv("WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID", "").strip(),
        "graph_api_version": os.getenv("WHATSAPP_GRAPH_API_VERSION", "").strip(),
    }


async def _load_stored_config() -> dict[str, str]:
    try:
        rows = await get_backend().select(CONFIG_TABLE, params={"id": f"eq.{CONFIG_ID}", "limit": "1"})
    except Exception:
        return {}
    if not rows:
        return {}
    row = rows[0]
    return {
        "provider": "meta_cloud",
        "access_token": _decrypt_secret(row.get("access_token_enc")),
        "phone_number_id": str(row.get("phone_number_id") or ""),
        "business_account_id": str(row.get("business_account_id") or ""),
        "verify_token": _decrypt_secret(row.get("verify_token_enc")),
        "app_secret": _decrypt_secret(row.get("app_secret_enc")),
        "app_id": str(row.get("app_id") or ""),
        "config_id": str(row.get("config_id") or ""),
        "graph_api_version": str(row.get("graph_api_version") or ""),
    }


async def _config() -> dict[str, str]:
    stored = await _load_stored_config()
    env = _env_config()
    merged: dict[str, str] = {"provider": "meta_cloud"}
    for key in (
        "access_token", "phone_number_id", "business_account_id", "verify_token",
        "app_secret", "app_id", "config_id", "graph_api_version",
    ):
        merged[key] = env.get(key) or stored.get(key) or ""
    return merged


async def _save_config(values: dict[str, str]) -> None:
    existing = await _load_stored_config()
    merged = {**existing, **{k: v for k, v in values.items() if v not in (None, "")}}
    row = {
        "id": CONFIG_ID,
        "provider": "meta_cloud",
        "access_token_enc": _encrypt_secret(merged.get("access_token", "")) if merged.get("access_token") else None,
        "phone_number_id": merged.get("phone_number_id") or None,
        "business_account_id": merged.get("business_account_id") or None,
        "verify_token_enc": _encrypt_secret(merged.get("verify_token", "")) if merged.get("verify_token") else None,
        "app_secret_enc": _encrypt_secret(merged.get("app_secret", "")) if merged.get("app_secret") else None,
        "app_id": merged.get("app_id") or None,
        "config_id": merged.get("config_id") or None,
        "graph_api_version": merged.get("graph_api_version") or None,
        "updated_at": _now(),
    }
    await get_backend().insert(CONFIG_TABLE, row)


def _configured(cfg: dict[str, str]) -> bool:
    return bool(
        cfg.get("access_token")
        and cfg.get("phone_number_id")
        and cfg.get("verify_token")
        and cfg.get("app_secret")
        and cfg.get("graph_api_version")
    )


def _send_ready(cfg: dict[str, str]) -> bool:
    return bool(cfg.get("access_token") and cfg.get("phone_number_id") and cfg.get("graph_api_version"))


def _webhook_ready(cfg: dict[str, str]) -> bool:
    return bool(cfg.get("verify_token") and cfg.get("app_secret"))


def _embedded_signup_ready(cfg: dict[str, str]) -> bool:
    return bool(cfg.get("app_id") and cfg.get("app_secret") and cfg.get("config_id") and cfg.get("graph_api_version"))


def _ai_auto_reply_enabled() -> bool:
    return os.getenv("WHATSAPP_AI_AUTO_REPLY_ENABLED", "true").strip().lower() == "true"


def _openai_ready() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _graph_url(cfg: dict[str, str], path: str) -> str:
    version = cfg.get("graph_api_version", "").strip()
    if not version:
        raise HTTPException(status_code=503, detail="WhatsApp Graph API version is not configured")
    return f"https://graph.facebook.com/{version}/{path.lstrip('/')}"


async def _meta_json(
    url: str,
    *,
    access_token: str = "",
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, url, headers=headers, json=payload, params=params)
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Meta WhatsApp HTTP {response.status_code}: {response.text[:1200]}")
        if not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"raw": data}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Meta WhatsApp unavailable: {type(exc).__name__}") from exc


async def _record_outbound(
    *,
    to: str,
    body: str,
    provider_message_id: str | None,
    lead_id: str | None = None,
    customer_id: str | None = None,
    source_url: str | None = None,
    autonomous: bool = False,
) -> None:
    try:
        await get_backend().insert("outbound_notifications", {
            "notification_id": f"ntf_{secrets.token_urlsafe(16)}",
            "event_id": None,
            "recipient_role": "customer" if customer_id else "lead",
            "recipient_id": customer_id or lead_id or "external",
            "channel": "whatsapp",
            "destination": _normalize_phone(to),
            "subject": "WhatsApp AI reply" if autonomous else "WhatsApp outreach",
            "body": body,
            "delivery_status": "submitted",
            "provider": "meta_whatsapp_cloud",
            "provider_message_id": provider_message_id,
            "source_url": source_url,
            "autonomous": autonomous,
            "attempts": 1,
            "last_error": None,
            "created_at": _now(),
            "updated_at": _now(),
        })
    except Exception:
        pass


async def _send_text(
    cfg: dict[str, str],
    *,
    to: str,
    body: str,
    preview_url: bool = False,
    lead_id: str | None = None,
    customer_id: str | None = None,
    source_url: str | None = None,
    autonomous: bool = False,
) -> dict[str, Any]:
    if not _send_ready(cfg):
        raise HTTPException(status_code=503, detail="WhatsApp Cloud API is not configured for sending")
    recipient = _normalize_phone(to)
    result = await _meta_json(
        _graph_url(cfg, f"{cfg['phone_number_id']}/messages"),
        access_token=cfg["access_token"],
        method="POST",
        payload={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "text",
            "text": {"preview_url": preview_url, "body": body[:4096]},
        },
    )
    messages = result.get("messages") or []
    message_id = messages[0].get("id") if messages and isinstance(messages[0], dict) else None
    await _record_outbound(
        to=recipient,
        body=body[:4096],
        provider_message_id=message_id,
        lead_id=lead_id,
        customer_id=customer_id,
        source_url=source_url,
        autonomous=autonomous,
    )
    return {"status": "submitted", "provider": "meta_whatsapp_cloud", "message_id": message_id, "recipient": recipient}


async def _message_seen(message_id: str | None) -> bool:
    if not message_id:
        return False
    try:
        rows = await get_backend().select("whatsapp_messages", params={"message_id": f"eq.{message_id}", "limit": "1"})
        return bool(rows)
    except Exception:
        return False


async def _register_inbound_message(
    *,
    phone: str | None,
    message_id: str | None,
    message_type: str,
    text: str,
    contact_name: str | None,
) -> None:
    try:
        await get_backend().insert("whatsapp_messages", {
            "message_id": message_id or f"wam_{secrets.token_urlsafe(16)}",
            "direction": "inbound",
            "phone": phone,
            "contact_name": contact_name,
            "message_type": message_type,
            "text": text[:4096],
            "provider": "meta_whatsapp_cloud",
            "received_at": _now(),
        })
    except Exception:
        pass


async def _upsert_whatsapp_lead(phone: str, text: str, contact_name: str | None, *, opted_out: bool = False) -> str:
    lead_id = "wa_" + hashlib.sha256(phone.encode("utf-8")).hexdigest()[:24]
    try:
        rows = await get_backend().select("whatsapp_leads", params={"lead_id": f"eq.{lead_id}", "limit": "1"}) or []
        existing = rows[0] if rows else {}
        row = {
            "lead_id": lead_id,
            "phone": phone,
            "contact_name": contact_name or existing.get("contact_name"),
            "source": "WHATSAPP_INBOUND",
            "channel": "whatsapp",
            "status": "OPTED_OUT" if opted_out else existing.get("status") or "NEW",
            "message_count": int(existing.get("message_count") or 0) + 1,
            "first_seen_at": existing.get("first_seen_at") or _now(),
            "last_seen_at": _now(),
            "last_message": text[:4000],
            "assigned_owner_id": existing.get("assigned_owner_id") or "owner",
            "ai_followup_allowed": not opted_out,
            "updated_at": _now(),
        }
        await get_backend().insert("whatsapp_leads", row)
    except Exception:
        pass
    return lead_id


async def _record_inbound_event(phone: str | None, message_id: str | None, text: str, message_type: str, lead_id: str | None) -> None:
    try:
        await get_backend().insert("business_events", {
            "event_id": f"evt_{secrets.token_urlsafe(16)}",
            "event_type": "message",
            "source_type": "whatsapp_inbound",
            "source_id": message_id,
            "trade_case_id": None,
            "customer_id": None,
            "lead_id": lead_id,
            "actor_role": "customer",
            "actor_id": phone or "external_whatsapp",
            "visibility": "internal",
            "title": "Inbound WhatsApp message",
            "summary": text[:4000],
            "action_required": True,
            "action_label": "Review WhatsApp conversation",
            "priority": "high",
            "event_status": "open",
            "payload": {"phone": phone, "provider": "meta_whatsapp_cloud", "raw_type": message_type},
            "created_at": _now(),
            "updated_at": _now(),
        })
    except Exception:
        pass


def _opt_out(text: str) -> bool:
    normalized = " ".join(text.lower().strip().split())
    exact = {
        "stop", "unsubscribe", "cancel", "cancelar", "parar", "baja", "salir",
        "no me escribas", "no me contacten", "remove me", "opt out", "désabonner",
    }
    return normalized in exact


async def _generate_ai_reply(text: str, contact_name: str | None) -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return ""
    model = os.getenv("WHATSAPP_AI_MODEL", "").strip() or os.getenv("OPENAI_FAST_MODEL", "").strip() or "gpt-5.6-terra"
    system = (
        "You are the multilingual WhatsApp FrontDesk AI Agent for SAHJONY Global Trade. "
        "Reply in the customer's language. Be concise, professional, commercially useful, and transparent that you are an AI assistant. "
        "Qualify legitimate import/export and sourcing needs by gathering product, specifications, quantity, destination, target timing and budget when missing. "
        "Never promise legal authorization, sanctions clearance, product availability, price, credit, payment release, shipment release, supplier commitment, or guaranteed delivery. "
        "Never request passwords, full payment-card details, API keys, or authentication secrets. "
        "For regulated, Cuba-related, sanctions-sensitive, payment, customs or legal questions, state that SAHJONY's trade/compliance team must verify the transaction before commitment. "
        "If the person asks for a human, acknowledge and say the conversation has been routed for human attention."
    )
    user = f"Contact name: {contact_name or 'unknown'}\nInbound WhatsApp message:\n{text[:5000]}"
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [{"type": "input_text", "text": user}]},
        ],
        "max_output_tokens": 500,
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code >= 400:
            return ""
        data = response.json()
        text_out = str(data.get("output_text") or "").strip()
        if not text_out:
            parts: list[str] = []
            for item in data.get("output") or []:
                for content in item.get("content") or []:
                    if content.get("type") in {"output_text", "text"} and content.get("text"):
                        parts.append(str(content["text"]))
            text_out = "\n".join(parts).strip()
        return text_out[:4096]
    except Exception:
        return ""


async def _process_inbound(
    cfg: dict[str, str],
    *,
    phone: str | None,
    message_id: str | None,
    message_type: str,
    text: str,
    contact_name: str | None,
) -> None:
    try:
        clean_phone = _normalize_phone(phone or "") if phone else ""
    except HTTPException:
        clean_phone = ""
    opted_out = bool(text and _opt_out(text))
    lead_id = await _upsert_whatsapp_lead(clean_phone, text, contact_name, opted_out=opted_out) if clean_phone else None
    await _record_inbound_event(clean_phone or phone, message_id, text, message_type, lead_id)
    if not clean_phone or message_type != "text":
        return
    if opted_out:
        try:
            await _send_text(
                cfg,
                to=clean_phone,
                body="Your WhatsApp opt-out request has been recorded. SAHJONY Global Trade will not send automated follow-ups to this number.",
                lead_id=lead_id,
                autonomous=True,
            )
        except Exception:
            pass
        return
    if not (_ai_auto_reply_enabled() and _openai_ready() and _send_ready(cfg)):
        return
    reply = await _generate_ai_reply(text, contact_name)
    if not reply:
        return
    try:
        await _send_text(cfg, to=clean_phone, body=reply, lead_id=lead_id, autonomous=True)
    except Exception:
        pass


@app.get("/whatsapp/health")
async def whatsapp_health() -> dict[str, Any]:
    cfg = await _config()
    persistence = persistent_backend_status()
    return {
        "status": "ok" if _configured(cfg) else "configuration_required",
        "service": "whatsapp-transport",
        "version": "3.0.0",
        "provider": "meta_cloud",
        "send_ready": _send_ready(cfg),
        "webhook_ready": _webhook_ready(cfg),
        "embedded_signup_ready": _embedded_signup_ready(cfg),
        "phone_number_id_configured": bool(cfg.get("phone_number_id")),
        "business_account_id_configured": bool(cfg.get("business_account_id")),
        "access_token_configured": bool(cfg.get("access_token")),
        "verify_token_configured": bool(cfg.get("verify_token")),
        "app_secret_configured": bool(cfg.get("app_secret")),
        "app_id_configured": bool(cfg.get("app_id")),
        "config_id_configured": bool(cfg.get("config_id")),
        "graph_api_version_configured": bool(cfg.get("graph_api_version")),
        "durable_backend_configured": persistence["configured"],
        "durable_backend_provider": persistence["provider"],
        "lead_capture_enabled": persistence["configured"],
        "webhook_idempotency_enabled": persistence["configured"],
        "ai_auto_reply_enabled": _ai_auto_reply_enabled(),
        "ai_ready": _openai_ready(),
        "outbound_owner_governed": True,
        "autonomous_reply_release_authority": False,
        "secrets_exposed": False,
        "durable_owner_configuration": True,
    }


@app.get("/whatsapp/setup")
async def whatsapp_setup_status(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    cfg = await _config()
    return {
        "app_id": cfg.get("app_id") or None,
        "config_id": cfg.get("config_id") or None,
        "graph_api_version": cfg.get("graph_api_version") or None,
        "phone_number_id": cfg.get("phone_number_id") or None,
        "business_account_id": cfg.get("business_account_id") or None,
        "verify_token_configured": bool(cfg.get("verify_token")),
        "app_secret_configured": bool(cfg.get("app_secret")),
        "access_token_configured": bool(cfg.get("access_token")),
        "embedded_signup_ready": _embedded_signup_ready(cfg),
        "send_ready": _send_ready(cfg),
        "webhook_ready": _webhook_ready(cfg),
        "webhook_url": "https://www.sahjony.com/whatsapp/webhook",
        "ai_auto_reply_enabled": _ai_auto_reply_enabled(),
        "secrets_exposed": False,
    }


@app.post("/whatsapp/setup")
async def whatsapp_setup_save(payload: WhatsAppSetup, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    verify_token = payload.verify_token or secrets.token_urlsafe(32)
    await _save_config({
        "app_id": payload.app_id.strip(),
        "app_secret": payload.app_secret.strip(),
        "config_id": payload.config_id.strip(),
        "verify_token": verify_token,
        "graph_api_version": payload.graph_api_version.strip(),
    })
    return {
        "status": "saved",
        "embedded_signup_ready": True,
        "verify_token_generated": payload.verify_token is None,
        "secrets_exposed": False,
    }


@app.post("/whatsapp/setup/manual")
async def whatsapp_setup_manual(payload: ManualWhatsAppConfig, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    await _save_config({
        "access_token": payload.access_token.strip(),
        "phone_number_id": payload.phone_number_id.strip(),
        "business_account_id": (payload.business_account_id or "").strip(),
        "verify_token": payload.verify_token.strip(),
        "app_secret": payload.app_secret.strip(),
        "app_id": (payload.app_id or "").strip(),
        "config_id": (payload.config_id or "").strip(),
        "graph_api_version": payload.graph_api_version.strip(),
    })
    cfg = await _config()
    return {
        "status": "saved",
        "send_ready": _send_ready(cfg),
        "webhook_ready": _webhook_ready(cfg),
        "secrets_exposed": False,
    }


@app.post("/whatsapp/setup/exchange")
async def whatsapp_embedded_signup_exchange(payload: EmbeddedSignupExchange, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    cfg = await _config()
    if not _embedded_signup_ready(cfg):
        raise HTTPException(status_code=503, detail="Meta Embedded Signup app configuration is incomplete")
    token_result = await _meta_json(
        _graph_url(cfg, "oauth/access_token"),
        params={
            "client_id": cfg["app_id"],
            "client_secret": cfg["app_secret"],
            "code": payload.code,
        },
    )
    access_token = str(token_result.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(status_code=502, detail="Meta did not return a WhatsApp access token")
    await _save_config({
        "access_token": access_token,
        "phone_number_id": payload.phone_number_id.strip(),
        "business_account_id": payload.waba_id.strip(),
    })
    final_cfg = await _config()
    return {
        "status": "connected",
        "business_account_id": final_cfg.get("business_account_id"),
        "phone_number_id": final_cfg.get("phone_number_id"),
        "send_ready": _send_ready(final_cfg),
        "webhook_ready": _webhook_ready(final_cfg),
        "secrets_exposed": False,
    }


@app.post("/whatsapp/setup/test")
async def whatsapp_setup_test(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    cfg = await _config()
    if not _send_ready(cfg):
        raise HTTPException(status_code=503, detail="WhatsApp is not ready for provider validation")
    result = await _meta_json(
        _graph_url(cfg, cfg["phone_number_id"]),
        access_token=cfg["access_token"],
        params={"fields": "id,display_phone_number,verified_name,quality_rating"},
    )
    return {
        "status": "verified",
        "phone_number_id": result.get("id"),
        "display_phone_number": result.get("display_phone_number"),
        "verified_name": result.get("verified_name"),
        "quality_rating": result.get("quality_rating"),
        "secrets_exposed": False,
    }


@app.post("/whatsapp/send")
async def whatsapp_send(payload: WhatsAppSend, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    cfg = await _config()
    return await _send_text(
        cfg,
        to=payload.to,
        body=payload.body,
        preview_url=payload.preview_url,
        lead_id=payload.lead_id,
        customer_id=payload.customer_id,
        source_url=payload.source_url,
        autonomous=False,
    )


@app.get("/whatsapp/webhook")
async def whatsapp_webhook_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    cfg = await _config()
    verify_token = cfg.get("verify_token", "")
    if not verify_token:
        raise HTTPException(status_code=503, detail="WhatsApp webhook verification is not configured")
    if hub_mode == "subscribe" and hub_verify_token and hmac.compare_digest(hub_verify_token, verify_token):
        return int(hub_challenge) if str(hub_challenge or "").isdigit() else (hub_challenge or "")
    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed")


@app.post("/whatsapp/webhook")
async def whatsapp_webhook_receive(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
) -> dict[str, Any]:
    cfg = await _config()
    app_secret = cfg.get("app_secret", "")
    if not app_secret:
        raise HTTPException(status_code=503, detail="WhatsApp webhook signature validation is not configured")
    raw = await request.body()
    expected = "sha256=" + hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid WhatsApp webhook signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON") from exc

    accepted = 0
    duplicates = 0
    status_updates = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            contacts = {
                str(item.get("wa_id") or ""): str((item.get("profile") or {}).get("name") or "")
                for item in value.get("contacts") or []
                if item.get("wa_id")
            }
            for status in value.get("statuses") or []:
                provider_message_id = str(status.get("id") or "")
                if provider_message_id:
                    try:
                        await get_backend().insert("whatsapp_delivery_status", {
                            "id": f"{provider_message_id}:{status.get('status') or 'unknown'}",
                            "provider_message_id": provider_message_id,
                            "status": status.get("status"),
                            "recipient_id": status.get("recipient_id"),
                            "timestamp": status.get("timestamp"),
                            "provider": "meta_whatsapp_cloud",
                            "recorded_at": _now(),
                        })
                    except Exception:
                        pass
                    status_updates += 1
            for msg in value.get("messages") or []:
                phone = str(msg.get("from") or "") or None
                msg_id = str(msg.get("id") or "") or None
                msg_type = str(msg.get("type") or "") or "message"
                if await _message_seen(msg_id):
                    duplicates += 1
                    continue
                if msg_type == "text":
                    text = str((msg.get("text") or {}).get("body") or "")
                else:
                    text = f"[{msg_type} received]"
                contact_name = contacts.get(phone or "") or None
                await _register_inbound_message(
                    phone=phone,
                    message_id=msg_id,
                    message_type=msg_type,
                    text=text,
                    contact_name=contact_name,
                )
                background_tasks.add_task(
                    _process_inbound,
                    cfg,
                    phone=phone,
                    message_id=msg_id,
                    message_type=msg_type,
                    text=text,
                    contact_name=contact_name,
                )
                accepted += 1
    return {
        "status": "accepted",
        "messages_recorded": accepted,
        "duplicates_ignored": duplicates,
        "status_updates_recorded": status_updates,
        "background_ai_processing": accepted > 0 and _ai_auto_reply_enabled(),
    }
