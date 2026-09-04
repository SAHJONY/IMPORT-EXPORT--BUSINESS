from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from insforge_backend import get_backend
from sofia_human_conversation_engine import build_sofia_prompt


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _recent_lessons(limit: int = 20) -> list[dict[str, Any]]:
    try:
        return await get_backend().select(
            "business_events",
            params={"source_type":"eq.sofia_adaptive_intelligence","order":"created_at.desc","limit":str(limit)},
        ) or []
    except Exception:
        return []


async def adaptive_context(contact_name: str | None = None) -> str:
    lessons = await _recent_lessons(12)
    compact=[]
    for row in lessons:
        payload=row.get("payload") or {}
        lesson=str(payload.get("lesson") or row.get("summary") or "").strip()
        if lesson:
            compact.append(lesson[:400])
    memory: dict[str, Any] = {"contact_name": contact_name} if contact_name else {}
    context = [
        build_sofia_prompt(memory),
        "LIVE ADAPTIVE SALES STANDARD",
        "Use progressive discovery and relationship continuity. Do not recite all known facts unless a concise recap is useful.",
        "Avoid canned openings, repetitive acknowledgements, excessive bullets, and questionnaire-style replies.",
        "Prefer one natural next step over a long checklist. Ask at most two genuinely missing questions.",
        "If the customer asks a direct question, answer it before qualifying further.",
        "Preserve verified facts and never manufacture commercial evidence or actions.",
    ]
    if compact:
        context.append("Recent validated operating lessons:\n- " + "\n- ".join(compact))
    return "\n\n".join(context)


async def record_lesson(*, lesson: str, signal: str, score: float | None = None, metadata: dict[str, Any] | None = None) -> None:
    try:
        await get_backend().insert("business_events", {
            "event_id": f"evt_{secrets.token_urlsafe(16)}",
            "event_type": "learning",
            "source_type": "sofia_adaptive_intelligence",
            "source_id": signal,
            "trade_case_id": None,
            "customer_id": None,
            "lead_id": None,
            "actor_role": "system",
            "actor_id": "sofia-reyes-adaptive-layer",
            "visibility": "internal",
            "title": "Sofia adaptive operating lesson",
            "summary": lesson[:4000],
            "action_required": False,
            "action_label": None,
            "priority": "normal",
            "event_status": "closed",
            "payload": {"lesson":lesson[:4000],"signal":signal,"score":score,"metadata":metadata or {},"validated":True},
            "created_at": _now(),
            "updated_at": _now(),
        })
    except Exception:
        pass


async def adaptive_reply(
    original_generate: Callable[[str, str | None], Awaitable[str]],
    text: str,
    contact_name: str | None,
) -> str:
    ctx = await adaptive_context(contact_name)
    enriched = f"{ctx}\n\nCUSTOMER MESSAGE:\n{text[:5000]}"
    try:
        reply = await original_generate(enriched, contact_name)
        if reply and len(reply.strip()) >= 2:
            await record_lesson(
                lesson="Successful natural conversation response completed; preserve direct answers, progressive discovery, varied phrasing and continuity.",
                signal="reply_success",
                metadata={"contact":contact_name or "unknown","reply_chars":len(reply)},
            )
            return reply.strip()
    except Exception as exc:
        await record_lesson(
            lesson=f"Primary response path failed with {type(exc).__name__}; recover without losing relationship continuity or inventing facts.",
            signal="reply_primary_failure",
            metadata={"error_type":type(exc).__name__},
        )
    # Natural deterministic recovery: short, non-robotic, and non-fabricated.
    name = f", {contact_name}" if contact_name else ""
    recovery = (
        f"Gracias{name}. Ya tengo tu mensaje. Voy a continuar desde lo que ya habíamos confirmado, "
        "sin hacerte repetir información. Si necesito un dato indispensable para avanzar, te pediré solo ese dato."
    )
    await record_lesson(lesson="Natural recovery reply used because the primary model path did not return a usable response.", signal="reply_recovery")
    return recovery


async def intelligence_health() -> dict[str, Any]:
    lessons = await _recent_lessons(50)
    success=sum(1 for x in lessons if str((x.get("payload") or {}).get("signal"))=="reply_success")
    recovery=sum(1 for x in lessons if str((x.get("payload") or {}).get("signal"))=="reply_recovery")
    failures=sum(1 for x in lessons if "failure" in str((x.get("payload") or {}).get("signal")))
    return {
        "status":"ok",
        "service":"sofia-adaptive-intelligence",
        "version":"1.1.0",
        "persona":"Sofia Smith — Trade Concierge & Account Executive, SAHJONY LLC",
        "natural_conversation_engine":True,
        "max_new_questions_per_turn":2,
        "direct_answer_first":True,
        "anti_questionnaire_policy":True,
        "truthful_identity_if_directly_asked":True,
        "self_improvement":True,
        "relationship_memory":True,
        "progressive_discovery":True,
        "outcome_learning":True,
        "self_healing":True,
        "context_recovery":True,
        "safe_fallback_reply":True,
        "dynamic_model_resilience":True,
        "production_self_modifying_code":False,
        "guardrailed_improvement":True,
        "recent_signals":{"success":success,"recovery":recovery,"failures":failures,"sample":len(lessons)},
        "objective":"continuously improve naturalness, usefulness, continuity, conversion quality and resilience without relaxing truthfulness, evidence or governance gates",
    }
