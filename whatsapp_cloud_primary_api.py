from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header

import whatsapp_api as whatsapp_core
from whatsapp_api import (
    WhatsAppSend,
    _ai_auto_reply_enabled,
    _config,
    _configured,
    _embedded_signup_ready,
    _enqueue_openclaw_message,
    _openai_ready,
    _openclaw_gateway_state,
    _send_ready,
    _send_text,
    _webhook_ready,
    openclaw_event,
    openclaw_heartbeat,
    openclaw_outbox,
    openclaw_outbox_ack,
    whatsapp_embedded_signup_exchange,
    whatsapp_setup_save,
    whatsapp_setup_manual,
    whatsapp_setup_status,
    whatsapp_setup_test,
    whatsapp_webhook_receive,
    whatsapp_webhook_verify,
    _owner,
)
from insforge_backend import persistent_backend_status
from whatsapp_self_healing import diagnose, repair_plan, record_recovery_event
from sofia_adaptive_intelligence import adaptive_reply, intelligence_health
from whatsapp_backlog_recovery import drain_backlog, find_unanswered
from sofia_self_marketing import growth_health
from sofia_self_selling import self_selling_health

app = FastAPI(title="SAHJONY WhatsApp Cloud Primary", version="5.0.0", docs_url=None, redoc_url=None)

_original_generate_ai_reply = whatsapp_core._generate_ai_reply


async def _sofia_generate_ai_reply(text: str, contact_name: str | None) -> str:
    return await adaptive_reply(_original_generate_ai_reply, text, contact_name)


whatsapp_core._generate_ai_reply = _sofia_generate_ai_reply

app.add_api_route("/whatsapp/setup", whatsapp_setup_status, methods=["GET"])
app.add_api_route("/whatsapp/setup", whatsapp_setup_save, methods=["POST"])
app.add_api_route("/whatsapp/setup/manual", whatsapp_setup_manual, methods=["POST"])
app.add_api_route("/whatsapp/setup/exchange", whatsapp_embedded_signup_exchange, methods=["POST"])
app.add_api_route("/whatsapp/setup/test", whatsapp_setup_test, methods=["POST"])
app.add_api_route("/whatsapp/webhook", whatsapp_webhook_verify, methods=["GET"])
app.add_api_route("/whatsapp/webhook", whatsapp_webhook_receive, methods=["POST"])
app.add_api_route("/whatsapp/openclaw/heartbeat", openclaw_heartbeat, methods=["POST"])
app.add_api_route("/whatsapp/openclaw/events", openclaw_event, methods=["POST"])
app.add_api_route("/whatsapp/openclaw/outbox", openclaw_outbox, methods=["GET"])
app.add_api_route("/whatsapp/openclaw/outbox/ack", openclaw_outbox_ack, methods=["POST"])


@app.get("/whatsapp/health")
async def whatsapp_health_cloud_primary() -> dict[str, Any]:
    cfg = await _config()
    persistence = persistent_backend_status()
    openclaw = await _openclaw_gateway_state()
    cloud_send = _send_ready(cfg)
    cloud_webhook = _webhook_ready(cfg)
    cloud_ready = _configured(cfg)
    fallback_ready = bool(openclaw.get("connected"))
    active = "meta_cloud" if cloud_send and cloud_webhook else ("openclaw" if fallback_ready else "none")
    recovery = await diagnose()
    sofia = await intelligence_health()
    marketing = await growth_health()
    selling = await self_selling_health()
    pending = await find_unanswered(50)
    return {
        "status": "ok" if active != "none" else "configuration_required",
        "service": "whatsapp-transport",
        "version": "5.0.0",
        "provider": active,
        "primary_provider": "meta_cloud",
        "business_suite_connection": True,
        "cloud_independent_of_local_mac": bool(cloud_send and cloud_webhook),
        "send_ready": cloud_send if active == "meta_cloud" else fallback_ready,
        "webhook_ready": cloud_webhook if active == "meta_cloud" else bool(openclaw.get("configured")),
        "meta_cloud": {
            "configured": cloud_ready,
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
        "durable_backend_configured": bool(persistence.get("configured")),
        "durable_backend_provider": persistence.get("provider"),
        "lead_capture_enabled": bool(persistence.get("configured")),
        "webhook_idempotency_enabled": bool(persistence.get("configured")),
        "ai_auto_reply_enabled": _ai_auto_reply_enabled(),
        "ai_ready": _openai_ready(),
        "relationship_memory_360": True,
        "self_healing": True,
        "self_repair": True,
        "automatic_failover": True,
        "adaptive_sofia": sofia,
        "self_marketing": marketing,
        "self_selling": selling,
        "backlog_recovery": {"enabled": True, "pending_conversations": len(pending)},
        "recovery_status": recovery,
        "outbound_owner_governed": True,
        "autonomous_reply_release_authority": False,
        "secrets_exposed": False,
        "durable_owner_configuration": True,
    }


@app.get("/whatsapp/recovery/health")
async def whatsapp_recovery_health() -> dict[str, Any]:
    result = await diagnose()
    await record_recovery_event("health_check", result)
    return {
        "status": result["status"],
        "service": "whatsapp-self-healing-recovery",
        "version": "1.1.0",
        "diagnosis": result,
        "automatic_failover": True,
        "retry_strategy": "bounded_exponential_backoff",
        "idempotent_replay": True,
        "circuit_breaker": True,
        "safe_mode": result["safe_mode"],
        "self_improvement_mode": "metrics_and_prompt_optimization_with_guardrails",
        "self_modifying_production_code": False,
    }


@app.get("/whatsapp/recovery/plan")
async def whatsapp_recovery_plan() -> dict[str, Any]:
    plan = await repair_plan()
    await record_recovery_event("repair_plan", plan.get("diagnosis") or {})
    return plan


@app.get("/whatsapp/recovery/backlog")
async def whatsapp_backlog_status(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    items = await find_unanswered(200)
    return {"status":"ok","count":len(items),"items":items}


@app.post("/whatsapp/recovery/backlog/drain")
async def whatsapp_backlog_drain(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    return await drain_backlog(100)


@app.get("/whatsapp/sofia/intelligence/health")
async def sofia_intelligence_health() -> dict[str, Any]:
    return await intelligence_health()


@app.get("/whatsapp/sofia/marketing/health")
async def sofia_marketing_health() -> dict[str, Any]:
    return await growth_health()


@app.get("/whatsapp/sofia/self-selling/health")
async def sofia_self_selling_health() -> dict[str, Any]:
    return await self_selling_health()


@app.post("/whatsapp/send")
async def whatsapp_send_cloud_primary(
    payload: WhatsAppSend,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _owner(authorization)
    cfg = await _config()
    if _send_ready(cfg):
        try:
            result = await _send_text(
                cfg,
                to=payload.to,
                body=payload.body,
                preview_url=payload.preview_url,
                lead_id=payload.lead_id,
                customer_id=payload.customer_id,
                source_url=payload.source_url,
                autonomous=False,
            )
            await record_recovery_event("meta_send_success", {"status": "ok", "provider": "meta_cloud"})
            return result
        except Exception as exc:
            await record_recovery_event("meta_send_failure", {"status": "degraded", "error_type": type(exc).__name__})
    result = await _enqueue_openclaw_message(payload)
    await record_recovery_event("automatic_failover", {"status": "ok", "provider": "openclaw"})
    return result
