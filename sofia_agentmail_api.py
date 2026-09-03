from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from svix.webhooks import Webhook, WebhookVerificationError

from insforge_backend import get_backend
from whatsapp_api import _owner

AGENTMAIL_API_BASE = "https://api.agentmail.to/v0"
SOFIA_AGENT_ID = "sofia-smith"
SOFIA_DISPLAY_NAME = "Sofía Smith"
SOFIA_ROLE = "Executive Manager / Executive Assistant & AI Commercial Executive"

router = APIRouter(prefix="/whatsapp/sofia/agentmail", tags=["sofia-agentmail"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _configured() -> dict[str, bool]:
    return {
        "api_key": bool(_env("AGENTMAIL_API_KEY")),
        "inbox_id": bool(_env("AGENTMAIL_INBOX_ID")),
        "webhook_secret": bool(_env("AGENTMAIL_WEBHOOK_SECRET")),
    }


def _extract_message(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("message") or payload.get("data") or {}
    if not isinstance(candidate, dict):
        candidate = {}
    return candidate


def _address(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get("email") or value.get("address") or "").strip()
    if isinstance(value, list) and value:
        return _address(value[0])
    return ""


async def _record_event(event_type: str, payload: dict[str, Any]) -> None:
    event_id = str(payload.get("event_id") or payload.get("id") or "")
    message = _extract_message(payload)
    sender = _address(message.get("from") or message.get("from_"))
    subject = str(message.get("subject") or "")[:500]
    summary = f"AgentMail {event_type}"
    if sender:
        summary += f" from {sender}"
    if subject:
        summary += f": {subject}"
    try:
        await get_backend().insert(
            "business_events",
            {
                "event_id": event_id or f"agentmail-{int(datetime.now(timezone.utc).timestamp() * 1000000)}",
                "event_type": f"agentmail.{event_type}",
                "source_type": "agentmail",
                "source_id": str(message.get("message_id") or message.get("id") or event_id or "") or None,
                "trade_case_id": None,
                "customer_id": None,
                "lead_id": None,
                "actor_role": "digital_representative",
                "actor_id": SOFIA_AGENT_ID,
                "visibility": "internal",
                "title": "Sofía omnichannel email event",
                "summary": summary[:4000],
                "action_required": False,
                "action_label": None,
                "priority": "normal",
                "event_status": "closed",
                "payload": {
                    "channel": "agentmail",
                    "event_id": event_id or None,
                    "message_id": message.get("message_id") or message.get("id"),
                    "thread_id": message.get("thread_id"),
                    "from": sender or None,
                    "subject": subject or None,
                    "received_at": message.get("received_at") or message.get("created_at"),
                },
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
    except Exception:
        # AgentMail should retry only transport failures, not temporary audit-store issues.
        pass


@router.get("/health")
async def agentmail_health() -> dict[str, Any]:
    cfg = _configured()
    ready = all(cfg.values())
    return {
        "status": "ok" if ready else "configuration_required",
        "service": "sofia-agentmail-bridge",
        "version": "1.1.0",
        "agent_id": SOFIA_AGENT_ID,
        "identity": {
            "display_name": SOFIA_DISPLAY_NAME,
            "role": SOFIA_ROLE,
            "shared_with_whatsapp": True,
        },
        "agentmail": {
            "api_key_configured": cfg["api_key"],
            "inbox_id_configured": cfg["inbox_id"],
            "webhook_secret_configured": cfg["webhook_secret"],
            "webhook_signature_verification": "svix",
        },
        "whatsapp_runtime": {
            "provider": "hostinger_openclaw",
            "agent_id": SOFIA_AGENT_ID,
        },
        "secrets_exposed": False,
        "autonomous_binding_ready": ready,
    }


@router.post("/webhook")
async def agentmail_webhook(request: Request) -> dict[str, Any]:
    secret = _env("AGENTMAIL_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="AgentMail webhook is not configured")

    raw = await request.body()
    headers = {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    if not all(headers.values()):
        raise HTTPException(status_code=400, detail="Missing webhook verification headers")

    try:
        payload = Webhook(secret).verify(raw, headers)
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    event_type = str(payload.get("event_type") or "")
    allowed = {
        "message.received",
        "message.sent",
        "message.delivered",
        "message.bounced",
        "message.complained",
        "message.rejected",
    }
    if event_type not in allowed:
        return {"status": "ignored", "event_type": event_type}

    await _record_event(event_type, payload)
    return {
        "status": "accepted",
        "event_type": event_type,
        "agent_id": SOFIA_AGENT_ID,
        "channel": "agentmail",
    }


class AgentMailSend(BaseModel):
    to: EmailStr | list[EmailStr]
    subject: str = Field(min_length=1, max_length=998)
    text: str = Field(min_length=1, max_length=100000)
    reply_to: EmailStr | list[EmailStr] | None = None


@router.post("/send")
async def agentmail_send(
    payload: AgentMailSend,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _owner(authorization)
    api_key = _env("AGENTMAIL_API_KEY")
    inbox_id = _env("AGENTMAIL_INBOX_ID")
    if not api_key or not inbox_id:
        raise HTTPException(status_code=503, detail="AgentMail outbound is not configured")

    body: dict[str, Any] = {
        "to": [str(x) for x in payload.to] if isinstance(payload.to, list) else str(payload.to),
        "subject": payload.subject,
        "text": payload.text,
    }
    if payload.reply_to is not None:
        body["reply_to"] = (
            [str(x) for x in payload.reply_to]
            if isinstance(payload.reply_to, list)
            else str(payload.reply_to)
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{AGENTMAIL_API_BASE}/inboxes/{inbox_id}/messages/send",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="AgentMail send failed")

    data = response.json()
    return {
        "status": "sent",
        "channel": "agentmail",
        "agent_id": SOFIA_AGENT_ID,
        "message_id": data.get("message_id"),
        "thread_id": data.get("thread_id"),
    }
