from __future__ import annotations

import os
from datetime import date, datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row


CONTROL_FIELDS = (
    "supplier_screening_status",
    "origin_export_control_status",
    "destination_import_control_status",
    "product_restriction_status",
    "banking_status",
    "logistics_status",
    "tax_duty_status",
    "us_nexus_status",
)

_REQUIRED_TABLES = {
    "global_sourcing_requests",
    "global_supplier_candidates",
    "global_sourcing_control_evidence",
    "trade_corridor_activations",
}


def _database_url() -> str:
    for name in (
        "DATABASE_URL",
        "POSTGRES_URL",
        "NEON_DATABASE_URL",
        "NEON_POSTGRES_URL",
        "POSTGRES_PRISMA_URL",
    ):
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise RuntimeError("Production database URL is not configured")


def _expired(value: Any) -> bool:
    if not value:
        return False
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            try:
                moment = datetime.combine(date.fromisoformat(str(value)[:10]), datetime.min.time(), tzinfo=timezone.utc)
            except ValueError:
                return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment < datetime.now(timezone.utc)


def _quote_status(candidate: dict[str, Any]) -> tuple[bool, list[str]]:
    source = candidate.get("source_evidence") or {}
    if not isinstance(source, dict):
        source = {}
    quote = source.get("supplier_quote") or {}
    if not isinstance(quote, dict):
        quote = {}

    required = (
        "unit_cost",
        "currency",
        "moq",
        "lead_time_days",
        "incoterm",
        "payment_terms",
        "quote_reference",
        "quote_date",
        "valid_until",
    )
    failures = [f"quote:{key}_missing" for key in required if quote.get(key) in (None, "")]
    if quote.get("verified") is not True:
        failures.append("quote:not_owner_verified")
    if not quote.get("verified_by"):
        failures.append("quote:verified_by_missing")
    if not quote.get("verified_at"):
        failures.append("quote:verified_at_missing")
    if _expired(quote.get("valid_until")):
        failures.append("quote:expired")
    return not failures, failures


def _probe(country_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    with psycopg.connect(_database_url(), connect_timeout=10, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            present_tables: set[str] = set()
            for table in sorted(_REQUIRED_TABLES):
                cur.execute("SELECT to_regclass(%s) AS relation", (f"public.{table}",))
                row = cur.fetchone()
                if row and row["relation"] is not None:
                    present_tables.add(table)

            missing_tables = sorted(_REQUIRED_TABLES - present_tables)
            if missing_tables:
                return {
                    "verified": False,
                    "provider": "neon_postgres",
                    "canonical_database": "active_vercel_database_url",
                    "missing_tables": missing_tables,
                    "selected_candidate_count": 0,
                    "valid_selected_candidate_count": 0,
                    "reason": "Global supplier sourcing evidence schema is incomplete",
                    "fail_closed": True,
                }

            cur.execute("SELECT * FROM public.global_sourcing_requests")
            requests = [dict(row) for row in cur.fetchall()]
            cur.execute("SELECT * FROM public.global_supplier_candidates WHERE selected = true")
            selected = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT *
                FROM public.global_sourcing_control_evidence
                WHERE global_candidate_id = ANY(%s)
                ORDER BY created_at DESC
                """,
                ([str(row.get("global_candidate_id")) for row in selected] or ["__none__"],),
            )
            evidence_rows = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT *
                FROM public.trade_corridor_activations
                WHERE status = 'READY' AND execution_mode = 'LIVE' AND owner_approved = true
                """
            )
            corridors = [dict(row) for row in cur.fetchall()]

    requests_by_id = {str(row.get("sourcing_request_id")): row for row in requests}
    corridors_by_pair = {
        (str(row.get("origin_country_code") or "").upper(), str(row.get("destination_country_code") or "").upper()): row
        for row in corridors
    }
    evidence_by_candidate: dict[str, dict[str, dict[str, Any]]] = {}
    for item in evidence_rows:
        candidate_id = str(item.get("global_candidate_id") or "")
        key = str(item.get("control_key") or "")
        bucket = evidence_by_candidate.setdefault(candidate_id, {})
        if key not in bucket:
            bucket[key] = item

    invalid: dict[str, list[str]] = {}
    valid: list[str] = []

    for candidate in selected:
        candidate_id = str(candidate.get("global_candidate_id") or "unknown")
        failures: list[str] = []
        if str(candidate.get("corridor_status") or "BLOCKED").upper() != "READY":
            failures.append("candidate_controls_not_ready")

        request = requests_by_id.get(str(candidate.get("sourcing_request_id") or ""))
        if not request:
            failures.append("sourcing_request_missing")
        else:
            origin = str(candidate.get("supplier_country") or "").upper()
            destination = str(request.get("destination_country") or "").upper()
            if (origin, destination) not in corridors_by_pair:
                failures.append("owner_approved_live_country_corridor_missing")

        quote_ok, quote_failures = _quote_status(candidate)
        if not quote_ok:
            failures.extend(quote_failures)

        latest = evidence_by_candidate.get(candidate_id, {})
        for key in CONTROL_FIELDS:
            status = str(candidate.get(key) or "MISSING").upper()
            if status not in {"PASS", "NOT_APPLICABLE"}:
                failures.append(f"{key}:status_{status.lower()}")
                continue
            item = latest.get(key)
            if not item:
                failures.append(f"{key}:evidence_missing")
                continue
            if item.get("verified") is not True:
                failures.append(f"{key}:not_owner_verified")
            if not str(item.get("authority") or "").strip():
                failures.append(f"{key}:authority_missing")
            if not str(item.get("reference") or "").strip():
                failures.append(f"{key}:reference_missing")
            if not str(item.get("summary") or "").strip():
                failures.append(f"{key}:summary_missing")
            if _expired(item.get("expires_at")):
                failures.append(f"{key}:evidence_expired")

        if failures:
            invalid[candidate_id] = sorted(set(failures))
        else:
            valid.append(candidate_id)

    country_ok = bool((country_evidence or {}).get("verified")) if country_evidence is not None else True
    verified = bool(selected and valid and len(valid) == len(selected) and country_ok)
    reason = None
    if not selected:
        reason = "No owner-selected supplier candidate has completed the governed sourcing workflow"
    elif not country_ok:
        reason = "Country/corridor governance is not verified"
    elif invalid:
        reason = "One or more selected supplier candidates fail current quote/control/corridor evidence checks"

    return {
        "verified": verified,
        "provider": "neon_postgres",
        "canonical_database": "active_vercel_database_url",
        "required_table_count": len(_REQUIRED_TABLES),
        "present_table_count": len(_REQUIRED_TABLES),
        "missing_tables": [],
        "selected_candidate_count": len(selected),
        "valid_selected_candidate_count": len(valid),
        "valid_selected_candidate_ids": sorted(valid),
        "invalid_selected_candidates": invalid,
        "country_governance_verified": country_ok,
        "reason": reason,
        "fail_closed": True,
    }


def supplier_sourcing_evidence(country_evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return _probe(country_evidence=country_evidence)
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0][:240] if str(exc).strip() else "unknown database error"
        return {
            "verified": False,
            "provider": "neon_postgres",
            "canonical_database": "active_vercel_database_url",
            "reason": f"{type(exc).__name__}: {detail}",
            "missing_tables": [],
            "selected_candidate_count": 0,
            "valid_selected_candidate_count": 0,
            "fail_closed": True,
        }
