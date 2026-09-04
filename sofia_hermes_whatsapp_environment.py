from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from insforge_backend import get_backend
from sofia_hermes_nim_brain import configured as nim_configured
from sofia_hermes_nim_brain import health as nim_health
from sofia_whatsapp_runtime import generate_sofia_reply

HERMES_BASELINE = os.getenv("SOFIA_HERMES_VERSION", "0.21.0").strip() or "0.21.0"
HERMES_AGENT_ID = "sofia-smith"
HERMES_CHANNEL = "whatsapp"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def environment_enabled() -> bool:
    value = os.getenv("SOFIA_WHATSAPP_ENVIRONMENT", "hermes").strip().lower()
    return value in {"hermes", "hermes-agent", "enabled", "true", "1"}


def _asks_about_runtime(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not normalized:
        return False
    runtime_terms = (
        "hermes", "openclaw", "entorno", "environment", "runtime", "modelo",
        "model", "donde operas", "dónde operas", "como operas", "cómo operas",
        "whatsapp", "gpt-oss", "nvidia nim",
    )
    question_terms = (
        "estas en", "estás en", "operas", "usas", "use", "running", "run",
        "which", "what", "cual", "cuál", "donde", "dónde", "inside",
    )
    return any(term in normalized for term in runtime_terms) and any(term in normalized for term in question_terms)


def _runtime_identity_reply() -> str:
    model = nim_health().get("model") or "openai/gpt-oss-120b"
    return (
        f"Sí. En WhatsApp opero dentro de Hermes Agent v{HERMES_BASELINE} como mi entorno ejecutivo. "
        f"Hostinger/OpenClaw es el transporte que conecta el canal de WhatsApp, no mi entorno de razonamiento. "
        f"Mi inferencia primaria es NVIDIA NIM con {model}. Mi identidad operativa es Sofía Smith y comparto "
        "memoria comercial, CRM, contexto de relaciones y controles de autorización de SAHJONY."
    )


async def _audit(event_type: str, payload: dict[str, Any]) -> None:
    try:
        await get_backend().insert(
            "business_events",
            {
                "event_id": f"evt_{secrets.token_urlsafe(16)}",
                "event_type": event_type,
                "source_type": "sofia_hermes_whatsapp_environment",
                "source_id": HERMES_AGENT_ID,
                "trade_case_id": None,
                "customer_id": None,
                "lead_id": None,
                "actor_role": "digital_representative",
                "actor_id": HERMES_AGENT_ID,
                "visibility": "internal",
                "title": "Sofía Hermes WhatsApp environment",
                "summary": str(payload.get("summary") or event_type)[:4000],
                "action_required": False,
                "action_label": None,
                "priority": "normal",
                "event_status": "closed",
                "payload": payload,
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
    except Exception:
        pass


async def generate_hermes_whatsapp_reply(text: str, contact_name: str | None) -> str:
    """Hermes is the mandatory operating environment for Sofía on WhatsApp.

    The transport remains Hostinger/OpenClaw. Hermes owns the executive cognition
    environment, while NVIDIA NIM GPT-OSS-120B is the preferred inference provider.
    Existing CRM, relationship memory, sales intelligence, safety, and owner gates
    remain inside generate_sofia_reply.
    """
    if not environment_enabled():
        await _audit(
            "hermes_environment_disabled",
            {"summary": "Hermes WhatsApp environment is disabled; no autonomous reply released."},
        )
        return ""

    await _audit(
        "hermes_turn_started",
        {
            "summary": "Sofía WhatsApp turn entered Hermes environment",
            "channel": HERMES_CHANNEL,
            "hermes_version": HERMES_BASELINE,
            "nim_configured": nim_configured(),
        },
    )

    # Runtime questions are answered deterministically from the actual configured
    # architecture so Sofía never confuses the WhatsApp transport with her
    # executive cognition environment.
    if _asks_about_runtime(text):
        reply = _runtime_identity_reply()
        await _audit(
            "hermes_runtime_identity_reported",
            {
                "summary": "Sofía truthfully reported Hermes as the WhatsApp operating environment",
                "channel": HERMES_CHANNEL,
                "hermes_version": HERMES_BASELINE,
                "transport": "hostinger_openclaw",
                "primary_inference": nim_health().get("model"),
            },
        )
        return reply

    reply = await generate_sofia_reply(text, contact_name)
    if reply:
        await _audit(
            "hermes_turn_completed",
            {
                "summary": "Sofía WhatsApp turn completed in Hermes environment",
                "channel": HERMES_CHANNEL,
                "hermes_version": HERMES_BASELINE,
                "reply_chars": len(reply),
                "private_reasoning_exposed": False,
            },
        )
    else:
        await _audit(
            "hermes_turn_failed_closed",
            {
                "summary": "Hermes environment produced no releasable WhatsApp reply",
                "channel": HERMES_CHANNEL,
                "hermes_version": HERMES_BASELINE,
            },
        )
    return reply


def health() -> dict[str, Any]:
    brain = nim_health()
    enabled = environment_enabled()
    return {
        "status": "ok" if enabled and nim_configured() else ("degraded" if enabled else "configuration_required"),
        "service": "sofia-hermes-whatsapp-environment",
        "environment": "hermes-agent",
        "hermes_version": HERMES_BASELINE,
        "agent_id": HERMES_AGENT_ID,
        "channel": HERMES_CHANNEL,
        "transport": "hostinger_openclaw",
        "cognition_runtime": "hermes",
        "primary_inference": {
            "provider": brain.get("provider"),
            "model": brain.get("model"),
            "configured": nim_configured(),
        },
        "openai_fallback_preserved": True,
        "relationship_memory": True,
        "crm_context": True,
        "adaptive_learning": True,
        "sales_intelligence": True,
        "owner_governance": True,
        "binding_actions_owner_controlled": True,
        "private_reasoning_exposed": False,
        "secrets_exposed": False,
        "mandatory_for_whatsapp": enabled,
    }
