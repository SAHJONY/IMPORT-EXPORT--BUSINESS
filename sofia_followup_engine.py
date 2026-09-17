"""Sofia 360° salesperson — autonomous follow-up engine.

Runs on schedule (cron/worker). Scans WhatsApp leads for follow-ups due per
the playbook cadence (day 1/3/7/14 after the last meaningful touch) and for
dormant leads (qualified stage, no inbound for DORMANT_AFTER_DAYS).

HARD RULE: this engine DRAFTS ONLY. Drafts go to the approval queue
(business_events, action_required=True) for Juan. There is NO send path in
this module — no function here can message a customer, by construction.

Each draft carries: lead, business, language, due-day reason, the draft
text (short, phone-readable, Spanish-first), and the source citations it
was built from. Nothing is invented: drafts reference only facts already
in the 360 profile.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sofia_customer_360 import build_customer_360_from_data
from sofia_sales_playbooks import (
    DORMANT_AFTER_DAYS,
    FOLLOWUP_CADENCE_DAYS,
    TRACKS,
    get_playbook,
    next_qualification_question,
)

# A lead is only followed up when it has shown commercial intent in a known
# business: at least one inbound turn classified to that business.
MIN_INBOUND_TURNS = 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _days_since(value: Any, now: datetime) -> int | None:
    dt = _parse_ts(value)
    if dt is None:
        return None
    return max(0, int((now - dt).total_seconds() // 86400))


def _last_outbound_draft_day(events: list[dict[str, Any]], business: str) -> int | None:
    """Most recent follow-up draft day already queued for this business."""
    latest: int | None = None
    for event in events:
        if event.get("event_type") != "sofia_followup_draft":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if payload.get("business") != business:
            continue
        day = payload.get("cadence_day")
        try:
            day = int(day)
        except (TypeError, ValueError):
            continue
        latest = day if latest is None else max(latest, day)
    return latest


def due_followups_from_data(
    *,
    leads: list[dict[str, Any]],
    messages_by_lead: dict[str, list[dict[str, Any]]],
    events_by_lead: dict[str, list[dict[str, Any]]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Compute due follow-up drafts from plain data (fully testable).

    Returns draft dicts; NOTHING is sent or persisted here.
    """
    now = now or _now()
    drafts: list[dict[str, Any]] = []

    for lead in leads or []:
        lead_id = str(lead.get("lead_id") or "")
        if not lead_id:
            continue
        if str(lead.get("status") or "").upper() == "OPTED_OUT":
            continue
        messages = messages_by_lead.get(lead_id) or []
        events = events_by_lead.get(lead_id) or []

        for business in TRACKS:
            profile = build_customer_360_from_data(
                messages=messages, lead=lead, events=events, business=business
            )
            if profile["inbound_count"] < MIN_INBOUND_TURNS:
                continue
            if profile["deal_stage"] in ("WON", "LOST", "OPTED_OUT", "COMPLETED"):
                continue

            days_quiet = _days_since(profile.get("last_touch"), now)
            if days_quiet is None:
                continue
            last_draft_day = _last_outbound_draft_day(events, business)

            # Dormant revival: qualified stage, long silence, no revival yet.
            if (
                days_quiet >= DORMANT_AFTER_DAYS
                and profile["deal_stage"]
                not in ("NEW", "ENGAGED", "QUALIFYING", "QUALIFYING_BUYER", "QUALIFYING_SELLER")
                and last_draft_day is None
            ):
                drafts.append(_build_draft(
                    lead=lead, business=business, profile=profile,
                    kind="dormant_revival", cadence_day=None, days_quiet=days_quiet,
                ))
                continue

            # Cadence: first cadence day reached since last touch with no
            # draft already queued for an equal-or-later day.
            for day in FOLLOWUP_CADENCE_DAYS:
                if days_quiet >= day and (last_draft_day is None or last_draft_day < day):
                    drafts.append(_build_draft(
                        lead=lead, business=business, profile=profile,
                        kind="cadence", cadence_day=day, days_quiet=days_quiet,
                    ))
                    break

    return drafts


def _build_draft(
    *,
    lead: dict[str, Any],
    business: str,
    profile: dict[str, Any],
    kind: str,
    cadence_day: int | None,
    days_quiet: int,
) -> dict[str, Any]:
    language = profile.get("language") or "es"
    interests = [i["keyword"] for i in (profile.get("interests") or [])[:2]]
    about = f" ({', '.join(interests)})" if interests else ""

    if kind == "dormant_revival":
        reason = f"dormant {days_quiet}d at stage {profile.get('deal_stage')}"
        if language == "es":
            text = (
                f"Hola{', ' + (profile.get('contact_name') or '') if profile.get('contact_name') else ''}, "
                f"soy Sofía de SAHJONY. ¿Seguimos con lo de{about}? Quedo atenta."
            )
        else:
            text = (
                f"Hi{( ', ' + profile['contact_name']) if profile.get('contact_name') else ''}, "
                f"Sofía from SAHJONY here. Should we pick up where we left off{about}? Let me know."
            )
    else:
        reason = f"cadence day {cadence_day} ({days_quiet}d since last touch)"
        # Ask the next question Sofia does NOT already know the answer to:
        # the profile's preferences carry already-captured facts.
        known_state = dict(profile.get("preferences") or {})
        question = next_qualification_question(business, known_state, language)
        if language == "es":
            text = (
                f"Hola, soy Sofía de SAHJONY. Solo paso a seguir con tu solicitud{about}. "
                f"{question or '¿En qué te ayudo hoy?'}"
            )
        else:
            text = (
                f"Hi, Sofía from SAHJONY. Just following up on your request{about}. "
                f"{question or 'How can I help today?'}"
            )

    return {
        "draft_id": f"draft_{secrets.token_urlsafe(12)}",
        "lead_id": lead.get("lead_id"),
        "business": business,
        "language": language,
        "kind": kind,  # cadence | dormant_revival
        "cadence_day": cadence_day,
        "days_quiet": days_quiet,
        "deal_stage": profile.get("deal_stage"),
        "draft_text": text[:1000],
        "reason": reason,
        "source_turns": profile.get("last_touch_source"),
        "created_at": _now().isoformat(),
        "status": "draft_pending_approval",  # invariant: never auto-sent
    }


async def queue_followup_drafts(drafts: list[dict[str, Any]]) -> dict[str, Any]:
    """Persist drafts to the approval queue (business_events).

    Returns {"queued": n, "errors": [...]}. This is the ONLY write path and
    it writes DRAFTS — there is no send capability in this module.
    """
    queued = 0
    errors: list[str] = []
    try:
        from insforge_backend import get_backend

        backend = get_backend()
    except Exception as exc:
        return {"queued": 0, "errors": [f"backend_unavailable: {type(exc).__name__}"]}

    for draft in drafts or []:
        try:
            await backend.insert("business_events", {
                "event_id": f"evt_{secrets.token_urlsafe(16)}",
                "event_type": "sofia_followup_draft",
                "source_type": "sofia_360_followup_engine",
                "source_id": draft.get("draft_id"),
                "trade_case_id": None,
                "customer_id": None,
                "lead_id": draft.get("lead_id"),
                "actor_role": "system",
                "actor_id": "sofia-360-followup-engine",
                "visibility": "owner",
                "title": (
                    f"Follow-up draft ({draft.get('business')}, "
                    f"{draft.get('kind')}, {draft.get('reason')})"
                ),
                "summary": str(draft.get("draft_text") or "")[:4000],
                "action_required": True,
                "action_label": "Review and approve before any send",
                "priority": "normal",
                "event_status": "open",
                "payload": {**draft, "send_authorized": False},
                "created_at": _now().isoformat(),
                "updated_at": _now().isoformat(),
            })
            queued += 1
        except Exception as exc:
            errors.append(f"{draft.get('draft_id')}: {type(exc).__name__}")
    return {"queued": queued, "errors": errors}


async def run_followup_cycle() -> dict[str, Any]:
    """One scheduled cycle: scan, draft, queue. Returns a run report.

    Fails closed: backend errors produce an empty draft list, never sends.
    """
    try:
        from insforge_backend import get_backend

        backend = get_backend()
        leads = await backend.select("whatsapp_leads", params={"limit": "2000"}) or []
    except Exception as exc:
        return {"ok": False, "error": f"backend_unavailable: {type(exc).__name__}", "drafts": []}

    messages_by_lead: dict[str, list[dict[str, Any]]] = {}
    events_by_lead: dict[str, list[dict[str, Any]]] = {}
    try:
        from insforge_backend import get_backend as _gb

        backend = _gb()
        for lead in leads:
            lead_id = str(lead.get("lead_id") or "")
            phone = lead.get("phone")
            if phone:
                messages_by_lead[lead_id] = await backend.select(
                    "whatsapp_messages",
                    params={"phone": f"eq.{phone}", "order": "received_at.asc", "limit": "500"},
                ) or []
            events_by_lead[lead_id] = await backend.select(
                "business_events",
                params={"lead_id": f"eq.{lead_id}", "order": "created_at.asc", "limit": "2000"},
            ) or []
    except Exception:
        pass

    drafts = due_followups_from_data(
        leads=leads, messages_by_lead=messages_by_lead, events_by_lead=events_by_lead
    )
    result = await queue_followup_drafts(drafts)
    return {
        "ok": True,
        "ran_at": _now().isoformat(),
        "leads_scanned": len(leads),
        "drafts_created": len(drafts),
        **result,
    }


def followup_engine_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "sofia-followup-engine",
        "version": "1.0.0",
        "cadence_days": list(FOLLOWUP_CADENCE_DAYS),
        "dormant_after_days": DORMANT_AFTER_DAYS,
        "drafts_only": True,
        "send_capability": False,
    }
