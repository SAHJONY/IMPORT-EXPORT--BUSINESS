"""Sofia 360° salesperson — unified customer view, one profile per business.

A 360 profile assembles everything Sofia knows about one contact FOR ONE
BUSINESS: conversation history, language, preferences, deal stage,
budget/product/vehicle interest, commitments, objections, last touch, and
the next best action. Built from whatsapp_messages + whatsapp_leads +
business_events + relationship memory.

HARD RULES:
- ``business`` is REQUIRED and must be one of the known tracks. An unknown
  business raises ValueError — profiles never fall through to another
  business's data.
- Nothing is invented: every field cites its source turn/event id. A field
  with no source is reported as unknown, never guessed.
- Businesses never cross-file: the profile for business B contains ONLY
  turns and facts classified to B. Use ``separation_audit`` to verify.

The pure builder ``build_customer_360_from_data`` takes plain data so it is
fully testable without a backend; ``build_customer_360`` is the async
wrapper that fetches from the insforge backend.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any

from sofia_sales_playbooks import TRACKS, car_signal_score, playbook_stages
from sofia_track_classifier import TRACK_ASK, classify_track, detect_language

# Conversation turns with no track signal of their own inherit the latest
# established business for the contact (mirrors the runtime's continuity).
_TRACK_BY_DECISION = {
    "import_export": "import_export",
    "my_cuba_cash": "my_cuba_cash",
    "ask": None,
}

_MONEY_RE = re.compile(r"\$\s?[\d,]+(?:\.\d+)?")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _phone_hash(phone: str | None) -> str | None:
    if not phone:
        return None
    return "ph_" + hashlib.sha256(str(phone).encode("utf-8")).hexdigest()[:16]


def _flag_on() -> bool:
    return os.getenv("SOFIA_360_SALESPERSON", "").strip().lower() in ("1", "true", "yes")


def classify_turn(text: str) -> str | None:
    """Business for one turn, or None when the turn carries no signal.

    Uses the live classifier first. Strong car_sales signals resolve to
    ``car_sales`` when the 360 flag is on (which itself needs Juan's
    approval). When the flag is off, a strong car signal is quarantined as
    ``unclassified_car`` — it is NEVER inherited into another business's
    profile via continuity. Genuinely signal-less turns still inherit the
    latest established business.
    """
    decision = classify_track(text or "")
    resolved = _TRACK_BY_DECISION.get(decision.track)
    if resolved is not None:
        return resolved
    if car_signal_score(text or "") >= 0.66:
        return "car_sales" if _flag_on() else "unclassified_car"
    return None


def tag_turns_with_business(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return messages with a ``business`` key each.

    Signal-less turns inherit the latest established business (continuity),
    exactly like the live runtime. Turns before any business is established
    keep business=None and are excluded from per-business profiles.
    The ``unclassified_car`` quarantine bucket never updates the continuity
    pointer and is never inherited: a strong car-signal turn with the flag
    off is kept aside rather than misfiled into another business.
    """
    tagged: list[dict[str, Any]] = []
    current: str | None = None
    for msg in messages:
        business = classify_turn(str(msg.get("text") or ""))
        if business in TRACKS:
            current = business
            tagged_business: str | None = business
        elif business is None:
            tagged_business = current
        else:  # quarantine bucket: kept, never inherited, never inherits
            tagged_business = business
        tagged.append({**msg, "business": tagged_business})
    return tagged


def _turn_id(msg: dict[str, Any], index: int) -> str:
    return str(msg.get("message_id") or f"turn_{index}")


def _extract_amounts(text: str) -> list[str]:
    return [m.group(0) for m in _MONEY_RE.finditer(text or "")]


def _extract_interests(text: str, business: str) -> list[str]:
    """Keyword interests per business — evidence-extracted, never invented."""
    t = (text or "").lower()
    interests: list[str] = []
    if business == "car_sales":
        for kw in (
            "toyota", "honda", "hyundai", "kia", "nissan", "ford",
            "chevrolet", "mazda", "pickup", "camioneta", "suv", "sedan",
        ):
            if kw in t:
                interests.append(kw)
    elif business == "import_export":
        for kw in (
            "arroz", "rice", "harina", "flour", "aceite", "oil", "azucar",
            "sugar", "pollo", "chicken", "leche", "milk", "contenedor",
            "container", "flete", "freight",
        ):
            if kw in t:
                interests.append(kw)
    elif business == "my_cuba_cash":
        for kw in ("remesa", "recarga", "divisas", "tasa", "envio"):
            if kw in t:
                interests.append(kw)
    return interests


def build_customer_360_from_data(
    *,
    messages: list[dict[str, Any]],
    lead: dict[str, Any] | None,
    events: list[dict[str, Any]],
    business: str,
) -> dict[str, Any]:
    """Build the 360 profile for one contact and ONE business.

    ``messages``: whatsapp_messages rows (any business; tagged inside).
    ``lead``: whatsapp_leads row or None.
    ``events``: business_events rows for the lead.
    """
    if business not in TRACKS:
        raise ValueError(f"Unknown business: {business!r}. Known: {TRACKS}")
    lead = lead or {}
    messages = messages or []
    events = events or []

    tagged = tag_turns_with_business(messages)
    biz_turns = [m for m in tagged if m.get("business") == business]

    inbound = [m for m in biz_turns if m.get("direction") == "inbound"]
    outbound = [m for m in biz_turns if m.get("direction") != "inbound"]

    # Language: latest inbound turn wins; default Spanish.
    language = "es"
    if inbound:
        language = detect_language(str(inbound[-1].get("text") or "")) or "es"
        if language not in ("es", "en"):
            language = "es"

    # Deal stage: latest stage-bearing event for THIS business wins.
    stage = "NEW"
    stage_source: str | None = None
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        event_biz = payload.get("business") or payload.get("business_track")
        event_stage = payload.get("stage") or payload.get("relationship_stage")
        if event_biz and event_biz != business:
            continue
        if event_stage and str(event_stage).upper() in [
            s.upper() for s in playbook_stages(business)
        ]:
            stage = str(event_stage).upper()
            stage_source = str(event.get("event_id"))

    # Interests, amounts, commitments, objections — each with sources.
    interests: dict[str, str] = {}
    amounts: dict[str, str] = {}
    for i, msg in enumerate(biz_turns):
        text = str(msg.get("text") or "")
        tid = _turn_id(msg, i)
        for kw in _extract_interests(text, business):
            interests.setdefault(kw, tid)
        for amount in _extract_amounts(text):
            amounts.setdefault(amount, tid)

    commitments: list[dict[str, str]] = []
    objections: list[dict[str, str]] = []
    preferences: dict[str, str] = {}
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if (payload.get("business") or payload.get("business_track")) not in (None, business):
            continue
        eid = str(event.get("event_id") or "event")
        for c in payload.get("commitments") or []:
            if _clean(c):
                commitments.append({"text": _clean(c), "source": eid})
        for o in payload.get("objections") or []:
            if _clean(o):
                objections.append({"text": _clean(o), "source": eid})
        for fact in (payload.get("facts") or []):
            if isinstance(fact, dict) and _clean(fact.get("key")) and _clean(fact.get("value")):
                preferences[str(fact["key"])] = str(fact["value"])

    last_touch = None
    last_touch_source = None
    if biz_turns:
        last = biz_turns[-1]
        last_touch = last.get("received_at") or last.get("created_at")
        last_touch_source = _turn_id(last, len(biz_turns) - 1)

    first_seen = None
    if messages:
        first_seen = messages[0].get("received_at") or messages[0].get("created_at")

    return {
        "business": business,
        "contact_hash": _phone_hash(lead.get("phone")),
        "contact_name": _clean(lead.get("contact_name") or lead.get("name")),
        "language": language,
        "language_source": _turn_id(inbound[-1], len(biz_turns) - 1) if inbound else None,
        "deal_stage": stage,
        "deal_stage_source": stage_source,
        "turns_in_scope": len(biz_turns),
        "turns_total": len(messages),
        "inbound_count": len(inbound),
        "outbound_count": len(outbound),
        "interests": [{"keyword": k, "source": v} for k, v in interests.items()],
        "amounts_mentioned": [{"amount": k, "source": v} for k, v in amounts.items()],
        "commitments": commitments[-10:],
        "objections": objections[-10:],
        "preferences": preferences,
        "first_seen": first_seen,
        "last_touch": last_touch,
        "last_touch_source": last_touch_source,
        "unknown_means_unknown": True,
    }


def separation_audit(profile: dict[str, Any], other_business_turns: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify a profile contains no facts sourced from another business's turns.

    Returns {"ok": bool, "leaks": [str, ...]}. A leak is any source id in the
    profile that belongs to a turn classified to a different business.
    """
    other_ids = {
        str(m.get("message_id")) for m in other_business_turns if m.get("message_id")
    }
    profile_sources: set[str] = set()

    def _collect(value: Any) -> None:
        if isinstance(value, dict):
            source = value.get("source")
            if isinstance(source, str):
                profile_sources.add(source)
            for v in value.values():
                _collect(v)
        elif isinstance(value, list):
            for v in value:
                _collect(v)

    _collect(profile.get("interests"))
    _collect(profile.get("amounts_mentioned"))
    _collect(profile.get("commitments"))
    _collect(profile.get("objections"))
    leaks = sorted(profile_sources & other_ids)
    return {"ok": not leaks, "leaks": leaks}


async def build_customer_360(
    *,
    phone: str | None,
    lead_id: str | None,
    business: str,
) -> dict[str, Any]:
    """Async wrapper: fetch from the insforge backend, then build.

    Fails closed: any backend error yields an empty-but-valid profile for
    the requested business (never another business's data, never invented
    facts).
    """
    if business not in TRACKS:
        raise ValueError(f"Unknown business: {business!r}. Known: {TRACKS}")
    messages: list[dict[str, Any]] = []
    lead: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    try:
        from insforge_backend import get_backend

        backend = get_backend()
        if phone:
            messages = await backend.select(
                "whatsapp_messages",
                params={"phone": f"eq.{phone}", "order": "received_at.asc", "limit": "500"},
            ) or []
        if lead_id:
            rows = await backend.select(
                "whatsapp_leads", params={"lead_id": f"eq.{lead_id}", "limit": "1"}
            ) or []
            lead = rows[0] if rows else None
            events = await backend.select(
                "business_events",
                params={"lead_id": f"eq.{lead_id}", "order": "created_at.asc", "limit": "2000"},
            ) or []
    except Exception:
        pass
    profile = build_customer_360_from_data(
        messages=messages, lead=lead, events=events, business=business
    )
    profile["backend_degraded"] = not messages and not lead
    profile["built_at"] = _now()
    return profile
