from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Header

import whatsapp_api as whatsapp_core
from whatsapp_api import (
    WhatsAppSend,
    _ai_auto_reply_enabled,
    _config,
    _configured,
    _embedded_signup_ready,
    _enqueue_hermes_message,
    _openai_ready,
    _hermes_gateway_state,
    _send_ready,
    _webhook_ready,
    hermes_event,
    hermes_heartbeat,
    hermes_outbox,
    hermes_outbox_ack,
    whatsapp_embedded_signup_exchange,
    whatsapp_setup_save,
    whatsapp_setup_manual,
    whatsapp_setup_status,
    whatsapp_setup_test,
    whatsapp_webhook_receive,
    whatsapp_webhook_verify,
    _owner,
)
from insforge_backend import get_backend, persistent_backend_status
from whatsapp_self_healing import diagnose, repair_plan, record_recovery_event
from sofia_adaptive_intelligence import intelligence_health
from sofia_hermes_whatsapp_environment import generate_hermes_whatsapp_reply, health as hermes_whatsapp_health
from whatsapp_backlog_recovery import drain_backlog, find_unanswered
from sofia_self_marketing import growth_health
from sofia_self_selling import self_selling_health
from sofia_agentic_sales_os import sales_os_health
from whatsapp_crm_bridge import crm_bridge_status, router as crm_bridge_router
from sofia_agentmail_api import router as agentmail_router

app = FastAPI(title="SAHJONY WhatsApp Hermes Agent Native Transport + Sofía Runtime", version="5.7.0", docs_url=None, redoc_url=None)

# Hermes Agent is the sole WhatsApp transport and cognition runtime. No OpenClaw runtime is required or authorized.
whatsapp_core._generate_ai_reply = generate_hermes_whatsapp_reply

app.add_api_route("/whatsapp/setup", whatsapp_setup_status, methods=["GET"])
app.add_api_route("/whatsapp/setup", whatsapp_setup_save, methods=["POST"])
app.add_api_route("/whatsapp/setup/manual", whatsapp_setup_manual, methods=["POST"])
app.add_api_route("/whatsapp/setup/exchange", whatsapp_embedded_signup_exchange, methods=["POST"])
app.add_api_route("/whatsapp/setup/test", whatsapp_setup_test, methods=["POST"])
app.add_api_route("/whatsapp/webhook", whatsapp_webhook_verify, methods=["GET"])
app.add_api_route("/whatsapp/webhook", whatsapp_webhook_receive, methods=["POST"])
app.add_api_route("/whatsapp/hermes/heartbeat", hermes_heartbeat, methods=["POST"])
app.add_api_route("/whatsapp/hermes/events", hermes_event, methods=["POST"])
app.add_api_route("/whatsapp/hermes/outbox", hermes_outbox, methods=["GET"])
app.add_api_route("/whatsapp/hermes/outbox/ack", hermes_outbox_ack, methods=["POST"])
app.include_router(crm_bridge_router)
app.include_router(agentmail_router)


async def _named_hermes_gateway_state(gateway_id: str) -> dict[str, Any]:
    try:
        rows = await get_backend().select(
            "whatsapp_openclaw_gateways",
            params={"gateway_id": f"eq.{gateway_id}", "limit": "1"},
        ) or []
    except Exception:
        rows = []
    row = rows[0] if rows else {}
    last_seen = str(row.get("last_seen_at") or "")
    fresh = False
    if last_seen:
        try:
            seen_at = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            fresh = datetime.now(timezone.utc) - seen_at.astimezone(timezone.utc) <= timedelta(minutes=5)
        except ValueError:
            fresh = False
    connected = bool(row.get("channel_connected")) and fresh
    return {
        "gateway_id": gateway_id,
        "configured": bool(row),
        "connected": connected,
        "heartbeat_fresh": fresh,
        "last_seen_at": last_seen or None,
        "business_number": row.get("business_number"),
        "business_name": row.get("business_name"),
        "model": row.get("model"),
        "gateway_version": row.get("gateway_version"),
    }


# Legacy symbol alias for import/test compatibility only; production authority is Hermes.
_named_openclaw_gateway_state = _named_hermes_gateway_state
_openclaw_gateway_state = _hermes_gateway_state

def _active_hermes_gateway_id() -> str:
    return os.getenv("WHATSAPP_HERMES_GATEWAY_ID", "hermes-vercel").strip() or "hermes-vercel"

def _active_hermes_runtime() -> str:
    return os.getenv("WHATSAPP_HERMES_RUNTIME", "vercel-sandbox").strip() or "vercel-sandbox"


@app.get("/whatsapp/health")
async def whatsapp_health_hermes_authority() -> dict[str, Any]:
    cfg = await _config()
    persistence = persistent_backend_status()

    gateway_id = _active_hermes_gateway_id()
    runtime = _active_hermes_runtime()
    gateway = await _named_hermes_gateway_state(gateway_id)
    gateway_ready = bool(gateway.get("connected"))
    gateway_configured = bool(gateway.get("configured"))

    cloud_send = _send_ready(cfg)
    cloud_webhook = _webhook_ready(cfg)
    cloud_ready = _configured(cfg)

    recovery = await diagnose()
    sofia = await intelligence_health()
    marketing = await growth_health()
    selling = await self_selling_health()
    crm_bridge = await crm_bridge_status()
    backlog_available = True
    backlog_error_type = None
    try:
        pending = await find_unanswered(50)
    except Exception as exc:
        pending = []
        backlog_available = False
        backlog_error_type = type(exc).__name__
    hermes = hermes_whatsapp_health()

    return {
        "status": "ok" if gateway_ready else ("degraded" if gateway_configured else "configuration_required"),
        "service": "whatsapp-transport",
        "version": "5.7.0",
        "provider": "hermes_agent",
        "primary_provider": "hermes_agent",
        "authority": {
            "runtime": runtime,
            "transport": "hermes_native_whatsapp",
            "gateway_id": gateway_id,
            "sole_production_authority": True,
            "fallback_authority_allowed": False,
        },
        "sofia_environment": hermes,
        "cognition_policy": "hermes_mandatory_for_sofia_whatsapp",
        "transport_is_cognition_runtime": True,
        "transport_policy": "hermes_agent_single_authority",
        "command_control": {
            "owner": "Juan Gonzalez",
            "orchestrator": "AI Orchestrator",
            "executive_agent": "Sofia Smith",
            "cognition_path": "hermes_context_first",
            "whatsapp_transport": "hermes_agent",
            "nonbinding_business_execution": "autonomous_under_owner_policy",
            "binding_commitments": "owner_approval_required",
        },
        "business_suite_connection": True,
        "hermes_runtime_ready": gateway_ready,
        "vercel_independent_runtime": bool(runtime.startswith("vercel") and gateway_ready),
        "hostinger_independent_runtime": bool(runtime == "hostinger-vps" and gateway_ready),
        "send_ready": gateway_ready,
        "webhook_ready": gateway_ready,
        "meta_cloud_required": False,
        "meta_cloud_controlled": False,
        "cross_provider_failover": False,
        "meta_cloud": {
            "role": "diagnostic_only_non_authoritative",
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
        "crm_customer_admin_authorization_required": False,
        "durable_backend_configured": bool(persistence.get("configured")),
        "durable_backend_provider": persistence.get("provider"),
        "lead_capture_enabled": bool(persistence.get("configured")),
        "webhook_idempotency_enabled": bool(persistence.get("configured")),
        "ai_auto_reply_enabled": _ai_auto_reply_enabled(),
        "ai_ready": bool(hermes.get("status") in {"ok", "degraded"} or _openai_ready()),
        "relationship_memory_360": True,
        "human_conversation_engine": True,
        "human_conversation_runtime_mandatory": True,
        "max_new_questions_per_turn": 2,
        "self_healing": True,
        "self_repair": True,
        "automatic_failover": True,
        "automatic_failover_scope": f"{runtime}_runtime_only",
        "adaptive_sofia": sofia,
        "self_marketing": marketing,
        "self_selling": selling,
        "backlog_recovery": {
            "enabled": True,
            "available": backlog_available,
            "pending_conversations": len(pending),
            "error_type": backlog_error_type,
        },
        "recovery_status": recovery,
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
        "version": "1.2.0",
        "diagnosis": result,
        "automatic_failover": True,
        "automatic_failover_scope": f"{_active_hermes_runtime()}_runtime_only",
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
async def whatsapp_send_hermes_primary(
    payload: WhatsAppSend,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _owner(authorization)

    result = await _enqueue_hermes_message(payload)
    await record_recovery_event(
        "hermes_authoritative_enqueue",
        {"status": "ok", "provider": "hermes_agent", "gateway_id": _active_hermes_gateway_id()},
    )
    return result
