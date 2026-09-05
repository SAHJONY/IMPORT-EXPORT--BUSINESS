from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx

from insforge_backend import get_backend
from sofia_hermes_nim_brain import configured as nim_configured
from sofia_hermes_nim_brain import health as nim_health
from sofia_whatsapp_runtime import generate_sofia_reply

HERMES_BASELINE = os.getenv("SOFIA_HERMES_VERSION", "0.21.0").strip() or "0.21.0"
HERMES_AGENT_ID = "sofia-smith"
HERMES_CHANNEL = "whatsapp"
HERMES_TRANSPORT = "hostinger_hermes_native_whatsapp"
CUBA_CRM_HEALTH_URL = os.getenv("SOFIA_CUBA_CRM_HEALTH_URL", "https://www.sahjony.com/crm/cuba-mipymes/health").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def environment_enabled() -> bool:
    value = os.getenv("SOFIA_WHATSAPP_ENVIRONMENT", "hermes").strip().lower()
    return value in {"hermes", "hermes-agent", "enabled", "true", "1"}


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _asks_about_runtime(text: str) -> bool:
    normalized = _normalized(text)
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


def _asks_about_cuba_crm(text: str) -> bool:
    normalized = _normalized(text)
    if not normalized:
        return False
    cuba_terms = ("cuba", "cubana", "cubanas", "cubano", "cubanos", "mipyme", "mipymes", "meq", "cna")
    crm_terms = (
        "crm", "registro", "registros", "lead", "leads", "contacto", "contactos",
        "prospecto", "prospectos", "database", "base de datos", "cuantos", "cuántos",
        "tenemos", "hay", "exist", "existente", "existentes", "lista"
    )
    return any(term in normalized for term in cuba_terms) and any(term in normalized for term in crm_terms)


def _mentions_cuba_private_business(text: str) -> bool:
    normalized = _normalized(text)
    return any(term in normalized for term in (
        "cuba", "cubana", "cubanas", "cubano", "cubanos", "mipyme", "mipymes",
        "sector privado", "negocio privado", "negocios privados", "gestor", "gestores",
    ))


def _claims_cuba_crm_empty(reply: str) -> bool:
    normalized = _normalized(reply)
    empty_claims = (
        "no hay leads", "no tenemos leads", "no existen leads",
        "no hay oportunidades", "no tenemos oportunidades",
        "no hay registros", "no tenemos registros",
        "crm está vacío", "crm esta vacio", "crm se encuentra vacío", "crm se encuentra vacio",
    )
    return any(claim in normalized for claim in empty_claims)


def _runtime_identity_reply() -> str:
    model = nim_health().get("model") or "openai/gpt-oss-120b"
    return (
        f"Sí. En WhatsApp opero directamente en Hostinger mediante Hermes Agent v{HERMES_BASELINE}. "
        f"Hermes es ahora el runtime y transporte nativo del canal de WhatsApp. "
        f"Mi inferencia primaria es NVIDIA NIM con {model}. Mi identidad operativa es Sofía Smith y comparto "
        "memoria comercial, CRM, contexto de relaciones y controles de autorización de SAHJONY."
    )


async def _cuba_crm_snapshot() -> dict[str, Any]:
    if not CUBA_CRM_HEALTH_URL:
        return {"verified": False, "reason": "health_url_not_configured"}
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            response = await client.get(CUBA_CRM_HEALTH_URL, headers={"Accept": "application/json"})
        if response.status_code != 200:
            return {"verified": False, "reason": f"http_{response.status_code}"}
        data = response.json()
        if not isinstance(data, dict):
            return {"verified": False, "reason": "invalid_payload"}
        return {
            "verified": True,
            "status": data.get("status"),
            "service": data.get("service"),
            "version": data.get("version"),
            "record_count": int(data.get("record_count") or 0),
            "target": int(data.get("target") or 0),
            "remaining_shortfall": int(data.get("remaining_shortfall") or 0),
            "source_scope": data.get("source_scope"),
            "ownership_policy": data.get("ownership_policy"),
            "binding_actions": bool(data.get("binding_actions")),
        }
    except Exception as exc:
        return {"verified": False, "reason": type(exc).__name__}


def _cuba_crm_reply(snapshot: dict[str, Any]) -> str:
    count = int(snapshot.get("record_count") or 0)
    target = int(snapshot.get("target") or 0)
    remaining = int(snapshot.get("remaining_shortfall") or 0)
    return (
        f"Sí tenemos una base de datos activa de MIPYMES/actores privados de Cuba. Acabo de verificar el CRM: "
        f"hay {count:,} registros en el módulo Cuba Private Sector CRM"
        + (f", con objetivo operativo de {target:,} y una brecha de {remaining:,}" if target else "")
        + ". Estos registros son de investigación provenientes de registros públicos y listas oficiales; no deben tratarse automáticamente como compradores calificados ni RFQs activos. "
        "Antes de afirmar que el CRM está vacío, debo consultar siempre el estado real del CRM. Para convertir esos registros en oportunidades comerciales, el siguiente paso es segmentarlos por actividad/producto, evidencia de demanda, verificabilidad y capacidad de contacto, y después avanzar solo los prospectos respaldados por evidencia."
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
            "transport": HERMES_TRANSPORT,
            "nim_configured": nim_configured(),
        },
    )

    if _asks_about_runtime(text):
        reply = _runtime_identity_reply()
        await _audit(
            "hermes_runtime_identity_reported",
            {
                "summary": "Sofía truthfully reported Hermes as the WhatsApp operating environment and transport",
                "channel": HERMES_CHANNEL,
                "hermes_version": HERMES_BASELINE,
                "transport": HERMES_TRANSPORT,
                "primary_inference": nim_health().get("model"),
            },
        )
        return reply

    if _asks_about_cuba_crm(text):
        snapshot = await _cuba_crm_snapshot()
        if snapshot.get("verified") and int(snapshot.get("record_count") or 0) > 0:
            reply = _cuba_crm_reply(snapshot)
            await _audit(
                "cuba_crm_truth_verified",
                {
                    "summary": "Sofía verified the live Cuba CRM before reporting record availability",
                    "record_count": snapshot.get("record_count"),
                    "target": snapshot.get("target"),
                    "remaining_shortfall": snapshot.get("remaining_shortfall"),
                    "source_scope": snapshot.get("source_scope"),
                },
            )
            return reply
        await _audit(
            "cuba_crm_truth_unavailable",
            {"summary": "Sofía could not verify Cuba CRM status and must not claim the CRM is empty", "snapshot": snapshot},
        )

    reply = await generate_sofia_reply(text, contact_name)
    if reply and _mentions_cuba_private_business(text) and _claims_cuba_crm_empty(reply):
        snapshot = await _cuba_crm_snapshot()
        if snapshot.get("verified") and int(snapshot.get("record_count") or 0) > 0:
            reply = _cuba_crm_reply(snapshot)
            await _audit(
                "cuba_crm_false_empty_claim_blocked",
                {
                    "summary": "Hermes blocked a generated false-empty Cuba CRM claim and replaced it with verified CRM truth",
                    "record_count": snapshot.get("record_count"),
                    "target": snapshot.get("target"),
                    "remaining_shortfall": snapshot.get("remaining_shortfall"),
                },
            )
    if reply:
        await _audit(
            "hermes_turn_completed",
            {
                "summary": "Sofía WhatsApp turn completed in Hermes environment",
                "channel": HERMES_CHANNEL,
                "hermes_version": HERMES_BASELINE,
                "transport": HERMES_TRANSPORT,
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
                "transport": HERMES_TRANSPORT,
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
        "transport": HERMES_TRANSPORT,
        "cognition_runtime": "hermes",
        "hostinger_native_transport": True,
        "openclaw_dependency": False,
        "primary_inference": {
            "provider": brain.get("provider"),
            "model": brain.get("model"),
            "configured": nim_configured(),
        },
        "openai_fallback_preserved": True,
        "relationship_memory": True,
        "crm_context": True,
        "cuba_crm_truth_preflight": True,
        "cuba_crm_health_url_configured": bool(CUBA_CRM_HEALTH_URL),
        "adaptive_learning": True,
        "sales_intelligence": True,
        "owner_governance": True,
        "binding_actions_owner_controlled": True,
        "private_reasoning_exposed": False,
        "secrets_exposed": False,
        "mandatory_for_whatsapp": enabled,
    }
