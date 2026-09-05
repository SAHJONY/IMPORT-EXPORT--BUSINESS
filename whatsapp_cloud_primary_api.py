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
    _openai_ready,
    _send_ready,
    _send_text,
    _webhook_ready,
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
from sofia_adaptive_intelligence import intelligence_health
from sofia_hermes_whatsapp_environment import generate_hermes_whatsapp_reply, health as hermes_whatsapp_health
from whatsapp_backlog_recovery import drain_backlog, find_unanswered
from sofia_self_marketing import growth_health
from sofia_self_selling import self_selling_health
from sofia_agentic_sales_os import sales_os_health
from whatsapp_crm_bridge import crm_bridge_status, router as crm_bridge_router
from sofia_agentmail_api import router as agentmail_router

app = FastAPI(title="SAHJONY Hostinger Hermes WhatsApp Sofia", version="6.0.0", docs_url=None, redoc_url=None)

# Hostinger runs the Sofia/Hermes business runtime. Meta WhatsApp Cloud is only
# the direct transport. OpenClaw is not part of this authority path.
whatsapp_core._generate_ai_reply = generate_hermes_whatsapp_reply

app.add_api_route("/whatsapp/setup", whatsapp_setup_status, methods=["GET"])
app.add_api_route("/whatsapp/setup", whatsapp_setup_save, methods=["POST"])
app.add_api_route("/whatsapp/setup/manual", whatsapp_setup_manual, methods=["POST"])
app.add_api_route("/whatsapp/setup/exchange", whatsapp_embedded_signup_exchange, methods=["POST"])
app.add_api_route("/whatsapp/setup/test", whatsapp_setup_test, methods=["POST"])
app.add_api_route("/whatsapp/webhook", whatsapp_webhook_verify, methods=["GET"])
app.add_api_route("/whatsapp/webhook", whatsapp_webhook_receive, methods=["POST"])
app.include_router(crm_bridge_router)
app.include_router(agentmail_router)


@app.get("/whatsapp/health")
async def whatsapp_health_hostinger_hermes() -> dict[str, Any]:
    cfg = await _config()
    persistence = persistent_backend_status()
    cloud_send = _send_ready(cfg)
    cloud_webhook = _webhook_ready(cfg)
    cloud_ready = _configured(cfg)
    hermes = hermes_whatsapp_health()
    hermes_ready = hermes.get("status") in {"ok", "degraded"}

    sofia = await intelligence_health()
    marketing = await growth_health()
    selling = await self_selling_health()
    crm_bridge = await crm_bridge_status()
    try:
        pending = await find_unanswered(50)
        backlog_available = True
        backlog_error_type = None
    except Exception as exc:
        pending = []
        backlog_available = False
        backlog_error_type = type(exc).__name__

    direct_ready = bool(cloud_send and cloud_webhook and hermes_ready)
    return {
        "status": "ok" if direct_ready else ("degraded" if cloud_ready or hermes_ready else "configuration_required"),
        "service": "whatsapp-transport",
        "version": "6.0.0",
        "provider": "hostinger_hermes_meta_cloud",
        "primary_provider": "hostinger_hermes_meta_cloud",
        "authority": {
            "runtime": "hostinger-vps",
            "cognition": "hermes",
            "transport": "meta_whatsapp_cloud",
            "executive_agent": "sofia-smith",
            "sole_production_authority": True,
            "openclaw_required": False,
        },
        "sofia_environment": hermes,
        "cognition_policy": "hermes_mandatory_for_sofia_whatsapp",
        "transport_is_not_cognition_runtime": True,
        "transport_policy": "direct_meta_cloud_to_hostinger_hermes",
        "command_control": {
            "owner": "Juan Gonzalez",
            "orchestrator": "AI Orchestrator",
            "executive_agent": "Sofia Smith",
            "cognition_path": "hermes_context_first",
            "whatsapp_transport": "meta_whatsapp_cloud",
            "host_runtime": "hostinger-vps",
            "openclaw": "removed_from_authority_path",
            "nonbinding_business_execution": "autonomous_under_owner_policy",
            "binding_commitments": "owner_approval_required",
        },
        "send_ready": cloud_send,
        "webhook_ready": cloud_webhook,
        "hostinger_hermes_ready": hermes_ready,
        "openclaw_required": False,
        "openclaw_authority": False,
        "meta_cloud": {
            "role": "direct_transport",
            "configured": cloud_ready,
            "send_ready": cloud_send,
            "webhook_ready": cloud_webhook,
            "cloud_independent_of_local_mac": bool(cloud_send and cloud_webhook),
            "embedded_signup_ready": _embedded_signup_ready(cfg),
            "phone_number_id_configured": bool(cfg.get("phone_number_id")),
            "business_account_id_configured": bool(cfg.get("business_account_id")),
            "access_token_configured": bool(cfg.get("access_token")),
            "verify_token_configured": bool(cfg.get("verify_token")),
            "app_secret_configured": bool(cfg.get("app_secret")),
            "graph_api_version_configured": bool(cfg.get("graph_api_version")),
        },
        "crm_bridge": crm_bridge,
        "crm_bridge_authorization": "server_to_server_hmac",
        "durable_backend_configured": bool(persistence.get("configured")),
        "durable_backend_provider": persistence.get("provider"),
        "lead_capture_enabled": bool(persistence.get("configured")),
        "webhook_idempotency_enabled": bool(persistence.get("configured")),
        "ai_auto_reply_enabled": _ai_auto_reply_enabled(),
        "ai_ready": bool(hermes_ready or _openai_ready()),
        "relationship_memory_360": True,
        "human_conversation_engine": True,
        "human_conversation_runtime_mandatory": True,
        "max_new_questions_per_turn": 2,
        "adaptive_sofia": sofia,
        "self_marketing": marketing,
        "self_selling": selling,
        "backlog_recovery": {
            "enabled": True,
            "available": backlog_available,
            "pending_conversations": len(pending),
            "error_type": backlog_error_type,
        },
        "outbound_owner_governed": True,
        "autonomous_reply_release_authority": False,
        "identity_policy": "truthful_digital_representative",
        "secrets_exposed": False,
        "durable_owner_configuration": True,
    }


@app.get("/whatsapp/sofia/hermes/health")
async def sofia_hermes_environment_health() -> dict[str, Any]:
    return hermes_whatsapp_health()


@app.get("/whatsapp/recovery/health")
async def whatsapp_recovery_health() -> dict[str, Any]:
    result = await diagnose()
    await record_recovery_event("health_check", result)
    return {
        "status": result["status"],
        "service": "whatsapp-self-healing-recovery",
        "version": "1.3.0",
        "diagnosis": result,
        "transport": "meta_whatsapp_cloud",
        "cognition": "hostinger_hermes",
        "openclaw_required": False,
        "retry_strategy": "bounded_exponential_backoff",
        "idempotent_replay": True,
        "circuit_breaker": True,
        "safe_mode": result["safe_mode"],
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
    return {"status": "ok", "count": len(items), "items": items}


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


@app.get("/whatsapp/sofia/sales-os/health")
async def sofia_sales_os_health() -> dict[str, Any]:
    return sales_os_health()


@app.post("/whatsapp/send")
async def whatsapp_send_hostinger_hermes(
    payload: WhatsAppSend,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _owner(authorization)
    cfg = await _config()
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
    await record_recovery_event(
        "hostinger_hermes_direct_meta_send",
        {"status": "ok", "provider": "meta_whatsapp_cloud", "runtime": "hostinger_hermes"},
    )
    return result
