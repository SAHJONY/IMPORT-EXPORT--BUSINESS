from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY WhatsApp Transport", version="1.0.0", docs_url=None, redoc_url=None)

PROVIDER = os.getenv("WHATSAPP_PROVIDER", "meta_cloud").strip().lower()
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
BUSINESS_ACCOUNT_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip()
VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "").strip()
GRAPH_API_VERSION = os.getenv("WHATSAPP_GRAPH_API_VERSION", "").strip()


class WhatsAppSend(BaseModel):
    to: str = Field(min_length=8, max_length=32, description="Recipient phone number in E.164 digits, with or without leading +")
    body: str = Field(min_length=1, max_length=4096)
    preview_url: bool = False
    lead_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    source_url: str | None = Field(default=None, max_length=2000)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


def _configured() -> bool:
    return bool(PROVIDER == "meta_cloud" and ACCESS_TOKEN and PHONE_NUMBER_ID and VERIFY_TOKEN and GRAPH_API_VERSION)


def _send_ready() -> bool:
    return bool(PROVIDER == "meta_cloud" and ACCESS_TOKEN and PHONE_NUMBER_ID and GRAPH_API_VERSION)


def _webhook_ready() -> bool:
    return bool(PROVIDER == "meta_cloud" and VERIFY_TOKEN and APP_SECRET)


def _graph_url(path: str) -> str:
    if not GRAPH_API_VERSION:
        raise HTTPException(status_code=503, detail="WHATSAPP_GRAPH_API_VERSION is not configured")
    return f"https://graph.facebook.com/{GRAPH_API_VERSION}/{path.lstrip('/')}"


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1500]
        raise HTTPException(status_code=502, detail=f"WhatsApp provider HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"WhatsApp provider unavailable: {type(exc).__name__}") from exc


def _normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 8 or len(digits) > 15:
        raise HTTPException(status_code=400, detail="Recipient must be a valid international phone number")
    return digits


async def _record_outbound(payload: WhatsAppSend, provider_message_id: str | None) -> None:
    try:
        await get_backend().insert("outbound_notifications", {
            "notification_id": f"ntf_{secrets.token_urlsafe(16)}",
            "event_id": None,
            "recipient_role": "customer" if payload.customer_id else "lead",
            "recipient_id": payload.customer_id or payload.lead_id or "external",
            "channel": "whatsapp",
            "destination": _normalize_phone(payload.to),
            "subject": "WhatsApp outreach",
            "body": payload.body,
            "delivery_status": "submitted",
            "provider": "meta_whatsapp_cloud",
            "provider_message_id": provider_message_id,
            "attempts": 1,
            "last_error": None,
            "created_at": _now(),
            "updated_at": _now(),
        })
    except Exception:
        # Delivery success must not be reversed solely because audit persistence is temporarily unavailable.
        pass


async def _record_inbound(phone: str | None, message_id: str | None, text: str, raw: dict[str, Any]) -> None:
    try:
        await get_backend().insert("business_events", {
            "event_id": f"evt_{secrets.token_urlsafe(16)}",
            "event_type": "message",
            "source_type": "whatsapp_inbound",
            "source_id": message_id,
            "trade_case_id": None,
            "customer_id": None,
            "actor_role": "customer",
            "actor_id": phone or "external_whatsapp",
            "visibility": "internal",
            "title": "Inbound WhatsApp message",
            "summary": text[:4000],
            "action_required": True,
            "action_label": "Review WhatsApp reply",
            "priority": "high",
            "event_status": "open",
            "payload": {"phone": phone, "provider": "meta_whatsapp_cloud", "raw_type": raw.get("type")},
            "created_at": _now(),
            "updated_at": _now(),
        })
    except Exception:
        pass


@app.get("/whatsapp/health")
def whatsapp_health() -> dict[str, Any]:
    return {
        "status": "ok" if _configured() else "configuration_required",
        "service": "whatsapp-transport",
        "provider": PROVIDER,
        "send_ready": _send_ready(),
        "webhook_ready": _webhook_ready(),
        "phone_number_id_configured": bool(PHONE_NUMBER_ID),
        "business_account_id_configured": bool(BUSINESS_ACCOUNT_ID),
        "access_token_configured": bool(ACCESS_TOKEN),
        "verify_token_configured": bool(VERIFY_TOKEN),
        "app_secret_configured": bool(APP_SECRET),
        "graph_api_version_configured": bool(GRAPH_API_VERSION),
        "outbound_owner_governed": True,
        "secrets_exposed": False,
        "required_env": ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "WHATSAPP_GRAPH_API_VERSION"],
    }


@app.post("/whatsapp/send")
async def whatsapp_send(payload: WhatsAppSend, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    if not _send_ready():
        raise HTTPException(status_code=503, detail="WhatsApp Cloud API is not configured for sending")
    to = _normalize_phone(payload.to)
    result = _post_json(
        _graph_url(f"{PHONE_NUMBER_ID}/messages"),
        {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": payload.preview_url, "body": payload.body},
        },
    )
    messages = result.get("messages") or []
    message_id = messages[0].get("id") if messages and isinstance(messages[0], dict) else None
    await _record_outbound(payload, message_id)
    return {"status": "submitted", "provider": "meta_whatsapp_cloud", "message_id": message_id, "recipient": to}


@app.get("/whatsapp/webhook")
def whatsapp_webhook_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    if not VERIFY_TOKEN:
        raise HTTPException(status_code=503, detail="WhatsApp webhook verification is not configured")
    if hub_mode == "subscribe" and hub_verify_token and hmac.compare_digest(hub_verify_token, VERIFY_TOKEN):
        return int(hub_challenge) if str(hub_challenge or "").isdigit() else (hub_challenge or "")
    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed")


@app.post("/whatsapp/webhook")
async def whatsapp_webhook_receive(request: Request, x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256")) -> dict[str, Any]:
    raw = await request.body()
    if not APP_SECRET:
        raise HTTPException(status_code=503, detail="WhatsApp webhook signature validation is not configured")
    expected = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid WhatsApp webhook signature")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook JSON") from exc

    accepted = 0
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for msg in value.get("messages") or []:
                phone = str(msg.get("from") or "") or None
                msg_id = str(msg.get("id") or "") or None
                msg_type = str(msg.get("type") or "")
                text = ""
                if msg_type == "text":
                    text = str((msg.get("text") or {}).get("body") or "")
                else:
                    text = f"[{msg_type or 'message'} received]"
                await _record_inbound(phone, msg_id, text, msg)
                accepted += 1
    return {"status": "accepted", "messages_recorded": accepted}
