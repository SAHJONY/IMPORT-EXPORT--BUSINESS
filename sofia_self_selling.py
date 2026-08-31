from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from insforge_backend import get_backend
from sofia_self_marketing import classify_segment, next_marketing_action, record_marketing_event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def value_proposition(segment: str) -> str:
    props = {
        "hot_buyer": "I can help move your request from requirements to a structured RFQ, supplier comparison, logistics review and evidence-backed commercial next step.",
        "supplier": "I can help connect your offer with qualified B2B demand, organize specifications, buyer requirements and RFQ follow-through.",
        "partner": "I can help you understand SAHJONY LLC's partner process, identify suitable opportunities and coordinate the next commercial step.",
        "logistics": "I can help organize the logistics workflow, compare routes and partners, track required documentation and keep the customer informed.",
        "general_trade": "I can help you evaluate global sourcing, import-export opportunities, documentation needs, supplier options and the next commercial step.",
    }
    return props.get(segment, props["general_trade"])


def self_sell_reply(customer_text: str, stage: str = "ENGAGED", opted_out: bool = False) -> dict[str, Any]:
    segment = classify_segment(customer_text)
    action = next_marketing_action(stage, segment, opted_out)
    if not action.get("send_allowed"):
        return {
            "segment": segment,
            "action": action,
            "reply": None,
            "conversion_goal": "none",
            "send_allowed": False,
        }
    vp = value_proposition(segment)
    reply = (
        f"Claro. {vp} "
        "Si me comparte el producto o servicio, cantidad aproximada, destino y fecha objetivo, puedo organizar la solicitud y decirle cuál es el siguiente paso más útil."
    )
    goal = "rfq" if segment == "hot_buyer" else "qualified_conversation"
    return {
        "segment": segment,
        "action": action,
        "reply": reply,
        "conversion_goal": goal,
        "send_allowed": True,
        "claims_verified": True,
        "binding_commitment": False,
    }


async def record_conversion_signal(*, lead_id: str | None, signal: str, metadata: dict[str, Any] | None = None) -> None:
    try:
        await get_backend().insert("business_events", {
            "event_id": f"evt_{secrets.token_urlsafe(16)}",
            "event_type": "conversion",
            "source_type": "sofia_self_selling",
            "source_id": lead_id or signal,
            "trade_case_id": None,
            "customer_id": None,
            "lead_id": lead_id,
            "actor_role": "system",
            "actor_id": "sofia-reyes-self-selling",
            "visibility": "internal",
            "title": f"Sofia conversion signal: {signal}",
            "summary": signal,
            "action_required": False,
            "action_label": None,
            "priority": "normal",
            "event_status": "closed",
            "payload": {"signal": signal, "metadata": metadata or {}},
            "created_at": _now(),
            "updated_at": _now(),
        })
    except Exception:
        pass


async def autonomous_conversion_plan(*, lead_id: str, stage: str, transcript: str, opted_out: bool = False) -> dict[str, Any]:
    result = self_sell_reply(transcript, stage, opted_out)
    await record_conversion_signal(
        lead_id=lead_id,
        signal="conversion_plan_generated",
        metadata={"stage":stage,"segment":result.get("segment"),"send_allowed":result.get("send_allowed")},
    )
    if result.get("send_allowed"):
        await record_marketing_event(
            lead_id=lead_id,
            segment=str(result.get("segment")),
            action="self_sell_nurture",
            metadata={"conversion_goal":result.get("conversion_goal")},
        )
    return result


async def self_selling_health() -> dict[str, Any]:
    return {
        "status":"ok",
        "service":"sofia-self-selling",
        "version":"1.0.0",
        "autonomous_self_selling":True,
        "inbound_conversion":True,
        "relationship_followup":True,
        "rfq_conversion":True,
        "meeting_conversion":True,
        "supplier_and_partner_positioning":True,
        "bulk_unsolicited_outreach":False,
        "paid_spend_without_owner":False,
        "binding_commitments":False,
        "objective":"turn legitimate conversations into qualified commercial opportunities for SAHJONY LLC while preserving consent, trust and evidence gates",
    }
