from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row


MANDATORY_CONTROL_KEYS = (
    "legal_entity_trading_eligibility",
    "importer_exporter_registration",
    "customs_broker_coverage",
    "sanctions_export_controls",
    "product_restrictions",
    "tax_vat_gst",
    "banking_settlement",
    "currency_support",
    "freight_carrier_coverage",
    "cargo_liability_insurance",
    "document_requirements",
    "translation_language",
    "local_contracts",
    "warehouse_3pl",
    "data_privacy",
    "accounting_reconciliation",
)

_REQUIRED_TABLES = {
    "country_activation_profiles",
    "country_activation_controls",
    "trade_corridor_activations",
    "country_activation_audit",
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


def _is_expired(value: Any) -> bool:
    if not value:
        return False
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment <= datetime.now(timezone.utc)


def _control_state(control: dict[str, Any] | None, *, live: bool) -> tuple[str, str | None]:
    if not control:
        return "BLOCKED", "missing_control"

    status = str(control.get("status") or "BLOCKED").upper()
    if status == "BLOCKED":
        return "BLOCKED", "control_blocked"
    if status not in {"READY", "LIMITED", "NOT_APPLICABLE"}:
        return "BLOCKED", "invalid_status"

    if not str(control.get("evidence_summary") or "").strip():
        return "BLOCKED", "missing_evidence_summary"
    if not str(control.get("evidence_source") or "").strip():
        return "BLOCKED", "missing_evidence_source"
    if not control.get("reviewed_at"):
        return "BLOCKED", "not_reviewed"
    if _is_expired(control.get("expires_at")):
        return "BLOCKED", "evidence_expired"

    if status == "NOT_APPLICABLE":
        if live and not bool(control.get("owner_waiver")):
            return "BLOCKED", "not_applicable_without_owner_waiver"
        if live and str(control.get("reviewed_by_role") or "").lower() != "owner":
            return "BLOCKED", "not_applicable_not_owner_reviewed"
        return "READY", None

    return status, None


def _country_state(profile: dict[str, Any], controls: list[dict[str, Any]]) -> dict[str, Any]:
    live = str(profile.get("scenario_mode") or "LIVE").upper() == "LIVE"
    by_key = {str(item.get("control_key")): item for item in controls}
    states: list[str] = []
    failures: dict[str, str] = {}

    for key in MANDATORY_CONTROL_KEYS:
        state, reason = _control_state(by_key.get(key), live=live)
        states.append(state)
        if reason:
            failures[key] = reason

    if any(state == "BLOCKED" for state in states):
        derived = "BLOCKED"
    elif any(state == "LIMITED" for state in states):
        derived = "LIMITED"
    else:
        derived = "READY"

    live_eligible = bool(
        live
        and profile.get("live_execution_allowed") is True
        and profile.get("owner_approved") is True
        and bool(profile.get("approved_at"))
        and str(profile.get("operating_status") or "BLOCKED").upper() == "READY"
        and derived == "READY"
    )

    return {
        "derived_status": derived,
        "live_eligible": live_eligible,
        "control_failures": failures,
    }


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).upper() for item in value]
    if isinstance(value, tuple):
        return [str(item).upper() for item in value]
    return []


def _probe() -> dict[str, Any]:
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
                    "required_table_count": len(_REQUIRED_TABLES),
                    "present_table_count": len(present_tables),
                    "missing_tables": missing_tables,
                    "ready_live_country_count": 0,
                    "ready_live_corridor_count": 0,
                    "reason": "Country/corridor governance schema is incomplete",
                    "fail_closed": True,
                }

            cur.execute("SELECT * FROM public.country_activation_profiles ORDER BY country_code")
            profiles = [dict(row) for row in cur.fetchall()]
            cur.execute("SELECT * FROM public.country_activation_controls ORDER BY country_code, control_key")
            controls = [dict(row) for row in cur.fetchall()]
            cur.execute("SELECT * FROM public.trade_corridor_activations ORDER BY origin_country_code, destination_country_code")
            corridors = [dict(row) for row in cur.fetchall()]

    controls_by_country: dict[str, list[dict[str, Any]]] = {}
    for control in controls:
        controls_by_country.setdefault(str(control.get("country_code") or "").upper(), []).append(control)

    profiles_by_code = {str(profile.get("country_code") or "").upper(): profile for profile in profiles}
    country_states = {
        code: _country_state(profile, controls_by_country.get(code, []))
        for code, profile in profiles_by_code.items()
    }

    invalid_ready_countries: list[str] = []
    ready_live_countries: list[str] = []
    hypothetical_live_violations: list[str] = []

    for code, profile in profiles_by_code.items():
        state = country_states[code]
        scenario_mode = str(profile.get("scenario_mode") or "LIVE").upper()
        if scenario_mode == "HYPOTHETICAL" and bool(profile.get("live_execution_allowed")):
            hypothetical_live_violations.append(f"country:{code}")
        if str(profile.get("operating_status") or "BLOCKED").upper() == "READY" and scenario_mode == "LIVE" and not state["live_eligible"]:
            invalid_ready_countries.append(code)
        if state["live_eligible"]:
            ready_live_countries.append(code)

    valid_ready_corridors: list[str] = []
    invalid_ready_corridors: list[str] = []

    for corridor in corridors:
        corridor_id = str(corridor.get("corridor_id") or "unknown")
        origin = str(corridor.get("origin_country_code") or "").upper()
        destination = str(corridor.get("destination_country_code") or "").upper()
        execution_mode = str(corridor.get("execution_mode") or "LIVE").upper()
        status = str(corridor.get("status") or "BLOCKED").upper()

        origin_profile = profiles_by_code.get(origin)
        destination_profile = profiles_by_code.get(destination)
        involves_hypothetical = bool(
            (origin_profile and str(origin_profile.get("scenario_mode") or "LIVE").upper() == "HYPOTHETICAL")
            or (destination_profile and str(destination_profile.get("scenario_mode") or "LIVE").upper() == "HYPOTHETICAL")
        )
        if execution_mode == "LIVE" and involves_hypothetical:
            hypothetical_live_violations.append(f"corridor:{corridor_id}")

        if status != "READY" or execution_mode != "LIVE":
            continue

        coverage_ok = all(bool(corridor.get(field)) for field in (
            "carrier_coverage",
            "broker_coverage",
            "banking_coverage",
            "insurance_coverage",
            "tax_model_verified",
        ))
        incoterms_ok = bool(_as_list(corridor.get("allowed_incoterms")))
        currencies = _as_list(corridor.get("supported_currencies"))
        usd_ok = "USD" in currencies
        countries_ok = bool(
            origin in country_states
            and destination in country_states
            and country_states[origin]["live_eligible"]
            and country_states[destination]["live_eligible"]
        )
        approved_ok = corridor.get("owner_approved") is True

        if coverage_ok and incoterms_ok and usd_ok and countries_ok and approved_ok and not involves_hypothetical:
            valid_ready_corridors.append(corridor_id)
        else:
            invalid_ready_corridors.append(corridor_id)

    verified = bool(
        ready_live_countries
        and valid_ready_corridors
        and not invalid_ready_countries
        and not invalid_ready_corridors
        and not hypothetical_live_violations
    )

    return {
        "verified": verified,
        "provider": "neon_postgres",
        "canonical_database": "active_vercel_database_url",
        "required_table_count": len(_REQUIRED_TABLES),
        "present_table_count": len(_REQUIRED_TABLES),
        "missing_tables": [],
        "mandatory_control_count": len(MANDATORY_CONTROL_KEYS),
        "profile_count": len(profiles),
        "corridor_count": len(corridors),
        "ready_live_country_count": len(ready_live_countries),
        "ready_live_country_codes": sorted(ready_live_countries),
        "ready_live_corridor_count": len(valid_ready_corridors),
        "ready_live_corridor_ids": sorted(valid_ready_corridors),
        "invalid_ready_country_codes": sorted(invalid_ready_countries),
        "invalid_ready_corridor_ids": sorted(invalid_ready_corridors),
        "hypothetical_live_violations": sorted(hypothetical_live_violations),
        "reason": None if verified else "No fully evidenced owner-approved LIVE/READY trade corridor is currently verified",
        "fail_closed": True,
    }


def country_governance_evidence() -> dict[str, Any]:
    try:
        return _probe()
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0][:240] if str(exc).strip() else "unknown database error"
        return {
            "verified": False,
            "provider": "neon_postgres",
            "canonical_database": "active_vercel_database_url",
            "reason": f"{type(exc).__name__}: {detail}",
            "missing_tables": [],
            "ready_live_country_count": 0,
            "ready_live_corridor_count": 0,
            "fail_closed": True,
        }
