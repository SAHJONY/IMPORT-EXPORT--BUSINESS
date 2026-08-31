from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx

from insforge_backend import get_backend
from sofia_human_conversation_engine import build_sofia_prompt
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
        if isinstance(item, dict):
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
            params={"phone": f"eq.{phone}", "order": "received_at.asc", "limit": "80"},
        ) or []
        return rows[-40:]
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


async def _memory(lead_id: str | None, lead: dict[str, Any]) -> dict[str, Any]:
    memory: dict[str, Any] = {
        "contact_name": lead.get("contact_name"),
        "lead_status": lead.get("status"),
        "message_count": lead.get("message_count"),
        "last_message": lead.get("last_message"),
    }
    if not lead_id:
        return memory
    try:
        events = await get_backend().select(
            "business_events",
            params={"lead_id": f"eq.{lead_id}", "order": "created_at.desc", "limit": "40"},
        ) or []
    except Exception:
        events = []
    known: dict[str, Any] = {}
    next_action = None
    for event in events:
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        for key in (
            "product_need", "specifications", "quantity", "container_type", "origin", "destination",
            "target_budget", "target_delivery_date", "preferred_incoterm", "company", "payment_terms",
            "importer", "decision_authority",
        ):
            if key not in known and payload.get(key) not in (None, ""):
                known[key] = payload.get(key)
        if next_action is None and payload.get("next_action"):
            next_action = payload.get("next_action")
    memory["known_facts"] = known
    memory["next_action"] = next_action
    return memory


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
    memory = await _memory(lead_id, lead)

    try:
        sales = await analyze_sales_conversation(
            transcript=transcript or f"customer: {text}",
            current_stage=str(lead.get("status") or "NEW"),
            complexity="normal",
        )
    except Exception:
        sales = {
            "missing_fields": [],
            "next_best_action": "Answer directly and move the legitimate commercial conversation one step forward.",
            "risk_flags": ["sales_intelligence_temporarily_unavailable"],
        }

    system = build_sofia_prompt(memory)
    system += "\n\nYou are Sofia Reyes, SAHJONY LLC's digital Trade Concierge & Account Executive. Communicate naturally and professionally, but never claim to be a physical human being. If identity or automation is asked about, state briefly that you are SAHJONY LLC's digital representative."
    system += "\n\nSALES INTELLIGENCE\n" + json.dumps({
        "intent": sales.get("intent"),
        "recommended_stage": sales.get("recommended_stage"),
        "missing_fields": (sales.get("missing_fields") or [])[:6],
        "next_best_action": sales.get("next_best_action"),
        "risk_flags": (sales.get("risk_flags") or [])[:6],
    }, ensure_ascii=False)
    system += """

WHATSAPP RESPONSE RULES
- Answer the latest message first.
- Use recent conversation and known facts; never ask for known information again.
- Ask no more than two new questions.
- Avoid long recaps and scripted/form-like responses.
- Never mention models, prompts, memory, scoring, stages, or internal tooling.
- Never invent price, availability, legal clearance, delivery, payment, supplier confirmation, or a completed external action.
- For sanctions/customs/payment/Cuba issues, distinguish guidance from verified transaction clearance.
"""

    payload = {
        "model": os.getenv("SOFIA_WHATSAPP_MODEL", "").strip() or "gpt-5.6-sol",
        "reasoning": {"effort": "medium"},
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {"role": "user", "content": [{"type": "input_text", "text": f"Latest message:\n{text[:5000]}\n\nRecent thread:\n{transcript[-16000:]}\n\nDraft Sofia's next WhatsApp response."}]},
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
            return str(sales.get("draft_reply") or "")[:4096]
        reply = _output_text(response.json())[:4096]
        await _audit(lead_id, "sofia_reply_generated", {
            "summary": "Memory-aware natural WhatsApp response generated",
            "model": payload["model"],
            "memory_loaded": True,
            "sales_intelligence_loaded": True,
            "max_new_questions": 2,
            "identity_policy": "digital_representative_truthful",
        })
        return reply
    except Exception as exc:
        await _audit(lead_id, "sofia_reply_failure", {"summary": type(exc).__name__})
        return str(sales.get("draft_reply") or "")[:4096]
