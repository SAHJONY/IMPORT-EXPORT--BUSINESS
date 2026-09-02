from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from insforge_backend import get_backend, persistent_backend_status
from whatsapp_api import _config, _openai_ready, _openclaw_gateway_state, _send_ready, _webhook_ready


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _gateway_state(gateway_id: str) -> dict[str, Any]:
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


async def diagnose() -> dict[str, Any]:
    cfg = await _config()
    hostinger = await _gateway_state("hostinger-vps")
    fallback = await _openclaw_gateway_state()
    persistence = persistent_backend_status()

    hostinger_ready = bool(hostinger.get("connected"))
    cloud_send = _send_ready(cfg)
    cloud_webhook = _webhook_ready(cfg)
    meta_ready = bool(cloud_send and cloud_webhook)
    fallback_ready = bool(fallback.get("connected"))
    ai_ready = _openai_ready()
    durable = bool(persistence.get("configured"))

    issues: list[str] = []
    warnings: list[str] = []

    # Only conditions that can impair the sole production authority belong in issues.
    if not hostinger_ready:
        issues.append("hostinger_openclaw_not_ready")
    if not ai_ready:
        issues.append("ai_not_ready")
    if not durable:
        issues.append("durable_backend_not_ready")

    # Meta Cloud and the default/Mac OpenClaw gateway are intentionally
    # non-authoritative diagnostics/fallbacks. Their absence must not degrade
    # production health while Hostinger is healthy.
    if not cloud_send:
        warnings.append("meta_send_not_ready_diagnostic_only")
    if not cloud_webhook:
        warnings.append("meta_webhook_not_ready_diagnostic_only")
    if not fallback_ready:
        warnings.append("openclaw_fallback_offline_non_authoritative")

    production_ready = bool(hostinger_ready and ai_ready and durable)
    return {
        "status": "ok" if production_ready else "degraded",
        "production_ready": production_ready,
        "active_provider": "hostinger_openclaw" if hostinger_ready else "none",
        "hostinger_ready": hostinger_ready,
        # Backward-compatible key: production OpenClaw readiness now means the
        # authoritative Hostinger gateway, not the optional default/Mac gateway.
        "openclaw_ready": hostinger_ready,
        "openclaw_fallback_ready": fallback_ready,
        "meta_cloud_ready": meta_ready,
        "ai_ready": ai_ready,
        "durable_backend_ready": durable,
        "issues": issues,
        "warnings": warnings,
        "safe_mode": not production_ready,
        "authority": {
            "runtime": "hostinger-vps",
            "sole_production_authority": True,
            "fallback_authority_allowed": False,
        },
        "checked_at": _now(),
    }


async def repair_plan() -> dict[str, Any]:
    d = await diagnose()
    actions: list[dict[str, str]] = []
    if "hostinger_openclaw_not_ready" in d["issues"]:
        actions.append({"action": "restore_hostinger_openclaw", "mode": "automatic_runtime_recovery"})
    if "ai_not_ready" in d["issues"]:
        actions.append({"action": "restore_ai_provider", "mode": "environment_or_provider_recovery_required"})
    if "durable_backend_not_ready" in d["issues"]:
        actions.append({"action": "restore_durable_backend", "mode": "database_configuration_required"})
    if d["production_ready"]:
        actions.append({"action": "continue_hostinger_openclaw", "mode": "automatic"})
    else:
        actions.append({"action": "enter_safe_mode", "mode": "automatic"})
    return {
        "diagnosis": d,
        "actions": actions,
        "diagnostic_warnings_non_authoritative": d.get("warnings") or [],
        "generated_at": _now(),
    }


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
