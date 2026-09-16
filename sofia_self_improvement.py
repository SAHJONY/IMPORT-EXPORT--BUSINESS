"""Sofia self-improvement: a durable learning loop for owner corrections and outcomes.

Sofia captures owner corrections (e.g. Juan correcting her identity or behavior)
and conversation outcomes as validated lessons stored in the ``business_events``
table (``source_type = "sofia_self_improvement"``). The existing adaptive layer
(``sofia_adaptive_intelligence.adaptive_context``) consumes these lessons alongside
its own, so corrections durably change future behavior.

Hard rules:
- Lessons are sanitized before storage: no secrets, credentials, tokens, or
  personal data beyond business necessity may ever be persisted.
- Near-duplicate lessons are rejected (deduplication), so the lesson store stays
  compact and high-signal.
- Nothing here sends, posts, or mutates production state beyond the lesson log.

Real conversation feed (for ``review_recent_conversations``): the Hermes runtime
on the Kali VPS keeps per-conversation history in ``/root/.hermes/state.db``
(``messages`` table) and the WhatsApp bridge logs. That feed is read-only from
this repo side via the dispatchable GitHub workflows
("Hostinger Hermes State Identity Audit" / "... Safe Clean"); this module
accepts injected conversation records so the review logic is testable offline.
"""

from __future__ import annotations

import difflib
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

# ---------------------------------------------------------------------------
# Canonical identity — shared source of truth for Sofia's self-systems.
# ---------------------------------------------------------------------------
SOFIA_IDENTITY = "Sofia Smith, Executive Manager of SAHJONY LLC"
OWNER_IDENTITY = "Juan Gonzalez, Chairman and owner of SAHJONY LLC"
RETIRED_INITIATIVES = ("PRIMO",)

SOURCE_TYPE = "sofia_self_improvement"
ADAPTIVE_SOURCE_TYPE = "sofia_adaptive_intelligence"
LESSON_SOURCE_TYPES = (ADAPTIVE_SOURCE_TYPE, SOURCE_TYPE)

DEDUP_SIMILARITY_THRESHOLD = 0.85
MAX_LESSON_CHARS = 2000

# Patterns that must never be persisted in a lesson.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r"nvapi-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{10,}", re.IGNORECASE),
    re.compile(
        r"(?i)\b(api[_-]?key|password|passwd|pwd|secret|client[_-]?secret|access[_-]?token)\b\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)\b\d{7,}\b"),  # long digit runs: phones, codes, account numbers
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_lesson(text: str) -> str:
    """Strip secrets/credentials/long digit runs from lesson text before storage."""
    cleaned = text or ""
    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    return " ".join(cleaned.split())


def lesson_fingerprint(text: str) -> str:
    """Normalized fingerprint used for near-duplicate comparison."""
    normalized = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    return " ".join(normalized.split())


def is_near_duplicate(
    candidate: str,
    existing: list[str],
    threshold: float = DEDUP_SIMILARITY_THRESHOLD,
) -> bool:
    """True when the candidate is a near-duplicate of any existing lesson."""
    cand_fp = lesson_fingerprint(candidate)
    if not cand_fp:
        return False
    for lesson in existing:
        lesson_fp = lesson_fingerprint(lesson)
        if not lesson_fp:
            continue
        if cand_fp == lesson_fp:
            return True
        if difflib.SequenceMatcher(None, cand_fp, lesson_fp).ratio() >= threshold:
            return True
    return False


def check_identity_compliant(text: str) -> list[str]:
    """Return violations if text treats a retired initiative as real/current."""
    violations: list[str] = []
    lowered = (text or "").lower()
    for retired in RETIRED_INITIATIVES:
        if retired.lower() in lowered:
            violations.append(f"mentions retired initiative '{retired}'")
    return violations


async def _get_backend(backend: Any = None) -> Any:
    if backend is not None:
        return backend
    from insforge_backend import get_backend  # lazy: keeps module importable offline

    return get_backend()


async def get_active_lessons(
    limit: int = 20,
    backend: Any = None,
) -> list[str]:
    """Return the currently active validated lessons (both lesson sources).

    This is the reader the adaptive context consumes: it merges lessons from
    ``sofia_self_improvement`` (owner corrections) and
    ``sofia_adaptive_intelligence`` (operating lessons), deduplicated.
    """
    be = await _get_backend(backend)
    lessons: list[str] = []
    seen: set[str] = set()
    for source_type in LESSON_SOURCE_TYPES:
        try:
            rows = await be.select(
                "business_events",
                params={
                    "source_type": f"eq.{source_type}",
                    "event_type": "eq.learning",
                    "order": "created_at.desc",
                    "limit": str(limit),
                },
            ) or []
        except Exception:
            rows = []
        for row in rows:
            payload = row.get("payload") or {}
            lesson = str(payload.get("lesson") or row.get("summary") or "").strip()
            if not lesson:
                continue
            fp = lesson_fingerprint(lesson)
            if fp in seen:
                continue
            seen.add(fp)
            lessons.append(lesson[:MAX_LESSON_CHARS])
            if len(lessons) >= limit:
                return lessons
    return lessons


async def record_correction(
    *,
    lesson_text: str,
    context: str | None = None,
    signal: str = "owner_correction",
    backend: Any = None,
    existing_lessons: list[str] | None = None,
) -> dict[str, Any]:
    """Record an owner correction as a durable validated lesson.

    Sanitizes the text, rejects near-duplicates, and stores the lesson in
    ``business_events``. Returns ``{"stored": bool, "reason": str, ...}``.
    """
    cleaned = sanitize_lesson(lesson_text)
    if not cleaned:
        return {"stored": False, "reason": "empty_lesson_after_sanitization"}
    if existing_lessons is None:
        existing_lessons = await get_active_lessons(backend=backend)
    if is_near_duplicate(cleaned, existing_lessons):
        return {"stored": False, "reason": "near_duplicate_lesson"}
    lesson_id = f"evt_{secrets.token_urlsafe(16)}"
    try:
        be = await _get_backend(backend)
        await be.insert(
            "business_events",
            {
                "event_id": lesson_id,
                "event_type": "learning",
                "source_type": SOURCE_TYPE,
                "source_id": signal,
                "trade_case_id": None,
                "customer_id": None,
                "lead_id": None,
                "actor_role": "system",
                "actor_id": "sofia-self-improvement-loop",
                "visibility": "internal",
                "title": "Sofia self-improvement lesson",
                "summary": cleaned[:4000],
                "action_required": False,
                "action_label": None,
                "priority": "normal",
                "event_status": "closed",
                "payload": {
                    "lesson": cleaned[:4000],
                    "signal": signal,
                    "context": (context or "")[:1000],
                    "validated": True,
                },
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
    except Exception as exc:
        return {"stored": False, "reason": f"backend_error: {type(exc).__name__}"}
    return {"stored": True, "reason": "lesson_recorded", "lesson_id": lesson_id}


# Heuristic cues that an owner message is correcting Sofia (Spanish/English).
_CORRECTION_CUES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bte dije\b", re.IGNORECASE),
    re.compile(r"\bcorrige\b", re.IGNORECASE),
    re.compile(r"\best[aá] mal\b", re.IGNORECASE),
    re.compile(r"\bno es (as[ií]|eso)\b", re.IGNORECASE),
    re.compile(r"\bnunca\b.*\b(menciones|digas)\b", re.IGNORECASE),
    re.compile(r"\bthat('s| is) wrong\b", re.IGNORECASE),
    re.compile(r"\bnever\b.*\b(mention|say)\b", re.IGNORECASE),
)


def review_recent_conversations(
    conversations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Scan recent conversations for owner-correction signals.

    ``conversations`` is an injected list of ``{"role": "owner"|"sofia",
    "text": str, "conversation_id": str}`` records. When ``None`` is passed,
    no live feed is read — the real feed plugs in here (Hermes
    ``/root/.hermes/state.db`` ``messages`` table on the Kali VPS, read via the
    dispatchable "Hostinger Hermes State Identity Audit" workflow).

    Returns candidate lessons (NOT auto-stored — store via ``record_correction``).
    """
    if not conversations:
        return []
    candidates: list[dict[str, Any]] = []
    for msg in conversations:
        if str(msg.get("role") or "").lower() != "owner":
            continue
        text = str(msg.get("text") or "")
        if any(cue.search(text) for cue in _CORRECTION_CUES):
            candidates.append(
                {
                    "conversation_id": msg.get("conversation_id"),
                    "signal": "owner_correction",
                    "suggested_lesson": sanitize_lesson(text)[:MAX_LESSON_CHARS],
                    "auto_stored": False,
                }
            )
    return candidates


async def build_improvement_context(limit: int = 12, backend: Any = None) -> str:
    """Render active lessons as a prompt block for Sofia's runtime context."""
    lessons = await get_active_lessons(limit=limit, backend=backend)
    if not lessons:
        return ""
    lines = ["VALIDATED SELF-IMPROVEMENT LESSONS (owner corrections — always honor):"]
    lines.extend(f"- {lesson}" for lesson in lessons)
    return "\n".join(lines)
