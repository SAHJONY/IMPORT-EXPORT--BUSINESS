from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from insforge_backend import get_backend
from sofia_whatsapp_runtime import generate_sofia_reply
from telegram_api import _telegram_call

MAX_FOLLOWUPS = int(os.getenv("TELEGRAM_PROACTIVE_MAX_FOLLOWUPS", "3"))
PROACTIVE_ENABLED = os.getenv("TELEGRAM_PROACTIVE_ENABLED", "false").strip().lower() == "true"

OPT_OUT_TERMS = (
    "stop", "unsubscribe", "do not contact", "don't contact", "no me escribas",
    "no contactar", "no contactarme", "baja", "cancelar mensajes",
)


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("payload") or {}
    return value if isinstance(value, dict) else {}


def _text(row: dict[str, Any]) -> str:
    payload = _payload(row)
    return str(payload.get("message_text") or row.get("summary") or "").strip()


def _chat_id(row: dict[str, Any]) -> str:
    return str(_payload(row).get("chat_id") or "").strip()


def _sender_id(row: dict[str, Any]) -> str:
    payload = _payload(row)
    return str(payload.get("sender_id") or row.get("source_id") or "").strip()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _eligible_inbound(row: dict[str, Any]) -> bool:
    if str(row.get("event_type") or "") != "telegram_inbound":
        return False
    payload = _payload(row)
    if str(payload.get("chat_type") or "") not in {"private", "group", "supergroup"}:
        return False
    text = _text(row).lower()
    if any(term in text for term in OPT_OUT_TERMS):
        return False
    if payload.get("sender_id") and str(payload.get("sender_id")) in {
        x.strip() for x in os.getenv("TELEGRAM_OWNER_USER_IDS", "").split(",") if x.strip()
    }:
        return False
    return bool(_chat_id(row) and _sender_id(row))


def _followup_key(chat_id: str, source_event_id: str, ordinal: int) -> str:
    raw = f"telegram-proactive:{chat_id}:{source_event_id}:{ordinal}"
    return "telegram_proactive_" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _next_ordinal(age_hours: float) -> int | None:
    if age_hours >= 72:
        return 3
    if age_hours >= 24:
        return 2
    if age_hours >= 6:
        return 1
    return None


async def _load_events() -> list[dict[str, Any]]:
    rows = await get_backend().select("business_events", params={"limit": "5000"}) or []
    return [row for row in rows if isinstance(row, dict)]


def _has_newer_inbound(events: list[dict[str, Any]], sender_id: str, created_at: datetime) -> bool:
    for row in events:
        if str(row.get("event_type") or "") != "telegram_inbound":
            continue
        if _sender_id(row) != sender_id:
            continue
        dt = _parse_dt(row.get("created_at") or row.get("updated_at"))
        if dt and dt > created_at:
            return True
    return False


def _sent_followup_count(events: list[dict[str, Any]], sender_id: str) -> int:
    count = 0
    for row in events:
        if str(row.get("event_type") or "") != "telegram_proactive_followup_sent":
            continue
        if str(row.get("source_id") or "") == sender_id:
            count += 1
    return count


def _already_sent(events: list[dict[str, Any]], event_id: str) -> bool:
    return any(str(row.get("event_id") or "") == event_id for row in events)


async def _compose_followup(row: dict[str, Any], ordinal: int) -> str:
    original = _text(row)
    payload = _payload(row)
    signals = payload.get("signals") or {}
    prompt = (
        "[TELEGRAM PROACTIVE SALES FOLLOW-UP]\n"
        "You are Sofía Smith, Executive Manager of SAHJONY GLOBAL TRADING. "
        "Write one concise, useful Telegram follow-up in the customer's language. "
        "This contact previously messaged SAHJONY, so this is not cold outreach. "
        "Do not invent price, availability, capacity, urgency, authority, certifications, or commercial facts. "
        "Ask only for the smallest missing detail needed to advance the transaction. "
        "Do not make binding commitments. Do not mention internal scoring or automation. "
        f"This is follow-up {ordinal} of at most {MAX_FOLLOWUPS}.\n"
        f"Known original message: {original[:2500]}\n"
        f"Known signals: {signals}\n"
    )
    reply = await asyncio.wait_for(generate_sofia_reply(prompt, None), timeout=35.0)
    return str(reply or "").strip()[:4096]


async def run_proactive_cycle() -> dict[str, Any]:
    if not PROACTIVE_ENABLED:
        return {"enabled": False, "sent": 0, "reason": "TELEGRAM_PROACTIVE_ENABLED is not true"}

    events = await _load_events()
    now = datetime.now(timezone.utc)
    candidates: list[tuple[dict[str, Any], int, datetime]] = []

    for row in events:
        if not _eligible_inbound(row):
            continue
        created = _parse_dt(row.get("created_at") or row.get("updated_at"))
        if not created:
            continue
        age_hours = (now - created).total_seconds() / 3600
        ordinal = _next_ordinal(age_hours)
        if not ordinal:
            continue
        sender_id = _sender_id(row)
        if _has_newer_inbound(events, sender_id, created):
            continue
        if _sent_followup_count(events, sender_id) >= MAX_FOLLOWUPS:
            continue
        followup_event_id = _followup_key(_chat_id(row), str(row.get("event_id") or ""), ordinal)
        if _already_sent(events, followup_event_id):
            continue
        candidates.append((row, ordinal, created))

    candidates.sort(key=lambda item: item[2])
    sent = 0
    skipped = 0

    for row, ordinal, _ in candidates[:25]:
        chat_id = _chat_id(row)
        sender_id = _sender_id(row)
        source_event_id = str(row.get("event_id") or "")
        followup_event_id = _followup_key(chat_id, source_event_id, ordinal)
        try:
            text = await _compose_followup(row, ordinal)
            if not text:
                skipped += 1
                continue
            result = await _telegram_call("sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "disable_notification": False,
            })
            message = result.get("result") or {}
            await get_backend().insert("business_events", {
                "event_id": followup_event_id,
                "event_type": "telegram_proactive_followup_sent",
                "source_type": "telegram_bot",
                "source_id": sender_id,
                "trade_case_id": row.get("trade_case_id"),
                "customer_id": row.get("customer_id"),
                "lead_id": row.get("lead_id"),
                "actor_role": "prospect",
                "actor_id": sender_id,
                "visibility": "business",
                "title": "Sofia proactive Telegram follow-up",
                "summary": text,
                "action_required": False,
                "action_label": "Proactive Telegram sales recovery",
                "priority": "normal",
                "event_status": "closed",
                "payload": {
                    "channel": "telegram",
                    "canonical_agent_id": "sofia-smith",
                    "canonical_agent_name": "Sofia Smith",
                    "chat_id": chat_id,
                    "sender_id": sender_id,
                    "source_event_id": source_event_id,
                    "followup_ordinal": ordinal,
                    "telegram_message_id": message.get("message_id"),
                    "cold_outreach": False,
                    "inbound_or_consented_only": True,
                    "binding_commitments_allowed": False,
                    "capital_at_risk_usd": 0,
                },
            })
            sent += 1
        except Exception:
            skipped += 1

    return {
        "enabled": True,
        "evaluated": len(events),
        "candidates": len(candidates),
        "sent": sent,
        "skipped": skipped,
        "max_followups_per_conversation": MAX_FOLLOWUPS,
        "cold_outreach_allowed": False,
        "binding_commitments_allowed": False,
    }


if __name__ == "__main__":
    print(asyncio.run(run_proactive_cycle()))
