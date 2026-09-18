from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx

from insforge_backend import get_backend
from sofia_adaptive_intelligence import adaptive_context, record_lesson
from sofia_agentic_sales_os import orchestrate_sales_turn
from sofia_hermes_nim_brain import generate as hermes_generate
from sofia_hermes_nim_brain import configured as hermes_configured
from sofia_hermes_nim_brain import model_name as hermes_model_name
from sofia_human_conversation_engine import build_sofia_prompt
from sofia_track_classifier import (
    TRACK_ASK,
    TRACK_IMPORT_EXPORT,
    TRACK_MY_CUBA_CASH,
    classify_track,
    detect_language,
)
from sofia_my_cuba_cash_track import (
    IMPORT_EXPORT_TRACK_GUARD,
    MY_CUBA_CASH_SYSTEM_BLOCK,
    TRACK_ASK_GUIDANCE,
)
from sofia_cubacash_intake_client import (
    apply_intake_update,
    detect_update_intent,
    fetch_intakes,
    format_intake_summary,
    looks_like_intake_inquiry,
)
from whatsapp_relationship_memory_api import _merge_memory
from whatsapp_sales_brain import analyze_sales_conversation
from whatsapp_crm_bridge import get_contact_context, owner_update_report
from sofia_knowledge_layer import build_business_knowledge

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _output_text(data: dict[str, Any]) -> str:
    direct = str(data.get("output_text") or "").strip()
    if direct:
        return direct
    parts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"].strip())
    return "\n".join(x for x in parts if x).strip()


async def _find_current_contact(text: str, contact_name: str | None) -> tuple[str, str | None, dict[str, Any]]:
    try:
        rows = await get_backend().select(
            "whatsapp_messages",
            params={"direction": "eq.inbound", "order": "received_at.desc", "limit": "100"},
        ) or []
    except Exception:
        rows = []
    match: dict[str, Any] = {}
    for row in rows:
        if str(row.get("text") or "").strip() != text.strip():
            continue
        if contact_name and row.get("contact_name") and str(row.get("contact_name")) != contact_name:
            continue
        match = row
        break
    phone = str(match.get("phone") or "")
    if not phone:
        return "", None, {}
    lead_id = "wa_" + hashlib.sha256(phone.encode("utf-8")).hexdigest()[:24]
    try:
        leads = await get_backend().select("whatsapp_leads", params={"lead_id": f"eq.{lead_id}", "limit": "1"}) or []
    except Exception:
        leads = []
    return phone, lead_id, leads[0] if leads else {}


async def _history(phone: str) -> list[dict[str, Any]]:
    if not phone:
        return []
    try:
        rows = await get_backend().select(
            "whatsapp_messages",
            params={"phone": f"eq.{phone}", "order": "received_at.asc", "limit": "100"},
        ) or []
        return rows[-50:]
    except Exception:
        return []


def _transcript(rows: list[dict[str, Any]]) -> str:
    turns: list[str] = []
    for row in rows:
        body = str(row.get("text") or "").strip()
        if not body:
            continue
        role = "customer" if row.get("direction") == "inbound" else "sofia"
        turns.append(f"{role}: {body[:1800]}")
    return "\n".join(turns)


async def _relationship_memory(lead_id: str | None, lead: dict[str, Any]) -> dict[str, Any]:
    if not lead_id:
        return {
            "known": {}, "uncertain": {}, "missing": [], "next_questions": [],
            "commitments": [], "objections": [], "next_action": None,
            "relationship_stage": str(lead.get("status") or "NEW"),
        }
    try:
        events = await get_backend().select(
            "business_events",
            params={"lead_id": f"eq.{lead_id}", "order": "created_at.asc", "limit": "2000"},
        ) or []
    except Exception:
        events = []
    try:
        return _merge_memory(lead, events)
    except Exception:
        return {
            "known": {}, "uncertain": {}, "missing": [], "next_questions": [],
            "commitments": [], "objections": [], "next_action": None,
            "relationship_stage": str(lead.get("status") or "NEW"),
        }


async def _audit(lead_id: str | None, event_type: str, payload: dict[str, Any]) -> None:
    try:
        await get_backend().insert("business_events", {
            "event_id": f"evt_{secrets.token_urlsafe(16)}",
            "event_type": event_type,
            "source_type": "sofia_whatsapp_runtime",
            "source_id": lead_id,
            "trade_case_id": None,
            "customer_id": None,
            "lead_id": lead_id,
            "actor_role": "digital_representative",
            "actor_id": "sofia-smith",
            "visibility": "internal",
            "title": "Sofía WhatsApp executive response runtime",
            "summary": str(payload.get("summary") or event_type)[:4000],
            "action_required": False,
            "action_label": None,
            "priority": "normal",
            "event_status": "closed",
            "payload": payload,
            "created_at": _now(),
            "updated_at": _now(),
        })
    except Exception:
        pass


async def _openai_fallback(system: str, user: str) -> tuple[str, dict[str, Any]]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return "", {"provider": "openai", "configured": False}
    payload = {
        "model": os.getenv("SOFIA_WHATSAPP_MODEL", "").strip() or "gpt-5.6-sol",
        "reasoning": {"effort": "medium"},
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [{"type": "input_text", "text": user}]},
        ],
        "max_output_tokens": 700,
    }
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            OPENAI_RESPONSES_URL,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        return "", {"provider": "openai", "configured": True, "status_code": response.status_code, "model": payload["model"]}
    return _output_text(response.json())[:4096], {
        "provider": "openai", "configured": True, "status_code": response.status_code, "model": payload["model"]
    }


async def _resolve_business_track(
    text: str,
    *,
    sender_phone: str | None,
    lead_id: str | None,
    transcript: str = "",
    owner_context: bool,
) -> dict[str, Any]:
    """Classify the inbound message into a business track and build the prompt addition.

    Returns {"action": "short_circuit", "reply": str, "audit": {...}} when Sofia must
    answer deterministically (exactly one clarifying question, or an ambiguous
    multi-intake update target), otherwise
    {"action": "continue", "prompt_addition": str, "audit": {...}}.

    Track continuity: a follow-up message with no track signal of its own (e.g.
    "¿cómo va mi solicitud?") inherits the track the conversation already
    established, instead of re-asking. A message that classifies on its own
    always wins — that is how mid-conversation track switches are honored.

    Owner-context mode is unchanged: no classification, no intake access.
    """
    if owner_context:
        return {
            "action": "continue",
            "prompt_addition": "",
            "audit": {"business_track": "owner_context"},
        }

    decision = classify_track(text)
    classification_source = "message"
    if decision.track == TRACK_ASK and transcript.strip():
        inherited = classify_track(transcript[-3000:])
        if inherited.track in (TRACK_IMPORT_EXPORT, TRACK_MY_CUBA_CASH):
            decision = inherited
            classification_source = "history"
    audit: dict[str, Any] = {
        "business_track": decision.track,
        "classification_confidence": round(decision.confidence, 2),
        "classification_signals": decision.signals[:8],
        "classification_language": decision.language,
        "classification_source": classification_source,
    }

    if decision.track == TRACK_ASK:
        if not transcript.strip():
            return {
                "action": "short_circuit",
                "reply": decision.clarifying_question or "",
                "audit": audit,
            }
        return {
            "action": "continue",
            "prompt_addition": "\n\n" + TRACK_ASK_GUIDANCE.format(
                question=decision.clarifying_question or ""
            ),
            "audit": audit,
        }

    if decision.track == TRACK_IMPORT_EXPORT:
        return {
            "action": "continue",
            "prompt_addition": "\n\n" + IMPORT_EXPORT_TRACK_GUARD,
            "audit": audit,
        }

    # --- MY CUBA CASH track -------------------------------------------------
    addition = "\n\n" + MY_CUBA_CASH_SYSTEM_BLOCK
    if sender_phone:
        e164 = sender_phone if sender_phone.startswith("+") else f"+{sender_phone}"
        update_intent = detect_update_intent(text)
        try:
            intakes = await fetch_intakes(e164)
            fetch_error: str | None = None
        except Exception as exc:
            intakes = None
            fetch_error = type(exc).__name__
        if update_intent is not None:
            field, value = update_intent
            if intakes is None:
                addition += (
                    "\n\nINTAKE UPDATE REQUESTED — LOOKUP FAILED "
                    f"({fetch_error}). Tell the customer you could not verify their "
                    "request right now and will follow up; do not claim any change was made."
                )
                audit["cubacash_update"] = "lookup_failed"
            elif not intakes:
                addition += (
                    "\n\nThe customer asked to update a request, but NO intake records were "
                    "found for their number at mycubacash.com. Say so plainly and offer to "
                    "start a new request; do not invent one."
                )
                audit["cubacash_update"] = "no_intakes"
            elif len(intakes) > 1:
                return {
                    "action": "short_circuit",
                    "reply": (
                        "Veo varias solicitudes a tu nombre:\n"
                        + format_intake_summary(intakes, max_items=5)
                        + "\n¿Cuál quieres actualizar?"
                    ),
                    "audit": {**audit, "cubacash_update": "ambiguous_target"},
                }
            else:
                target_id = str(intakes[0].get("id"))
                try:
                    result = await apply_intake_update(
                        target_id, {field: value}, sender_phone_e164=e164
                    )
                except ValueError as exc:
                    # Allowlist violation = programmer error: loud in audit, safe in reply.
                    result = {"ok": False, "reason": "validation_error"}
                    audit["cubacash_validation_error"] = str(exc)[:200]
                except Exception as exc:
                    result = {"ok": False, "reason": f"transport_{type(exc).__name__}"}
                if result.get("ok"):
                    addition += (
                        "\n\nVERIFIED INTAKE UPDATE — read-back confirmed at mycubacash.com:\n"
                        + json.dumps(result["record"], ensure_ascii=False, default=str)[:2000]
                        + "\nReport this outcome truthfully and briefly; do not add details not shown above."
                    )
                    audit["cubacash_update"] = "ok"
                    audit["cubacash_intake_id"] = target_id
                else:
                    addition += (
                        "\n\nINTAKE UPDATE COULD NOT BE CONFIRMED "
                        f"(reason: {result.get('reason')}). Acknowledge without inventing details; "
                        "say the change could not be confirmed and it will be followed up."
                    )
                    audit["cubacash_update"] = "failed"
        elif looks_like_intake_inquiry(text):
            if intakes is None:
                addition += (
                    "\n\nIntake lookup temporarily unavailable — do not invent intake details; "
                    "say you will check and follow up."
                )
            elif intakes:
                addition += (
                    "\n\nVERIFIED CUSTOMER INTAKE RECORDS (mycubacash.com, read-only, newest first):\n"
                    + format_intake_summary(intakes)
                    + "\nUse only these verified records. Never invent amounts, statuses, or timelines."
                )
            else:
                addition += (
                    "\n\nNo intake records found for this sender at mycubacash.com. Say so plainly "
                    "and offer to start a new request; do not invent one."
                )
    return {"action": "continue", "prompt_addition": addition, "audit": audit}


LANGUAGE_NAMES = {"es": "Spanish", "en": "English", "fr": "French", "pt": "Portuguese"}


def detect_reply_language(text: str, transcript: str = "") -> str:
    """Language code Sofia must reply in.

    The latest customer message wins. A very short message ("ok", "sí",
    "gracias") inherits the conversation's language from the transcript.
    Defaults to 'es'.
    """
    lang = detect_language(text)
    words = re.findall(r"[a-zA-Z\u00e0-\u00ff]+", text or "")
    if len(words) < 2 and transcript.strip():
        for line in reversed(transcript.splitlines()):
            if line.startswith("customer:"):
                tail = line[len("customer:"):].strip()
                if tail:
                    lang = detect_language(tail)
                break
    return lang


def reply_language_name(text: str, transcript: str = "") -> str:
    """Human language name for the reply-language directive."""
    return LANGUAGE_NAMES.get(detect_reply_language(text, transcript), "Spanish")


def language_rule(text: str, transcript: str = "") -> str:
    """Top-priority system-prompt block forcing Sofia to answer in the
    customer's language. The model otherwise defaults to English."""
    name = reply_language_name(text, transcript)
    return (
        "LANGUAGE RULE — HIGHEST PRIORITY, OVERRIDES ALL OTHER STYLE GUIDANCE:\n"
        f"- The customer's latest message is in {name.upper()}.\n"
        f"- Write your ENTIRE reply in {name}. Every word, including greetings and closings.\n"
        "- Do NOT reply in English when the customer wrote in another language.\n"
        "- If the customer mixes languages, use the language of their latest message.\n"
    )


# ---------------------------------------------------------------------------
# OUTBOUND GUARD — permanent fix for internal-text exposure (2026-09-18)
#
# The model occasionally emits infrastructure vocabulary ("endpoints",
# "modo degradado", "plataforma canónica"), unrendered template markers,
# reasoning traces, reverses buyer/seller roles, or re-asks known facts.
# Prompt instructions alone did not prevent it, so every outbound reply now
# passes this deterministic guard before release. Anything that trips the
# guard is replaced by a short human safe-fallback message — raw model text
# with internal jargon never reaches WhatsApp.
# ---------------------------------------------------------------------------

_INTERNAL_JARGON_PATTERNS = [
    r"endpoint",
    r"modo\s+degradado",
    r"\bdegraded\b",
    r"plataforma\s+can[oó]nica",
    r"\bcanonical\b",
    r"razonamiento\s+interno",
    r"internal\s+reasoning",
    r"an[áa]lisis\s+interno",
    r"como\s+(un\s+)?modelo\s+de\s+(lenguaje|ia)",
    r"as\s+an?\s+ai\s+language\s+model",
    r"mis\s+instrucciones",
    r"system\s+prompt",
    r"prompt\s+interno",
    r"\btokens?\b",
    r"\bnvidia\b",
    r"gpt-oss",
    r"hermes\s+agent",
    r"\bopenclaw\b",
    r"\{\{\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\}\}",
]

_TRACE_PATTERNS = [
    r"<think>.*?</think>",
    r"<reasoning>.*?</reasoning>",
    r"\[INTERNAL\].*?\[/INTERNAL\]",
]

_ROLE_HINTS = (
    ("supplier", ("vende", "ofrece", "suministra", "proveedor", "supplier", "seller")),
    ("buyer", ("busca", "necesita", "compra", "quiere comprar", "buyer", "customer")),
    ("gestor", ("gestor", "intermediario", "broker", "conecta")),
    ("partner", ("partner", "socio", "red de")),
)


def _contains_internal_jargon(reply: str) -> list[str]:
    hits: list[str] = []
    for pattern in _INTERNAL_JARGON_PATTERNS:
        if re.search(pattern, reply, re.IGNORECASE | re.DOTALL):
            hits.append(pattern)
    return hits


def _strip_reasoning_traces(reply: str) -> str:
    clean = reply
    for pattern in _TRACE_PATTERNS:
        clean = re.sub(pattern, "", clean, flags=re.IGNORECASE | re.DOTALL).strip()
    return clean


def _reply_questions(reply: str) -> list[str]:
    return [q.strip() for q in re.findall(r"([^.!?\n]*\?)", reply) if q.strip()]


def _known_fact_values(memory: dict[str, Any] | None) -> list[str]:
    values: list[str] = []
    known = (memory or {}).get("known") or {}

    def _collect(value: Any) -> None:
        if isinstance(value, str) and len(value.strip()) >= 3:
            values.append(value.strip().lower())
        elif isinstance(value, (list, tuple)):
            for item in value:
                _collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                _collect(item)

    _collect(known)
    return values


def _drop_known_fact_questions(reply: str, memory: dict[str, Any] | None) -> tuple[str, int]:
    questions = _reply_questions(reply)
    if not questions:
        return reply, 0
    known_values = _known_fact_values(memory)
    known = (memory or {}).get("known") or {}
    known_keys = [str(k).strip().lower() for k in known.keys() if len(str(k).strip()) >= 3]
    known_terms = known_values + known_keys
    dropped = 0
    clean = reply
    for question in questions:
        if any(term in question.lower() for term in known_terms):
            clean = clean.replace(question, "").strip()
            dropped += 1
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, dropped


def _cap_questions(reply: str, limit: int = 2) -> tuple[str, int]:
    questions = _reply_questions(reply)
    if len(questions) <= limit:
        return reply, 0
    clean = reply
    removed = 0
    for question in questions[limit:]:
        clean = clean.replace(question, "").strip()
        removed += 1
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, removed


def _infer_contact_role(
    memory: dict[str, Any] | None,
    sales: dict[str, Any] | None,
    text: str,
) -> str | None:
    known = (memory or {}).get("known") or {}
    for key in ("role", "contact_role", "rol", "tipo_contacto"):
        value = str(known.get(key) or "").strip().lower()
        if value:
            return value
    haystack = " ".join([
        text or "",
        str((sales or {}).get("interpreted_buyer_requirement") or ""),
        str((sales or {}).get("next_best_action") or ""),
        json.dumps(known, ensure_ascii=False),
    ]).lower()
    for role, hints in _ROLE_HINTS:
        if any(hint in haystack for hint in hints):
            return role
    return None


def _safe_fallback_reply(contact_name: str | None, language: str) -> str:
    name = f" {contact_name.strip()}" if contact_name and contact_name.strip() else ""
    templates = {
        "es": f"Hola{name}, soy Sofía de SAHJONY. Disculpe el mensaje anterior. ¿En qué le puedo ayudar?",
        "en": f"Hi{name}, this is Sofia from SAHJONY. Sorry about the previous message. How can I help?",
        "fr": f"Bonjour{name}, ici Sofia de SAHJONY. Désolée pour le message précédent. Comment puis-je aider?",
        "pt": f"Olá{name}, aqui é a Sofia da SAHJONY. Desculpe a mensagem anterior. Como posso ajudar?",
    }
    return templates.get(language, templates["es"])


def apply_outbound_guard(
    reply: str,
    *,
    memory: dict[str, Any] | None,
    sales: dict[str, Any] | None,
    text: str,
    contact_name: str | None,
    language: str,
) -> tuple[str, dict[str, Any]]:
    """Deterministic outbound guard. Returns (releasable_reply, guard_report).

    Blocked replies are replaced by a short human safe-fallback message;
    internal jargon, reasoning traces, and structured blobs never go out.
    """
    report: dict[str, Any] = {
        "guard_active": True,
        "blocked": False,
        "jargon_hits": [],
        "traces_stripped": False,
        "known_fact_questions_dropped": 0,
        "excess_questions_dropped": 0,
        "fallback_used": False,
    }
    candidate = _strip_reasoning_traces(reply or "")
    if candidate != (reply or ""):
        report["traces_stripped"] = True

    hits = _contains_internal_jargon(candidate)
    if hits:
        report["blocked"] = True
        report["jargon_hits"] = hits
        report["fallback_used"] = True
        return _safe_fallback_reply(contact_name, language), report

    stripped = candidate.strip()
    if not stripped or (stripped.startswith("{") and stripped.endswith("}")):
        report["blocked"] = True
        report["fallback_used"] = True
        report["empty_or_structured"] = True
        return _safe_fallback_reply(contact_name, language), report

    cleaned, dropped = _drop_known_fact_questions(candidate, memory)
    report["known_fact_questions_dropped"] = dropped
    cleaned, excess = _cap_questions(cleaned, limit=2)
    report["excess_questions_dropped"] = excess
    if not cleaned.strip():
        report["blocked"] = True
        report["fallback_used"] = True
        return _safe_fallback_reply(contact_name, language), report
    return cleaned, report


async def _generate_sofia_reply_unguarded(
    text: str,
    contact_name: str | None,
    owner_context: bool = False,
    sender_phone: str | None = None,
    _guard_ctx: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    if not hermes_configured() and not os.getenv("OPENAI_API_KEY", "").strip():
        return "", (_guard_ctx if _guard_ctx is not None else {})

    phone, lead_id, lead = await _find_current_contact(text, contact_name)
    history = await _history(phone)
    transcript = _transcript(history)
    memory = await _relationship_memory(lead_id, lead)
    crm_context: dict[str, Any] = {
        "status": "not_resolved",
        "crm_connected": False,
        "customers": [],
        "trade_intakes": [],
    }
    if phone:
        try:
            crm_context = await get_contact_context(phone)
        except Exception:
            crm_context = {
                "status": "temporarily_unavailable",
                "crm_connected": False,
                "customers": [],
                "trade_intakes": [],
            }

    try:
        sales = await analyze_sales_conversation(
            transcript=transcript or f"customer: {text}",
            current_stage=str(memory.get("relationship_stage") or lead.get("status") or "NEW"),
            complexity="normal",
            relationship_memory=memory,
        )
    except Exception:
        sales = {
            "missing_fields": memory.get("next_questions") or [],
            "next_best_action": memory.get("next_action") or "Answer directly and move the legitimate commercial conversation one step forward.",
            "risk_flags": ["sales_intelligence_temporarily_unavailable"],
        }

    sales_plan = orchestrate_sales_turn(
        lead_id=lead_id,
        customer_text=text,
        stage=str(memory.get("relationship_stage") or lead.get("status") or "NEW"),
        memory=memory,
        sales_intelligence=sales,
        crm_context=crm_context,
    )
    if _guard_ctx is not None:
        _guard_ctx.update(
            memory=memory,
            sales=sales,
            lead_id=lead_id,
            language=detect_reply_language(text, transcript),
        )

    knowledge = await build_business_knowledge(text, crm_context)
    adaptive = await adaptive_context(contact_name)
    owner_report: dict[str, Any] | None = None
    if owner_context:
        try:
            owner_report = await owner_update_report()
        except Exception as exc:
            owner_report = {
                "status": "degraded",
                "coverage": "unknown",
                "source_states": {"owner_report": {"state": "RUNTIME_ERROR", "error_class": type(exc).__name__}},
            }
    system = build_sofia_prompt(memory)
    system = language_rule(text, transcript) + "\n" + system
    system += "\n\n" + adaptive
    system += "\n\nYou are Sofía Smith, SAHJONY GLOBAL TRADING's Executive Manager, Executive Assistant and AI Commercial Executive. Communicate naturally and professionally. Never falsely claim to be a physical human being. If identity or automation is directly asked about, answer truthfully and briefly, then continue helping."
    track_resolution = await _resolve_business_track(
        text,
        sender_phone=sender_phone,
        lead_id=lead_id,
        transcript=transcript,
        owner_context=owner_context,
    )
    track_audit: dict[str, Any] = dict(track_resolution.get("audit") or {})
    if track_resolution.get("action") == "short_circuit":
        await _audit(lead_id, "sofia_track_clarification", {
            "summary": "Sofia answered deterministically for an ambiguous business track",
            **track_audit,
        })
        return str(track_resolution.get("reply") or "")[:4096], (_guard_ctx if _guard_ctx is not None else {})
    system += str(track_resolution.get("prompt_addition") or "")
    if owner_context:
        system += "\n\nOWNER EXECUTIVE MODE\n- The current sender is the authenticated SAHJONY owner. Treat this as an internal executive request, not a customer sales intake.\n- Never ask the owner to export/upload CRM data as the first response. Use the connected SAHJONY source snapshot supplied below first.\n- Distinguish verified zero from unknown/unreadable. Never convert source failure into zero.\n- If one source is unavailable, give the best partial report from healthy sources and isolate the blocker.\n- Do not fabricate cash, revenue, profit, invoices, payments, opportunities, shipments, or system health.\n- Only ask the owner for something when it is genuinely owner-only and cannot be resolved from connected systems."
        system += "\n\nLIVE OWNER SOURCE SNAPSHOT\n" + json.dumps(owner_report or {}, ensure_ascii=False, default=str)[:30000]
    system += "\n\nRELATIONSHIP MEMORY\n" + json.dumps({
        "known": memory.get("known") or {},
        "uncertain": memory.get("uncertain") or {},
        "commitments": (memory.get("commitments") or [])[-8:],
        "objections": (memory.get("objections") or [])[-8:],
        "relationship_stage": memory.get("relationship_stage"),
        "next_action": memory.get("next_action"),
        "next_questions": (memory.get("next_questions") or [])[:2],
    }, ensure_ascii=False, default=str)
    system += "\n\nBUSINESS KNOWLEDGE PREFLIGHT — SOURCE-GROUNDED\n" + json.dumps(knowledge, ensure_ascii=False, default=str)[:24000]
    system += "\n\nCRM CONTACT CONTEXT\n" + json.dumps({
        "crm_connected": bool(crm_context.get("crm_connected")),
        "customers": (crm_context.get("customers") or [])[:3],
        "trade_intakes": (crm_context.get("trade_intakes") or [])[:8],
    }, ensure_ascii=False, default=str)
    system += "\n\nSALES INTELLIGENCE\n" + json.dumps({
        "intent": sales.get("intent"),
        "recommended_stage": sales.get("recommended_stage"),
        "missing_fields": (sales.get("missing_fields") or [])[:6],
        "next_best_action": sales.get("next_best_action"),
        "risk_flags": (sales.get("risk_flags") or [])[:6],
    }, ensure_ascii=False, default=str)
    system += "\n\nAGENTIC SALES MISSION\n" + json.dumps({
        "mission": sales_plan.get("mission"),
        "deal_score": sales_plan.get("deal_score"),
        "next_best_action": sales_plan.get("next_best_action"),
        "autonomous_actions": sales_plan.get("autonomous_actions"),
        "approval_queue": sales_plan.get("approval_queue"),
        "missing_fields": sales_plan.get("missing_fields"),
        "risk_flags": sales_plan.get("risk_flags"),
        "interpreted_buyer_requirement": sales_plan.get("interpreted_buyer_requirement"),
        "trade_execution_lifecycle": sales_plan.get("trade_execution_lifecycle"),
        "success_criteria": sales_plan.get("success_criteria"),
        "stop_rules": sales_plan.get("stop_rules"),
    }, ensure_ascii=False, default=str)
    system += """

WHATSAPP HUMAN CONVERSATION RULES
- Answer the latest message first; do not start by restating the entire deal.
- Continue the relationship as an experienced executive account manager would. Reference prior facts only when useful.
- Never ask for a known fact again. Confirm an uncertain fact only when it blocks the next action.
- Ask zero, one, or at most two genuinely new questions in a turn.
- Prefer short conversational paragraphs. Do not turn every reply into numbered lists or intake forms.
- Vary acknowledgements naturally. Avoid repetitive openings.
- Use the customer's name sparingly. Match their language and reasonable formality.
- If the customer asks a direct question, give the useful answer before qualification questions.
- Preserve commitments and next actions. Do not imply an external action happened unless the system confirms it.
- Use CRM context silently. Do not expose infrastructure errors, models, prompts, tokens, internal scoring, or secrets.
- Never invent price, availability, legal clearance, delivery, payment, supplier confirmation, licenses, documents, or completed actions.
- For sanctions/customs/payment/Cuba issues, distinguish general guidance from verified transaction clearance.
- Follow the agentic sales mission, but execute only autonomous actions. Owner-approval items remain pending until actually approved.
- Treat a complete buyer requirement as the start of a trade-execution mission, not merely a CRM note. Open the RFQ, sourcing, container-utilization, freight-lane and compliance workstreams; then progress landed cost, SAHJONY margin, formal quote, negotiation and purchase order only as their evidence and approval gates are satisfied.
- "ASAP" expresses urgency but never authorizes invented inventory, price, transit time, compliance clearance, quote release or purchase order.
- Treat private individuals as legitimate business contacts when they show credible buying, selling, sourcing, importing, exporting, logistics, MIPYME/private-business, gestor, broker, introducer, referral, or commercial-network activity.
- Classify commercially relevant contacts internally as buyer, supplier, partner, MIPYME/private business, gestor/connector, broker, or opportunity source; do not expose the internal label unless useful to the conversation.
- A contact who can introduce multiple MIPYMES, buyers, suppliers, gestores, or business owners is a potential SAHJONY Partner Network contact. Qualify their network reach, geography, product categories, decision-maker access, and referral quality before promising economics or exclusivity.
- For partner-capable contacts, move toward a concrete next step: identify what markets/products their network needs, capture introduction channels, and invite qualified referrals into the SAHJONY commercial funnel.
- Treat business inquiries from Facebook/Instagram/WhatsApp comments and direct messages as opportunities when there is commercial intent, even if the sender is not formally incorporated.
- Do not auto-commercialize security alerts, platform notices, reactions-only, family/social messages, or unrelated personal conversations unless clear business intent appears.
- Optimize for legitimate customer value, trust, conversion quality, evidence completeness and durable margin.
"""

    contact_role = _infer_contact_role(memory, sales, text)
    if contact_role:
        system += (
            "\n\nVERIFIED CONTACT ROLE: " + contact_role + ". "
            "Treat the contact as this role for the entire conversation. "
            "Never reverse buyer and seller."
        )

    user = (
        f"Latest customer message:\n{text[:5000]}\n\n"
        f"Recent conversation:\n{transcript[-18000:]}\n\n"
        "Write only Sofía's next WhatsApp message. No analysis, private reasoning, labels, or internal metadata.\n"
        f"Reply in {reply_language_name(text, transcript)}."
    )

    try:
        reply, meta = await hermes_generate(system=system, user=user, max_tokens=900, temperature=0.6)
        if not reply:
            fallback, fallback_meta = await _openai_fallback(system, user)
            reply = fallback
            meta = {"primary": meta, "fallback": fallback_meta}
        if not reply:
            await _audit(lead_id, "sofia_reply_failure", {"summary": "NVIDIA NIM and OpenAI fallback returned no usable reply"})
            await record_lesson(
                lesson="Sofía inference providers returned no usable reply; preserve continuity through the verified sales fallback.",
                signal="reply_primary_failure",
                metadata={"lead_id": lead_id},
            )
            return str(sales.get("draft_reply") or "")[:4096], (_guard_ctx if _guard_ctx is not None else {})

        reply = reply[:4096]
        await _audit(lead_id, "sofia_reply_generated", {
            "summary": "Hermes-style NVIDIA NIM executive response generated",
            "primary_provider": "nvidia_nim" if hermes_configured() else "openai_fallback",
            "primary_model": hermes_model_name() if hermes_configured() else None,
            "inference": meta,
            "memory_loaded": True,
            "crm_context_loaded": bool(crm_context.get("crm_connected")),
            "sales_intelligence_loaded": True,
            "adaptive_context_loaded": True,
            "business_track": track_audit.get("business_track"),
            "classification_confidence": track_audit.get("classification_confidence"),
            "classification_signals": track_audit.get("classification_signals"),
            "cubacash_update": track_audit.get("cubacash_update"),
            "agentic_sales_plan": sales_plan,
            "hermes_style_agentic_loop": True,
            "max_new_questions": 2,
            "identity_policy": "truthful_digital_representative",
            "outbound_guard": "pending_wrapper_verification",
        })
        await record_lesson(
            lesson="Successful Sofía response used the Hermes-style cognition loop with durable relationship memory, CRM context, progressive discovery and guarded executive autonomy.",
            signal="reply_success",
            metadata={"lead_id": lead_id, "reply_chars": len(reply), "model": hermes_model_name() if hermes_configured() else "fallback"},
        )
        return reply, (_guard_ctx if _guard_ctx is not None else {})
    except Exception as exc:
        try:
            fallback, _ = await _openai_fallback(system, user)
            if fallback:
                return fallback[:4096], (_guard_ctx if _guard_ctx is not None else {})
        except Exception:
            pass
        await _audit(lead_id, "sofia_reply_failure", {"summary": type(exc).__name__})
        await record_lesson(
            lesson=f"Sofía Hermes/NIM runtime recovered from {type(exc).__name__}; retain the sales-brain fallback without fabricating actions.",
            signal="reply_primary_failure",
            metadata={"lead_id": lead_id, "error_type": type(exc).__name__},
        )
        return str(sales.get("draft_reply") or "")[:4096], (_guard_ctx if _guard_ctx is not None else {})


async def generate_sofia_reply(
    text: str,
    contact_name: str | None,
    owner_context: bool = False,
    sender_phone: str | None = None,
) -> str:
    """Public entry point. Every generated reply passes the deterministic
    outbound guard before release — internal jargon, reasoning traces, and
    structured blobs are blocked and replaced by a human safe-fallback."""
    guard_ctx: dict[str, Any] = {}
    reply, guard_ctx = await _generate_sofia_reply_unguarded(
        text, contact_name, owner_context, sender_phone, guard_ctx
    )
    language = guard_ctx.get("language") or detect_reply_language(text, "")
    clean, report = apply_outbound_guard(
        reply,
        memory=guard_ctx.get("memory"),
        sales=guard_ctx.get("sales"),
        text=text,
        contact_name=contact_name,
        language=language,
    )
    await _audit(guard_ctx.get("lead_id"), "sofia_outbound_guard", {
        "summary": "Outbound guard verdict on generated WhatsApp reply",
        **report,
        "private_reasoning_exposed": False,
        "reply_chars": len(clean),
    })
    return clean
