"""Sofia 360° salesperson — escalation protocol.

When Sofia hits something she must not handle alone, she stops and briefs
Juan. She never improvises past her authority: no binding commitments, no
price below floors, no legal/customs determinations, no invented facts.

An escalation produces a ONE-SCREEN owner brief:
- who: contact name + phone (owner channel — full detail is fine here)
- business: which business this belongs to (never cross-filed)
- trigger: which playbook trigger fired
- what_they_want: the customer's ask, in their words (cited)
- deal_value: amounts mentioned, or "unknown"
- what_sofia_tried: what she already did in this conversation
- what_she_needs: the EXACT decision/action needed from Juan
- suggested_reply: a draft Juan can approve or edit — Sofia does NOT send it

Briefs are recorded as business_events (visibility internal/owner,
action_required=True, priority=high) so they surface in the existing owner
flow. Recording is the delivery mechanism — this module never sends a
WhatsApp message itself.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from sofia_sales_playbooks import TRACKS, escalation_triggers

PRIORITY_BY_TRIGGER = {
    "fraud_signal": "critical",
    "below_floor_offer": "high",
    "hot_lead": "high",
    "price_acceptance": "high",
    "compliance_flag": "high",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def known_triggers(business: str) -> tuple[str, ...]:
    """Trigger names defined for a business. Unknown business -> ValueError."""
    if business not in TRACKS:
        raise ValueError(f"Unknown business: {business!r}. Known: {TRACKS}")
    return tuple(t["trigger"] for t in escalation_triggers(business))


def trigger_definition(business: str, trigger: str) -> dict[str, Any]:
    """The playbook's definition of a trigger (when it fires)."""
    for item in escalation_triggers(business):
        if item["trigger"] == trigger:
            return dict(item)
    raise ValueError(f"Unknown trigger {trigger!r} for business {business!r}")


def build_owner_brief(
    *,
    business: str,
    trigger: str,
    profile: dict[str, Any] | None = None,
    customer_ask: str | None = None,
    ask_source: str | None = None,
    what_sofia_tried: list[str] | None = None,
    contact_name: str | None = None,
    phone: str | None = None,
    language: str = "es",
) -> dict[str, Any]:
    """Build the one-screen owner brief for an escalation.

    ``profile`` is a sofia_customer_360 profile for the SAME business.
    Raises ValueError when the profile belongs to a different business —
    escalations never cross-file.
    """
    if business not in TRACKS:
        raise ValueError(f"Unknown business: {business!r}. Known: {TRACKS}")
    definition = trigger_definition(business, trigger)
    profile = profile or {}
    if profile.get("business") and profile["business"] != business:
        raise ValueError(
            f"Profile business {profile['business']!r} does not match "
            f"escalation business {business!r} — refusing to cross-file."
        )

    amounts = [a.get("amount") for a in (profile.get("amounts_mentioned") or []) if a.get("amount")]
    deal_value = ", ".join(amounts[:3]) if amounts else "unknown"

    tried = [t for t in (what_sofia_tried or []) if _clean(t)]
    lang = language if language in ("es", "en") else "es"

    if lang == "es":
        needs_line = (
            "Decisión/acción exacta que necesito de ti: "
            f"{definition['brief']} Responde a este aviso con tu decisión."
        )
    else:
        needs_line = (
            "Exact decision/action I need from you: "
            f"{definition['brief']} Reply to this brief with your decision."
        )

    brief = {
        "brief_id": f"esc_{secrets.token_urlsafe(12)}",
        "created_at": _now(),
        "business": business,
        "trigger": trigger,
        "trigger_when": definition["when"],
        "priority": PRIORITY_BY_TRIGGER.get(trigger, "normal"),
        "who": {
            "contact_name": _clean(contact_name) or _clean(profile.get("contact_name")) or "unknown",
            "phone": _clean(phone),
        },
        "what_they_want": _clean(customer_ask) or "see conversation",
        "ask_source": ask_source,
        "deal_value": deal_value,
        "deal_stage": profile.get("deal_stage") or "NEW",
        "language": profile.get("language") or lang,
        "what_sofia_tried": tried,
        "what_she_needs": needs_line,
        "suggested_reply": None,  # set by caller when a draft exists; never auto-sent
        "sent_to_customer": False,  # invariant: escalations never message the customer
    }
    return brief


async def record_escalation(brief: dict[str, Any], lead_id: str | None = None) -> dict[str, Any]:
    """Persist the brief to the owner-visible queue. Returns a status dict.

    The queue is business_events with action_required=True — the existing
    owner flow surfaces these. This function never sends a message.
    """
    try:
        from insforge_backend import get_backend

        row = {
            "event_id": f"evt_{secrets.token_urlsafe(16)}",
            "event_type": "sofia_escalation",
            "source_type": "sofia_360_salesperson",
            "source_id": brief.get("brief_id"),
            "trade_case_id": None,
            "customer_id": None,
            "lead_id": lead_id,
            "actor_role": "system",
            "actor_id": "sofia-360-salesperson",
            "visibility": "owner",
            "title": f"Sofia escalation: {brief.get('trigger')} ({brief.get('business')})",
            "summary": (
                f"{brief.get('who', {}).get('contact_name')}: "
                f"{brief.get('what_they_want')}"[:4000]
            ),
            "action_required": True,
            "action_label": brief.get("what_she_needs"),
            "priority": brief.get("priority") or "normal",
            "event_status": "open",
            "payload": {"brief": brief, "business": brief.get("business")},
            "created_at": _now(),
            "updated_at": _now(),
        }
        await get_backend().insert("business_events", row)
        return {"ok": True, "event_id": row["event_id"], "brief_id": brief.get("brief_id")}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "brief_id": brief.get("brief_id")}


def escalation_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "sofia-escalation-protocol",
        "version": "1.0.0",
        "briefs_recorded_not_sent": True,
        "customer_never_messaged": True,
        "tracks": list(TRACKS),
    }
