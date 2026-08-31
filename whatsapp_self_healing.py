from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from insforge_backend import get_backend, persistent_backend_status
from whatsapp_api import _config, _openai_ready, _openclaw_gateway_state, _send_ready, _webhook_ready


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def diagnose() -> dict[str, Any]:
    cfg = await _config()
    openclaw = await _openclaw_gateway_state()
    persistence = persistent_backend_status()
    cloud_send = _send_ready(cfg)
    cloud_webhook = _webhook_ready(cfg)
    ai_ready = _openai_ready()
    durable = bool(persistence.get("configured"))
    issues: list[str] = []
    if not cloud_send:
        issues.append("meta_send_not_ready")
    if not cloud_webhook:
        issues.append("meta_webhook_not_ready")
    if not ai_ready:
        issues.append("ai_not_ready")
    if not durable:
        issues.append("durable_backend_not_ready")
    if not bool(openclaw.get("connected")):
        issues.append("openclaw_fallback_offline")
    if cloud_send and cloud_webhook:
        active = "meta_cloud"
    elif bool(openclaw.get("connected")):
        active = "openclaw"
    else:
        active = "none"
    return {
        "status": "ok" if active != "none" and ai_ready and durable else "degraded",
        "active_provider": active,
        "meta_cloud_ready": bool(cloud_send and cloud_webhook),
        "openclaw_ready": bool(openclaw.get("connected")),
        "ai_ready": ai_ready,
        "durable_backend_ready": durable,
        "issues": issues,
        "safe_mode": active == "none" or not durable,
        "checked_at": _now(),
    }


async def repair_plan() -> dict[str, Any]:
    d = await diagnose()
    actions: list[dict[str, str]] = []
    if "meta_send_not_ready" in d["issues"]:
        actions.append({"action": "restore_meta_send_credentials", "mode": "manual_secret_or_embedded_signup_required"})
    if "meta_webhook_not_ready" in d["issues"]:
        actions.append({"action": "restore_meta_webhook_credentials", "mode": "manual_secret_or_embedded_signup_required"})
    if "ai_not_ready" in d["issues"]:
        actions.append({"action": "restore_ai_provider", "mode": "environment_or_provider_recovery_required"})
    if "durable_backend_not_ready" in d["issues"]:
        actions.append({"action": "restore_durable_backend", "mode": "database_configuration_required"})
    if d["meta_cloud_ready"] and not d["openclaw_ready"]:
        actions.append({"action": "continue_meta_cloud", "mode": "automatic"})
    if not d["meta_cloud_ready"] and d["openclaw_ready"]:
        actions.append({"action": "failover_to_openclaw", "mode": "automatic"})
    if d["active_provider"] == "none":
        actions.append({"action": "enter_safe_mode", "mode": "automatic"})
    return {"diagnosis": d, "actions": actions, "generated_at": _now()}


async def record_recovery_event(event: str, payload: dict[str, Any]) -> None:
    try:
        await get_backend().insert("business_events", {
            "event_id": f"evt_{secrets.token_urlsafe(16)}",
            "event_type": "recovery",
            "source_type": "whatsapp_self_healing",
            "source_id": event,
            "trade_case_id": None,
            "customer_id": None,
            "lead_id": None,
            "actor_role": "system",
            "actor_id": "whatsapp-self-healing-controller",
            "visibility": "internal",
            "title": f"WhatsApp recovery: {event}",
            "summary": str(payload)[:4000],
            "action_required": False,
            "action_label": None,
            "priority": "high" if payload.get("status") == "degraded" else "normal",
            "event_status": "closed",
            "payload": payload,
            "created_at": _now(),
            "updated_at": _now(),
        })
    except Exception:
        pass
