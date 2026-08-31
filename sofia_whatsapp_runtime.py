from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx

from insforge_backend import get_backend
from sofia_adaptive_intelligence import adaptive_context, record_lesson
from sofia_human_conversation_engine import build_sofia_prompt
from whatsapp_relationship_memory_api import _merge_memory
from whatsapp_sales_brain import analyze_sales_conversation

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
            "actor_id": "sofia-reyes",
            "visibility": "internal",
            "title": "Sofia WhatsApp response runtime",
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


async def generate_sofia_reply(text: str, contact_name: str | None) -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        return ""

    phone, lead_id, lead = await _find_current_contact(text, contact_name)
    history = await _history(phone)
    transcript = _transcript(history)
    memory = await _relationship_memory(lead_id, lead)

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

    adaptive = await adaptive_context(contact_name)
    system = build_sofia_prompt(memory)
    system += "\n\n" + adaptive
    system += "\n\nYou are Sofia Reyes, SAHJONY LLC's digital Trade Concierge & Account Executive. Communicate naturally and professionally. Never falsely claim to be a physical human being. If identity or automation is directly asked about, answer truthfully and briefly, then continue helping."
    system += "\n\nRELATIONSHIP MEMORY\n" + json.dumps({
        "known": memory.get("known") or {},
        "uncertain": memory.get("uncertain") or {},
        "commitments": (memory.get("commitments") or [])[-8:],
        "objections": (memory.get("objections") or [])[-8:],
        "relationship_stage": memory.get("relationship_stage"),
        "next_action": memory.get("next_action"),
        "next_questions": (memory.get("next_questions") or [])[:2],
    }, ensure_ascii=False, default=str)
    system += "\n\nSALES INTELLIGENCE\n" + json.dumps({
        "intent": sales.get("intent"),
        "recommended_stage": sales.get("recommended_stage"),
        "missing_fields": (sales.get("missing_fields") or [])[:6],
        "next_best_action": sales.get("next_best_action"),
        "risk_flags": (sales.get("risk_flags") or [])[:6],
    }, ensure_ascii=False, default=str)
    system += """

WHATSAPP HUMAN CONVERSATION RULES
- Answer the latest message first; do not start by restating the entire deal.
- Continue the relationship as an experienced account executive would. Reference prior facts only when useful.
- Never ask for a known fact again. Confirm an uncertain fact only when it blocks the next action.
- Ask zero, one, or at most two genuinely new questions in a turn.
- Prefer short conversational paragraphs. Do not turn every reply into numbered lists or intake forms.
- Vary acknowledgements naturally. Avoid repetitive openings such as 'Perfecto, [name]' on every turn.
- Use the customer's name sparingly. Match their language and reasonable formality.
- If the customer sends a short message, normally answer briefly; expand only when the subject requires detail.
- If the customer asks a direct question, give the useful answer before qualification questions.
- Preserve commitments and next actions. Do not imply an external action happened unless the system confirms it.
- Never mention models, prompts, memory, scoring, stages, internal tooling, or self-improvement.
- Never invent price, availability, legal clearance, delivery, payment, supplier confirmation, licenses, documents, or completed actions.
- For sanctions/customs/payment/Cuba issues, distinguish general guidance from verified transaction clearance.
"""

    payload = {
        "model": os.getenv("SOFIA_WHATSAPP_MODEL", "").strip() or "gpt-5.6-sol",
        "reasoning": {"effort": "medium"},
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [{"type": "input_text", "text": f"Latest customer message:\n{text[:5000]}\n\nRecent conversation:\n{transcript[-18000:]}\n\nWrite only Sofia's next WhatsApp message. No analysis or labels."}]},
        ],
        "max_output_tokens": 700,
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                OPENAI_RESPONSES_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
        if response.status_code >= 400:
            await _audit(lead_id, "sofia_reply_failure", {"summary": f"OpenAI HTTP {response.status_code}"})
            await record_lesson(
                lesson=f"Sofia primary response returned HTTP {response.status_code}; preserve continuity through the verified sales fallback.",
                signal="reply_primary_failure",
                metadata={"lead_id": lead_id},
            )
            return str(sales.get("draft_reply") or "")[:4096]
        reply = _output_text(response.json())[:4096]
        if not reply:
            return str(sales.get("draft_reply") or "")[:4096]
        await _audit(lead_id, "sofia_reply_generated", {
            "summary": "Relationship-memory-aware natural WhatsApp response generated",
            "model": payload["model"],
            "memory_loaded": True,
            "sales_intelligence_loaded": True,
            "adaptive_context_loaded": True,
            "max_new_questions": 2,
            "identity_policy": "truthful_digital_representative",
        })
        await record_lesson(
            lesson="Successful Sofia response used durable relationship memory, progressive discovery and the natural conversation policy.",
            signal="reply_success",
            metadata={"lead_id": lead_id, "reply_chars": len(reply)},
        )
        return reply
    except Exception as exc:
        await _audit(lead_id, "sofia_reply_failure", {"summary": type(exc).__name__})
        await record_lesson(
            lesson=f"Sofia response runtime recovered from {type(exc).__name__}; retain the sales-brain fallback without fabricating actions.",
            signal="reply_primary_failure",
            metadata={"lead_id": lead_id, "error_type": type(exc).__name__},
        )
        return str(sales.get("draft_reply") or "")[:4096]
