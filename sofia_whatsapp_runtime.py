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
from sofia_agentic_sales_os import orchestrate_sales_turn
from sofia_hermes_nim_brain import generate as hermes_generate
from sofia_hermes_nim_brain import configured as hermes_configured
from sofia_hermes_nim_brain import model_name as hermes_model_name
from sofia_human_conversation_engine import build_sofia_prompt
from whatsapp_relationship_memory_api import _merge_memory
from whatsapp_sales_brain import analyze_sales_conversation
from whatsapp_crm_bridge import get_contact_context

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


async def generate_sofia_reply(text: str, contact_name: str | None) -> str:
    if not hermes_configured() and not os.getenv("OPENAI_API_KEY", "").strip():
        return ""

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

    adaptive = await adaptive_context(contact_name)
    system = build_sofia_prompt(memory)
    system += "\n\n" + adaptive
    system += "\n\nYou are Sofía Smith, SAHJONY LLC's Executive Manager, Executive Assistant and AI Commercial Executive. Communicate naturally and professionally. Never falsely claim to be a physical human being. If identity or automation is directly asked about, answer truthfully and briefly, then continue helping."
    system += "\n\nRELATIONSHIP MEMORY\n" + json.dumps({
        "known": memory.get("known") or {},
        "uncertain": memory.get("uncertain") or {},
        "commitments": (memory.get("commitments") or [])[-8:],
        "objections": (memory.get("objections") or [])[-8:],
        "relationship_stage": memory.get("relationship_stage"),
        "next_action": memory.get("next_action"),
        "next_questions": (memory.get("next_questions") or [])[:2],
    }, ensure_ascii=False, default=str)
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
- Treat private individuals as legitimate business contacts when they show credible buying, selling, sourcing, importing, exporting, logistics, MIPYME/private-business, gestor, broker, introducer, referral, or commercial-network activity.
- Classify commercially relevant contacts internally as buyer, supplier, partner, MIPYME/private business, gestor/connector, broker, or opportunity source; do not expose the internal label unless useful to the conversation.
- A contact who can introduce multiple MIPYMES, buyers, suppliers, gestores, or business owners is a potential SAHJONY Partner Network contact. Qualify their network reach, geography, product categories, decision-maker access, and referral quality before promising economics or exclusivity.
- For partner-capable contacts, move toward a concrete next step: identify what markets/products their network needs, capture introduction channels, and invite qualified referrals into the SAHJONY commercial funnel.
- Treat business inquiries from Facebook/Instagram/WhatsApp comments and direct messages as opportunities when there is commercial intent, even if the sender is not formally incorporated.
- Do not auto-commercialize security alerts, platform notices, reactions-only, family/social messages, or unrelated personal conversations unless clear business intent appears.
- Optimize for legitimate customer value, trust, conversion quality, evidence completeness and durable margin.
"""

    user = (
        f"Latest customer message:\n{text[:5000]}\n\n"
        f"Recent conversation:\n{transcript[-18000:]}\n\n"
        "Write only Sofía's next WhatsApp message. No analysis, private reasoning, labels, or internal metadata."
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
            return str(sales.get("draft_reply") or "")[:4096]

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
            "agentic_sales_plan": sales_plan,
            "hermes_style_agentic_loop": True,
            "max_new_questions": 2,
            "identity_policy": "truthful_digital_representative",
            "private_reasoning_exposed": False,
        })
        await record_lesson(
            lesson="Successful Sofía response used the Hermes-style cognition loop with durable relationship memory, CRM context, progressive discovery and guarded executive autonomy.",
            signal="reply_success",
            metadata={"lead_id": lead_id, "reply_chars": len(reply), "model": hermes_model_name() if hermes_configured() else "fallback"},
        )
        return reply
    except Exception as exc:
        try:
            fallback, _ = await _openai_fallback(system, user)
            if fallback:
                return fallback[:4096]
        except Exception:
            pass
        await _audit(lead_id, "sofia_reply_failure", {"summary": type(exc).__name__})
        await record_lesson(
            lesson=f"Sofía Hermes/NIM runtime recovered from {type(exc).__name__}; retain the sales-brain fallback without fabricating actions.",
            signal="reply_primary_failure",
            metadata={"lead_id": lead_id, "error_type": type(exc).__name__},
        )
        return str(sales.get("draft_reply") or "")[:4096]
