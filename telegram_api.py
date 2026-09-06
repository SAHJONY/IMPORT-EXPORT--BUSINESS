from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token

CANONICAL_BOT_USERNAME = "@SahjonyGlobalTradeBot"
from insforge_backend import PersistentBackendConfigurationError, get_backend


app = FastAPI(
    title="SAHJONY Telegram Channel Gateway",
    version="1.2.0",
    docs_url=None,
    redoc_url=None,
)


class TelegramPublish(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    disable_notification: bool = False
    protect_content: bool = False


class TelegramMessageAction(BaseModel):
    message_id: int = Field(gt=0)


class TelegramWebhookRequest(BaseModel):
    drop_pending_updates: bool = False


def _bot_token() -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Telegram bot token is not configured")
    return token


def _channel_id() -> str:
    channel = os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    if not channel:
        raise HTTPException(status_code=503, detail="Telegram channel is not configured")
    return channel


def _webhook_secret() -> str:
    explicit = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if explicit:
        return explicit

    # Avoid another manually-managed secret when the Owner security root already
    # exists. The derived secret is deterministic, isolated by purpose and never
    # returned by the API.
    owner_secret = os.getenv("OWNER_SESSION_SECRET", "").strip()
    if not owner_secret:
        raise HTTPException(
            status_code=503,
            detail="Telegram webhook secret cannot be derived because OWNER_SESSION_SECRET is not configured",
        )
    return hmac.new(
        owner_secret.encode("utf-8"),
        b"SAHJONY:telegram:webhook:v1",
        hashlib.sha256,
    ).hexdigest()


def _webhook_url() -> str:
    explicit = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()
    if explicit:
        return explicit

    base = (
        os.getenv("TRADE_OS_URL", "").strip()
        or os.getenv("APP_URL", "").strip()
    )
    if not base:
        production_host = os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
        deployment_host = os.getenv("VERCEL_URL", "").strip()
        host = production_host or deployment_host
        if host:
            base = f"https://{host}"
    if not base:
        base = "https://import-export-business.vercel.app"
    return f"{base.rstrip('/')}/telegram/webhook"


def _require_owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if not verify_owner_token(token):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


async def _telegram_call(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _bot_token()
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload or {})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"Telegram provider unavailable: {type(exc).__name__}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Telegram returned an invalid response") from exc

    if response.status_code >= 400 or not body.get("ok"):
        description = str(body.get("description") or "Telegram request failed")[:500]
        raise HTTPException(status_code=502, detail=description)
    return body


@app.get("/telegram/health")
async def telegram_health() -> dict[str, Any]:
    webhook_secret_ready = bool(
        os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
        or os.getenv("OWNER_SESSION_SECRET", "").strip()
    )
    configured_username = os.getenv("TELEGRAM_BOT_USERNAME", "").strip() or CANONICAL_BOT_USERNAME
    return {
        "status": "ok",
        "service": "sahjony-telegram-channel-gateway",
        "bot_token_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "channel_configured": bool(os.getenv("TELEGRAM_CHANNEL_ID")),
        "webhook_secret_configured": webhook_secret_ready,
        "webhook_secret_mode": "explicit" if os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip() else "derived_from_owner_session_secret",
        "webhook_url_configured": True,
        "webhook_url": _webhook_url(),
        "bot_username": configured_username,
        "canonical_bot_username": CANONICAL_BOT_USERNAME,
        "bot_identity_matches_canonical": configured_username.lower() == CANONICAL_BOT_USERNAME.lower(),
        "owner_only_management": True,
        "autonomous_external_commitments": False,
        "fail_closed": True,
    }


@app.get("/telegram/bot")
async def telegram_bot(
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _require_owner(authorization)
    result = await _telegram_call("getMe")
    return {"status": "ok", "bot": result.get("result")}


@app.get("/telegram/channel")
async def telegram_channel(
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _require_owner(authorization)
    result = await _telegram_call("getChat", {"chat_id": _channel_id()})
    chat = result.get("result") or {}
    return {
        "status": "ok",
        "channel": {
            "id": chat.get("id"),
            "title": chat.get("title"),
            "username": chat.get("username"),
            "type": chat.get("type"),
        },
    }


@app.post("/telegram/publish")
async def telegram_publish(
    payload: TelegramPublish,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _require_owner(authorization)
    result = await _telegram_call(
        "sendMessage",
        {
            "chat_id": _channel_id(),
            "text": payload.text,
            "disable_notification": payload.disable_notification,
            "protect_content": payload.protect_content,
        },
    )
    message = result.get("result") or {}
    return {
        "published": True,
        "message_id": message.get("message_id"),
        "chat": message.get("chat"),
    }


@app.post("/telegram/test")
async def telegram_test(
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _require_owner(authorization)
    result = await _telegram_call(
        "sendMessage",
        {
            "chat_id": _channel_id(),
            "text": "SAHJONY Global Trade · Telegram integration verified.\nTrade OS communications channel is online.",
            "disable_notification": True,
        },
    )
    message = result.get("result") or {}
    return {"verified": True, "message_id": message.get("message_id")}


@app.post("/telegram/pin")
async def telegram_pin(
    payload: TelegramMessageAction,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _require_owner(authorization)
    await _telegram_call(
        "pinChatMessage",
        {
            "chat_id": _channel_id(),
            "message_id": payload.message_id,
            "disable_notification": True,
        },
    )
    return {"pinned": True, "message_id": payload.message_id}


@app.post("/telegram/delete")
async def telegram_delete(
    payload: TelegramMessageAction,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _require_owner(authorization)
    await _telegram_call(
        "deleteMessage",
        {"chat_id": _channel_id(), "message_id": payload.message_id},
    )
    return {"deleted": True, "message_id": payload.message_id}


@app.post("/telegram/webhook/configure")
async def telegram_configure_webhook(
    payload: TelegramWebhookRequest,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _require_owner(authorization)
    webhook_url = _webhook_url()
    result = await _telegram_call(
        "setWebhook",
        {
            "url": webhook_url,
            "secret_token": _webhook_secret(),
            "drop_pending_updates": payload.drop_pending_updates,
            "allowed_updates": ["channel_post", "edited_channel_post", "message"],
        },
    )
    return {
        "configured": True,
        "webhook_url": webhook_url,
        "telegram": result.get("result"),
    }


@app.get("/telegram/webhook/info")
async def telegram_webhook_info(
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _require_owner(authorization)
    result = await _telegram_call("getWebhookInfo")
    info = result.get("result") or {}
    return {
        "status": "ok",
        "webhook": {
            "url": info.get("url"),
            "pending_update_count": info.get("pending_update_count"),
            "last_error_date": info.get("last_error_date"),
            "last_error_message": info.get("last_error_message"),
            "max_connections": info.get("max_connections"),
        },
    }


async def _capture_inbound(update: dict[str, Any]) -> int:
    message = update.get("message") or update.get("channel_post") or update.get("edited_channel_post") or {}
    if not isinstance(message, dict) or not message:
        return 0
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = str(chat.get("id") or "unknown")[:200]
    sender_id = str(sender.get("id") or chat_id)[:200]
    text = str(message.get("text") or message.get("caption") or "")[:4000]
    message_id = str(message.get("message_id") or "")[:200]
    username = str(sender.get("username") or chat.get("username") or "")[:200]
    source_kind = "telegram_channel" if "channel_post" in update or "edited_channel_post" in update else "telegram_bot"
    event_id = f"telegram_{hashlib.sha256(f'{chat_id}:{message_id}:{update.get("update_id")}'.encode()).hexdigest()[:32]}"
    try:
        await get_backend().insert("business_events", {
            "event_id": event_id,
            "event_type": "telegram_inbound",
            "source_type": source_kind,
            "source_id": sender_id,
            "trade_case_id": None,
            "customer_id": None,
            "lead_id": None,
            "actor_role": "prospect",
            "actor_id": sender_id,
            "visibility": "business",
            "title": (text or "Telegram inbound event")[:240],
            "summary": (text or "Inbound Telegram event")[:4000],
            "action_required": True,
            "action_label": "Sofia Smith Telegram triage",
            "priority": "normal",
            "event_status": "open",
            "payload": {
                "channel": "telegram",
                "canonical_agent_id": "sofia-smith",
                "canonical_agent_name": "Sofia Smith",
                "chat_id": chat_id,
                "chat_type": str(chat.get("type") or "")[:80],
                "chat_title": str(chat.get("title") or "")[:240],
                "sender_id": sender_id,
                "sender_username": username or None,
                "sender_first_name": str(sender.get("first_name") or "")[:160],
                "sender_last_name": str(sender.get("last_name") or "")[:160],
                "message_id": message_id,
                "message_text": text,
                "update_id": update.get("update_id"),
                "edited": "edited_channel_post" in update,
                "binding_commitments_allowed": False,
                "capital_at_risk_usd": 0,
                "trade_intake_created": False,
            },
        })
        return 1
    except PersistentBackendConfigurationError:
        raise
    except Exception:
        return 0


@app.post("/telegram/webhook")
async def telegram_webhook(
    update: dict[str, Any],
    x_telegram_bot_api_secret_token: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> dict[str, Any]:
    expected = _webhook_secret()
    supplied = (x_telegram_bot_api_secret_token or "").strip()
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    captured = await _capture_inbound(update)
    return {
        "accepted": True,
        "update_id": update.get("update_id"),
        "captured_events": captured,
        "has_channel_post": "channel_post" in update or "edited_channel_post" in update,
        "crm_truth_policy": "Inbound Telegram is engagement evidence only until a genuine trade requirement is verified.",
        "autonomous_commitment_executed": False,
        "owner_authority_granted": False,
    }
