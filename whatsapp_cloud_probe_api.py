from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from insforge_backend import persistent_backend_status
from whatsapp_api import _config, _configured, _embedded_signup_ready, _openclaw_gateway_state, _send_ready, _webhook_ready, _ai_auto_reply_enabled, _openai_ready

app = FastAPI(title="SAHJONY WhatsApp Cloud Readiness", version="1.0.0", docs_url=None, redoc_url=None)


@app.get("/whatsapp-cloud/health")
async def whatsapp_cloud_health() -> dict[str, Any]:
    cfg = await _config()
    openclaw = await _openclaw_gateway_state()
    persistence = persistent_backend_status()
    cloud_send = _send_ready(cfg)
    cloud_webhook = _webhook_ready(cfg)
    cloud_configured = _configured(cfg)
    return {
        "status": "ok" if cloud_configured else "configuration_required",
        "service": "whatsapp-cloud-primary-readiness",
        "version": "1.0.0",
        "recommended_primary": "meta_cloud" if cloud_send and cloud_webhook else "openclaw_fallback",
        "meta_cloud": {
            "configured": cloud_configured,
            "send_ready": cloud_send,
            "webhook_ready": cloud_webhook,
            "embedded_signup_ready": _embedded_signup_ready(cfg),
            "phone_number_id_configured": bool(cfg.get("phone_number_id")),
            "business_account_id_configured": bool(cfg.get("business_account_id")),
            "access_token_configured": bool(cfg.get("access_token")),
            "verify_token_configured": bool(cfg.get("verify_token")),
            "app_secret_configured": bool(cfg.get("app_secret")),
            "graph_api_version_configured": bool(cfg.get("graph_api_version")),
        },
        "openclaw_fallback": {
            "configured": bool(openclaw.get("configured")),
            "connected": bool(openclaw.get("connected")),
            "heartbeat_fresh": bool(openclaw.get("heartbeat_fresh")),
            "last_seen_at": openclaw.get("last_seen_at"),
        },
        "ai_auto_reply_enabled": _ai_auto_reply_enabled(),
        "ai_ready": _openai_ready(),
        "durable_backend_configured": bool(persistence.get("configured")),
        "durable_backend_provider": persistence.get("provider"),
        "safe_to_remove_imac_dependency": bool(cloud_send and cloud_webhook and _openai_ready() and persistence.get("configured")),
        "secrets_exposed": False,
    }
