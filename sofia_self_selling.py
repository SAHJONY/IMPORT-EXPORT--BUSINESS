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


# ============================================================================
# Opportunity scanner + governed follow-up draft queue (self-selling v2).
#
# scan_opportunities() finds warm/dormant leads. draft_followup() generates a
# short Spanish-first WhatsApp follow-up draft. Drafts enter an approval queue;
# NOTHING SENDS AUTONOMOUSLY, EVER. There is intentionally no send function in
# this module: approved drafts are handed to the owner (or the governed owner
# UI) for the actual send.
#
# Business separation: every draft is tagged to exactly one business track
# ("import_export" or "my_cuba_cash"). Ambiguous leads are excluded, never
# blended.
#
# Identity: Sofia is "Sofia Smith, Executive Manager of SAHJONY LLC"; the
# owner is "Juan Gonzalez, Chairman and owner of SAHJONY LLC". Retired
# initiatives (e.g. PRIMO) must never appear in drafts.
# ============================================================================

from datetime import datetime, timedelta, timezone  # noqa: E402

from sofia_self_improvement import (  # noqa: E402
    OWNER_IDENTITY,
    RETIRED_INITIATIVES,
    SOFIA_IDENTITY,
    check_identity_compliant,
)

BUSINESS_TRACKS = ("import_export", "my_cuba_cash")

# Real CRM tables behind the stubbed scanner interface.
REAL_CRM_TABLES = {
    "import_export": "trade_rfq_intakes",
    "my_cuba_cash": "cuba_partner_accounts",
}

WARM_AFTER_DAYS = 7
DORMANT_AFTER_DAYS = 30
ENGAGEABLE_STATUSES = {"new", "contacted", "quoted", "follow_up"}

DRAFT_STATUS_PENDING = "pending"
DRAFT_STATUS_APPROVED = "approved"
DRAFT_STATUS_REJECTED = "rejected"

_DRAFT_QUEUE: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) <= 4:
        return "****"
    return "*" * (len(digits) - 4) + digits[-4:]


def classify_track(lead: dict[str, Any]) -> str | None:
    """Assign exactly one business track, or None when ambiguous.

    Explicit ``business_track`` wins. Otherwise utm/source hints are used only
    when they point to a single track. Conflicting or missing signals -> None
    (lead is excluded from drafting, never blended).
    """
    explicit = str(lead.get("business_track") or "").strip().lower()
    if explicit in BUSINESS_TRACKS:
        return explicit
    haystack = " ".join(
        str(lead.get(k) or "")
        for k in ("utm_source", "utm_medium", "utm_campaign", "source", "referrer")
    ).lower()
    hints_import = [h for h in ("sahjony", "import", "trade", "rfq") if h in haystack]
    hints_cash = [h for h in ("mycubacash", "my_cuba_cash", "my cuba cash", "cash") if h in haystack]
    if hints_cash and not hints_import:
        return "my_cuba_cash"
    if hints_import and not hints_cash:
        return "import_export"
    return None


def _days_since(value: Any, now: datetime) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, int((now - dt).total_seconds() // 86400))


def scan_opportunities(
    crm_source: Any = None,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Find warm/dormant engageable leads.

    ``crm_source`` is a callable returning a list of lead dicts. When None, no
    live CRM is read and an empty list is returned. Real wiring:
    - import_export -> ``trade_rfq_intakes`` table
    - my_cuba_cash  -> ``cuba_partner_accounts`` table
    Lead dict fields used: lead_id, name, phone, status, opted_out,
    last_contact_at, business_track, utm_*, source, product_interest.
    """
    now = now or datetime.now(timezone.utc)
    leads: list[dict[str, Any]] = []
    if crm_source is not None:
        try:
            leads = list(crm_source() or [])
        except Exception:
            leads = []
    opportunities: list[dict[str, Any]] = []
    for lead in leads:
        if not isinstance(lead, dict):
            continue
        if lead.get("opted_out"):
            continue
        status = str(lead.get("status") or "").strip().lower()
        if status not in ENGAGEABLE_STATUSES:
            continue
        track = classify_track(lead)
        if track is None:
            continue  # ambiguous business track: excluded, never blended
        days = _days_since(lead.get("last_contact_at"), now)
        if days is None:
            warmth = "warm"  # never contacted: treat as warm, not dormant
        elif days >= DORMANT_AFTER_DAYS:
            warmth = "dormant"
        elif days >= WARM_AFTER_DAYS:
            warmth = "warm"
        else:
            continue  # contacted recently: not a re-engagement opportunity
        opportunities.append(
            {
                "lead_id": lead.get("lead_id"),
                "name": lead.get("name"),
                "phone_masked": _mask_phone(lead.get("phone")),
                "business_track": track,
                "warmth": warmth,
                "days_since_contact": days,
                "status": status,
                "product_interest": lead.get("product_interest"),
                "source_table": REAL_CRM_TABLES[track],
                "reason": f"{warmth} lead ({days if days is not None else 'never'} days since contact)",
            }
        )
    return opportunities


def _followup_template(opportunity: dict[str, Any], language: str) -> str:
    name = (opportunity.get("name") or "").strip()
    greeting_name = f" {name}" if name else ""
    product = (opportunity.get("product_interest") or "").strip()
    product_line = (
        f" Sobre {product}, sigo atenta por si quieres retomar la conversación."
        if product
        else " Sigo atenta por si quieres retomar la conversación."
    )
    if language == "es":
        return (
            f"Hola{greeting_name}, soy Sofia Smith de SAHJONY LLC."
            f"{product_line} ¿Te ayudo con el siguiente paso?"
        )
    return (
        f"Hello{greeting_name}, this is Sofia Smith from SAHJONY LLC."
        f"{' Regarding ' + product + ', ' if product else ' '}"
        "Happy to help with the next step if you'd like to resume."
    )


def draft_followup(
    opportunity: dict[str, Any],
    *,
    language: str = "es",
) -> dict[str, Any]:
    """Generate a short follow-up draft for one opportunity (never sends).

    Spanish-first: ``my_cuba_cash`` drafts must always be Spanish. Drafts carry
    no prices, providers, timelines, addresses, or registration data — none are
    invented here. Raises ValueError on invalid track, non-Spanish Cuba draft,
    or retired-initiative contamination.
    """
    track = opportunity.get("business_track")
    if track not in BUSINESS_TRACKS:
        raise ValueError(f"draft requires exactly one business track, got {track!r}")
    if track == "my_cuba_cash" and language != "es":
        raise ValueError("my_cuba_cash drafts must be Spanish-first (es)")
    text = _followup_template(opportunity, language)
    violations = check_identity_compliant(text)
    if violations:
        raise ValueError(f"draft failed identity compliance: {violations}")
    draft_id = f"draft_{secrets.token_urlsafe(8)}"
    return {
        "draft_id": draft_id,
        "business_track": track,
        "lead_id": opportunity.get("lead_id"),
        "lead_name": opportunity.get("name"),
        "phone_masked": opportunity.get("phone_masked"),
        "warmth": opportunity.get("warmth"),
        "language": language,
        "text": text,
        "signed_as": SOFIA_IDENTITY,
        "owner": OWNER_IDENTITY,
        "status": DRAFT_STATUS_PENDING,
        "created_at": _now_iso(),
        "approved_by": None,
        "approved_at": None,
        "rejected_reason": None,
        # NOTE: there is intentionally no send step. Approved drafts are handed
        # to the owner / governed owner UI. Nothing sends autonomously, ever.
    }


def queue_draft(draft: dict[str, Any]) -> str:
    """Place a pending draft in the approval queue. Returns the draft id."""
    if not isinstance(draft, dict) or not draft.get("draft_id"):
        raise ValueError("queue_draft requires a draft dict with draft_id")
    if draft.get("status") != DRAFT_STATUS_PENDING:
        raise ValueError("only pending drafts can be queued")
    if draft.get("business_track") not in BUSINESS_TRACKS:
        raise ValueError("draft must carry exactly one business track")
    _DRAFT_QUEUE[draft["draft_id"]] = draft
    return draft["draft_id"]


def get_draft(draft_id: str) -> dict[str, Any] | None:
    return _DRAFT_QUEUE.get(draft_id)


def list_pending_drafts(track: str | None = None) -> list[dict[str, Any]]:
    """List pending drafts, optionally filtered to one business track."""
    if track is not None and track not in BUSINESS_TRACKS:
        raise ValueError(f"unknown business track {track!r}")
    return [
        d
        for d in _DRAFT_QUEUE.values()
        if d.get("status") == DRAFT_STATUS_PENDING
        and (track is None or d.get("business_track") == track)
    ]


def approve_draft(draft_id: str, approver: str) -> dict[str, Any]:
    """Approve a pending draft for owner/governed-UI sending. Does not send."""
    draft = _DRAFT_QUEUE.get(draft_id)
    if draft is None:
        raise KeyError(f"unknown draft {draft_id!r}")
    if draft.get("status") != DRAFT_STATUS_PENDING:
        raise ValueError(f"draft {draft_id!r} is not pending (status={draft.get('status')})")
    if not approver:
        raise ValueError("approver is required")
    draft["status"] = DRAFT_STATUS_APPROVED
    draft["approved_by"] = approver
    draft["approved_at"] = _now_iso()
    return draft


def reject_draft(draft_id: str, reason: str) -> dict[str, Any]:
    """Reject a pending draft with a reason. Does not send."""
    draft = _DRAFT_QUEUE.get(draft_id)
    if draft is None:
        raise KeyError(f"unknown draft {draft_id!r}")
    if draft.get("status") != DRAFT_STATUS_PENDING:
        raise ValueError(f"draft {draft_id!r} is not pending (status={draft.get('status')})")
    draft["status"] = DRAFT_STATUS_REJECTED
    draft["rejected_reason"] = reason or "no reason given"
    return draft


def clear_draft_queue() -> None:
    """Empty the draft queue (tests / operational reset)."""
    _DRAFT_QUEUE.clear()
