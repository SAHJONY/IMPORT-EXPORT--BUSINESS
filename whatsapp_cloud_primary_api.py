from __future__ import annotations

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
    _enqueue_openclaw_message,
    _openai_ready,
    _openclaw_gateway_state,
    _send_ready,
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
from insforge_backend import get_backend, persistent_backend_status
from whatsapp_self_healing import diagnose, repair_plan, record_recovery_event
from sofia_adaptive_intelligence import intelligence_health
from sofia_whatsapp_runtime import generate_sofia_reply
from whatsapp_backlog_recovery import drain_backlog, find_unanswered
from sofia_self_marketing import growth_health
from sofia_self_selling import self_selling_health

app = FastAPI(title="SAHJONY WhatsApp Hostinger OpenClaw Primary", version="5.3.0", docs_url=None, redoc_url=None)

# Mandatory inbound reply runtime: the original customer text is preserved for safe
# contact resolution, then Sofia loads durable history/memory and sales intelligence.
whatsapp_core._generate_ai_reply = generate_sofia_reply

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


async def _named_openclaw_gateway_state(gateway_id: str) -> dict[str, Any]:
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


@app.get("/whatsapp/health")
async def whatsapp_health_hostinger_primary() -> dict[str, Any]:
    cfg = await _config()
    persistence = persistent_backend_status()
    openclaw = await _openclaw_gateway_state()
    hostinger = await _named_openclaw_gateway_state("hostinger-vps")

    # Meta is diagnostic-only in the present architecture. It must not downgrade
    # or gate a healthy Hostinger/OpenClaw transport.
    cloud_send = _send_ready(cfg)
    cloud_webhook = _webhook_ready(cfg)
    cloud_ready = _configured(cfg)

    hostinger_ready = bool(hostinger.get("connected"))
    default_openclaw_ready = bool(openclaw.get("connected"))
    openclaw_ready = hostinger_ready or default_openclaw_ready
    active = "hostinger_openclaw" if hostinger_ready else ("openclaw" if default_openclaw_ready else "none")

    recovery = await diagnose()
    sofia = await intelligence_health()
    marketing = await growth_health()
    selling = await self_selling_health()
    pending = await find_unanswered(50)

    return {
        "status": "ok" if openclaw_ready else "configuration_required",
        "service": "whatsapp-transport",
        "version": "5.3.0",
        "provider": active,
        "primary_provider": "hostinger_openclaw",
        "transport_policy": "openclaw_hostinger_primary_meta_optional",
        "business_suite_connection": True,
        "hostinger_independent_runtime": hostinger_ready,
        "send_ready": openclaw_ready,
        "webhook_ready": bool(openclaw.get("configured") or hostinger.get("configured")),
        "meta_cloud_required": False,
        "meta_cloud_controlled": False,
        "meta_cloud": {
            "role": "optional_future_transport_diagnostics_only",
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
        "openclaw_default": {
            "gateway_id": "default",
            "configured": bool(openclaw.get("configured")),
            "connected": bool(openclaw.get("connected")),
            "heartbeat_fresh": bool(openclaw.get("heartbeat_fresh")),
            "last_seen_at": openclaw.get("last_seen_at"),
        },
        "hostinger_openclaw": hostinger,
        "durable_backend_configured": bool(persistence.get("configured")),
        "durable_backend_provider": persistence.get("provider"),
        "lead_capture_enabled": bool(persistence.get("configured")),
        "webhook_idempotency_enabled": bool(persistence.get("configured")),
        "ai_auto_reply_enabled": _ai_auto_reply_enabled(),
        "ai_ready": _openai_ready(),
        "relationship_memory_360": True,
        "human_conversation_engine": True,
        "human_conversation_runtime_mandatory": True,
        "max_new_questions_per_turn": 2,
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
        "identity_policy": "truthful_digital_representative",
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
        "version": "1.2.0",
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


@app.post("/whatsapp/send")
async def whatsapp_send_hostinger_primary(
    payload: WhatsAppSend,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _owner(authorization)

    # OpenClaw outbox is the authoritative outbound transport. Hostinger consumes
    # this durable queue. Meta credentials, if present, are intentionally ignored
    # here so stale/partial Meta configuration cannot hijack production sends.
    result = await _enqueue_openclaw_message(payload)
    await record_recovery_event(
        "openclaw_primary_enqueue",
        {"status": "ok", "provider": "hostinger_openclaw", "meta_required": False},
    )
    return result
