"""Sofia → MY CUBA CASH intake client.

Strict allowlist — ONLY these two routes may ever be called, nothing else:

- ``GET  /api/sofia/intakes?sender_phone=<e164>``
- ``PATCH /api/sofia/intakes/<id>``

Authentication: the secret comes ONLY from the ``SOFIA_INGEST_SECRET``
environment variable and is sent ONLY as the ``x-sofia-ingest-secret`` HTTP
header. It is never placed in a URL, never logged, and never echoed in
errors. If the secret is missing, every call fails closed with RuntimeError
before any HTTP request is made.

PATCH payload rules (enforced client-side, before the request):
- Allowed fields: ``notes``, ``intake_status`` — anything else raises ValueError.
- ``intake_status`` must be one of COLLECTING, READY_FOR_REVIEW, ON_HOLD,
  CANCELLED. ``CONVERTED`` and everything else raise ValueError.
- Payment status, requested amount, payment evidence, and remittance intent are
  never writable; attempts raise ValueError naming the blocked field.

Every successful update is verified by read-back (re-fetch and compare) before
it is reported as done.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any
from urllib.parse import quote

import httpx

CUBACASH_API_BASE = os.getenv("SOFIA_CUBACASH_API_BASE", "https://www.mycubacash.com").rstrip("/")
INTAKES_PATH = "/api/sofia/intakes"
SECRET_ENV_VAR = "SOFIA_INGEST_SECRET"
SECRET_HEADER = "x-sofia-ingest-secret"
HTTP_TIMEOUT = 15.0

ALLOWED_UPDATE_FIELDS = frozenset({"notes", "intake_status"})
ALLOWED_STATUSES = frozenset({"COLLECTING", "READY_FOR_REVIEW", "ON_HOLD", "CANCELLED"})
# Explicitly blocked so the error message is unmistakable (also enforced by the
# ALLOWED_UPDATE_FIELDS check above for any other unknown field).
BLOCKED_FIELDS = frozenset({
    "payment_status", "requested_amount", "payment_evidence",
    "remittance_intent", "payment_method", "amount",
})
BLOCKED_STATUSES = frozenset({"CONVERTED"})

# Keys the API must never surface to Sofia even if a future version returned them.
_SENSITIVE_KEYS = ("payment_", "requested_amount", "remittance_intent")


def _secret() -> str:
    value = os.getenv(SECRET_ENV_VAR, "").strip()
    if not value:
        raise RuntimeError(
            f"{SECRET_ENV_VAR} is not configured; refusing to call MY CUBA CASH intake API"
        )
    return value


def _assert_allowed_path(path: str) -> None:
    if path != INTAKES_PATH and not path.startswith(INTAKES_PATH + "/"):
        raise ValueError(f"Path not in Sofia allowlist: {path!r}")


def _headers() -> dict[str, str]:
    # The secret travels ONLY in this header — never in the URL, never in logs.
    return {SECRET_HEADER: _secret(), "Accept": "application/json"}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=HTTP_TIMEOUT)


def validate_intake_update(updates: dict[str, Any]) -> dict[str, Any]:
    """Validate a PATCH payload client-side. Raises ValueError on any violation."""
    if not isinstance(updates, dict) or not updates:
        raise ValueError("intake update must be a non-empty object")
    for field in updates:
        if field in BLOCKED_FIELDS:
            raise ValueError(f"field {field!r} is never writable by Sofia")
        if field not in ALLOWED_UPDATE_FIELDS:
            raise ValueError(f"field {field!r} is not in the Sofia update allowlist")
    status = updates.get("intake_status")
    if status is not None:
        if status in BLOCKED_STATUSES:
            raise ValueError("intake_status 'CONVERTED' is never settable by Sofia")
        if status not in ALLOWED_STATUSES:
            raise ValueError(
                f"intake_status {status!r} not allowed; use one of {sorted(ALLOWED_STATUSES)}"
            )
    notes = updates.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ValueError("notes must be a string")
    return dict(updates)


def _scrub_record(record: dict[str, Any]) -> dict[str, Any]:
    """Drop any payment-related keys defensively before Sofia ever sees them."""
    return {
        k: v for k, v in record.items()
        if not any(k.startswith(prefix) for prefix in _SENSITIVE_KEYS)
    }


def _coerce_intake_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("intakes") or payload.get("data") or payload.get("items") or []
    else:
        items = []
    return [_scrub_record(r) for r in items if isinstance(r, dict)]


async def fetch_intakes(sender_phone_e164: str) -> list[dict[str, Any]]:
    """GET /api/sofia/intakes?sender_phone=<e164> — newest first."""
    if not re.fullmatch(r"\+\d{8,15}", sender_phone_e164 or ""):
        raise ValueError("sender_phone must be E.164 like +12816628581")
    path = INTAKES_PATH
    _assert_allowed_path(path)
    url = f"{CUBACASH_API_BASE}{path}?sender_phone={quote(sender_phone_e164, safe='')}"
    headers = _headers()  # secret check happens here — before any HTTP client exists
    async with _client() as client:
        response = await client.get(url, headers=headers)
    if response.status_code == 401:
        raise RuntimeError("MY CUBA CASH intake API rejected the Sofia credential (401)")
    if response.status_code >= 400:
        raise RuntimeError(f"MY CUBA CASH intake API error: HTTP {response.status_code}")
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError("MY CUBA CASH intake API returned invalid JSON")
    return _coerce_intake_list(payload)


async def apply_intake_update(
    intake_id: str,
    updates: dict[str, Any],
    *,
    sender_phone_e164: str,
) -> dict[str, Any]:
    """PATCH one intake, then read back and verify before reporting success.

    Returns {"ok": True, "record": <verified record>} or
    {"ok": False, "reason": <short code>}. Never raises for transport/API
    failures (fail-closed result instead); raises ValueError only for
    allowlist violations (programmer error — must be loud).
    """
    validated = validate_intake_update(updates)
    if not intake_id or not isinstance(intake_id, str):
        raise ValueError("intake_id must be a non-empty string")
    path = f"{INTAKES_PATH}/{quote(intake_id, safe='')}"
    _assert_allowed_path(path)
    url = f"{CUBACASH_API_BASE}{path}"
    headers = {**_headers(), "Content-Type": "application/json"}  # secret check first
    try:
        async with _client() as client:
            response = await client.patch(url, headers=headers, json=validated)
        if response.status_code == 401:
            return {"ok": False, "reason": "auth_rejected"}
        if response.status_code >= 400:
            return {"ok": False, "reason": f"http_{response.status_code}"}
        # Read-back: re-fetch the sender's intakes and compare the written fields.
        records = await fetch_intakes(sender_phone_e164)
        record = next((r for r in records if str(r.get("id")) == str(intake_id)), None)
        if record is None:
            return {"ok": False, "reason": "readback_missing"}
        for field, expected in validated.items():
            actual = record.get(field)
            if field == "notes":
                if not (isinstance(actual, str) and str(expected)[:500] in actual):
                    return {"ok": False, "reason": "readback_mismatch"}
            elif actual != expected:
                return {"ok": False, "reason": "readback_mismatch"}
        return {"ok": True, "record": record}
    except (RuntimeError, ValueError):
        raise
    except Exception as exc:
        return {"ok": False, "reason": f"transport_{type(exc).__name__}"}


# ---------------------------------------------------------------------------
# Intent detection (deterministic, conservative)
# ---------------------------------------------------------------------------

_INTAKE_INQUIRY_RE = re.compile(
    r"(mi solicitud|mis solicitudes|mi tramite|mi trámite|mis tramites|"
    r"como va mi|estado de mi|seguimiento|donde va mi|dónde va mi|"
    r"que paso con mi|qué pasó con mi|mi caso|my request|my case|"
    r"status of my|suivi de ma)",
    re.IGNORECASE,
)

_CANCEL_RE = re.compile(r"\bcancel", re.IGNORECASE)
_HOLD_RE = re.compile(r"(pon.*en espera|en espera|en pausa|pausa mi|hold my|put.*on hold)", re.IGNORECASE)
_RESUME_RE = re.compile(r"(reanuda|reanudar|continua con|continúa con|sigue con mi|resume my)", re.IGNORECASE)
_NOTE_RE = re.compile(
    r"(?:agrega|añade|anota|agregar|añadir|add)\s+(?:una\s+)?nota\s*[:\-]?\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)


def looks_like_intake_inquiry(text: str) -> bool:
    """True when the message asks about the customer's own existing request(s)."""
    return bool(_INTAKE_INQUIRY_RE.search(text or ""))


def detect_update_intent(text: str) -> tuple[str, str] | None:
    """Detect an explicit customer request to change their own intake.

    Returns (field, value) — for notes, value is the note text — or None.
    Only fires on explicit phrasing; anything vague returns None so Sofia asks.
    """
    normalized = (text or "").strip()
    if not normalized:
        return None
    note_match = _NOTE_RE.search(normalized)
    if note_match:
        note = note_match.group(1).strip()[:500]
        if note:
            return ("notes", note)
        return None
    if _CANCEL_RE.search(normalized):
        return ("intake_status", "CANCELLED")
    if _HOLD_RE.search(normalized):
        return ("intake_status", "ON_HOLD")
    if _RESUME_RE.search(normalized):
        return ("intake_status", "COLLECTING")
    return None


def format_intake_summary(intakes: list[dict[str, Any]], max_items: int = 3) -> str:
    """Grounded, human-readable summary of verified intake records."""
    lines: list[str] = []
    for record in (intakes or [])[:max_items]:
        notes = str(record.get("notes") or "").strip()
        if len(notes) > 200:
            notes = notes[:200] + "…"
        lines.append(
            "- ID {id} · estado: {status} · actualizado: {updated}{notes}".format(
                id=record.get("id"),
                status=record.get("intake_status"),
                updated=record.get("updated_at") or record.get("created_at") or "—",
                notes=f" · notas: {notes}" if notes else "",
            )
        )
    if len(intakes or []) > max_items:
        lines.append(f"(+{len(intakes) - max_items} más)")
    return "\n".join(lines) if lines else "(sin registros)"
