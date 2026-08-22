import os
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from auth import verify_owner


app = FastAPI(title="SAHJONY Telegram Trade OS", version="1.0.0", docs_url=None, redoc_url=None)

TELEGRAM_API_BASE = "https://api.telegram.org"


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _bot_token() -> str:
    token = _env("TELEGRAM_BOT_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="TELEGRAM_BOT_TOKEN is not configured")
    return token


def _channel_id() -> str:
    channel = _env("TELEGRAM_CHANNEL_ID")
    if not channel:
        raise HTTPException(status_code=503, detail="TELEGRAM_CHANNEL_ID is not configured")
    return channel


def _api_url(method: str) -> str:
    return f"{TELEGRAM_API_BASE}/bot{_bot_token()}/{method}"


def _telegram_call(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(_api_url(method), json=payload or {})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Telegram API unavailable: {exc}") from exc

    try:
        body = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Telegram returned a non-JSON response") from exc

    if response.status_code >= 400 or not body.get("ok"):
        description = body.get("description") or f"Telegram API error {response.status_code}"
        raise HTTPException(status_code=502, detail=description)
    return body


class TelegramPostRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    disable_notification: bool = False
    protect_content: bool = False


class TelegramWebhookSetupRequest(BaseModel):
    url: str | None = Field(default=None, max_length=2048)


@app.get("/telegram/health")
def telegram_health():
    return {
        "status": "ok",
        "service": "sahjony-telegram-trade-os",
        "bot_token_configured": bool(_env("TELEGRAM_BOT_TOKEN")),
        "channel_configured": bool(_env("TELEGRAM_CHANNEL_ID")),
        "webhook_secret_configured": bool(_env("TELEGRAM_WEBHOOK_SECRET")),
        "webhook_url_configured": bool(_env("TELEGRAM_WEBHOOK_URL")),
        "owner_posting_required": True,
        "autonomous_external_commitments": False,
        "fail_closed": True,
    }


@app.get("/telegram/bot", dependencies=[Depends(verify_owner)])
def telegram_bot_identity():
    body = _telegram_call("getMe")
    return {"status": "ok", "bot": body["result"]}


@app.get("/telegram/channel", dependencies=[Depends(verify_owner)])
def telegram_channel_status():
    body = _telegram_call("getChat", {"chat_id": _channel_id()})
    chat = body["result"]
    return {
        "status": "ok",
        "channel": {
            "id": chat.get("id"),
            "title": chat.get("title"),
            "username": chat.get("username"),
            "type": chat.get("type"),
        },
    }


@app.post("/telegram/post", dependencies=[Depends(verify_owner)])
def telegram_post(payload: TelegramPostRequest):
    body = _telegram_call(
        "sendMessage",
        {
            "chat_id": _channel_id(),
            "text": payload.text,
            "disable_notification": payload.disable_notification,
            "protect_content": payload.protect_content,
            "disable_web_page_preview": False,
        },
    )
    message = body["result"]
    return {
        "status": "published",
        "channel_id": message.get("chat", {}).get("id"),
        "message_id": message.get("message_id"),
        "date": message.get("date"),
    }


@app.post("/telegram/test", dependencies=[Depends(verify_owner)])
def telegram_test_post():
    body = _telegram_call(
        "sendMessage",
        {
            "chat_id": _channel_id(),
            "text": "SAHJONY Global Trade · Telegram integration verified.\nTrade OS communications channel is online.",
            "disable_notification": True,
        },
    )
    return {"status": "verified", "message_id": body["result"].get("message_id")}


@app.post("/telegram/webhook/setup", dependencies=[Depends(verify_owner)])
def telegram_setup_webhook(payload: TelegramWebhookSetupRequest):
    webhook_url = (payload.url or _env("TELEGRAM_WEBHOOK_URL")).strip()
    secret = _env("TELEGRAM_WEBHOOK_SECRET")
    if not webhook_url:
        raise HTTPException(status_code=503, detail="TELEGRAM_WEBHOOK_URL is not configured")
    if not secret:
        raise HTTPException(status_code=503, detail="TELEGRAM_WEBHOOK_SECRET is not configured")
    body = _telegram_call(
        "setWebhook",
        {
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": ["channel_post", "edited_channel_post", "message", "callback_query"],
            "drop_pending_updates": False,
        },
    )
    return {"status": "configured", "result": body.get("result"), "description": body.get("description")}


@app.get("/telegram/webhook/info", dependencies=[Depends(verify_owner)])
def telegram_webhook_info():
    body = _telegram_call("getWebhookInfo")
    info = body["result"]
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


@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
):
    expected = _env("TELEGRAM_WEBHOOK_SECRET")
    if not expected or x_telegram_bot_api_secret_token != expected:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")

    update = await request.json()
    # Inbound Telegram updates are accepted as an event source only. They do not
    # acquire Owner authority, release trades, move money, or create commitments.
    update_id = update.get("update_id") if isinstance(update, dict) else None
    return {
        "status": "accepted",
        "update_id": update_id,
        "command_execution": False,
        "owner_authority_granted": False,
    }
