from __future__ import annotations

import os
from typing import Any

import httpx


def _supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip().rstrip("/")


def _supabase_key() -> str:
    return (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
    )


def _probe() -> dict[str, Any]:
    base = _supabase_url()
    key = _supabase_key()
    if not base or not key:
        return {
            "verified": False,
            "provider": "supabase",
            "canonical_database": "supabase",
            "reason": "Supabase server credentials are not configured",
            "rls_verified": False,
            "rls_reason": "Supabase server credentials are not configured",
        }
    response = httpx.post(
        f"{base}/rest/v1/rpc/sahjony_platform_evidence",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json() if response.content else {}
    evidence = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(evidence, dict):
        evidence = {}
    public_tables = int(evidence.get("public_table_count") or 0)
    rls_tables = int(evidence.get("rls_enabled_table_count") or 0)
    active_accounts = int(evidence.get("active_ledger_accounts") or 0)
    storage_ready = bool(evidence.get("required_storage_ready"))
    verified = bool(evidence.get("verified"))
    rls_verified = public_tables > 0 and rls_tables == public_tables
    return {
        "verified": verified,
        "provider": "supabase",
        "canonical_database": "supabase",
        "required_table_count": 36,
        "present_table_count": public_tables,
        "index_count": None,
        "active_usd_accounts": active_accounts,
        "missing_tables": [],
        "missing_columns": {},
        "reason": None if verified else "Supabase platform evidence is incomplete",
        "rls_verified": rls_verified,
        "rls_required_table_count": public_tables,
        "rls_present_table_count": rls_tables,
        "rls_enabled_table_count": rls_tables,
        "rls_forced_table_count": None,
        "rls_missing_tables": [],
        "rls_not_enabled": [] if rls_verified else ["one_or_more_public_tables"],
        "rls_required_policy_count": None,
        "rls_present_policy_count": None,
        "rls_missing_policies": [],
        "rls_policy_tables": {},
        "rls_required_function_count": None,
        "rls_present_function_count": None,
        "rls_missing_functions": [],
        "rls_reason": None if rls_verified else "Not every Supabase public application table has RLS enabled",
        "storage_ready": storage_ready,
        "storage_bucket_count": int(evidence.get("storage_bucket_count") or 0),
        "logical_record_count": int(evidence.get("logical_record_count") or 0),
        "cuba_actor_count": int(evidence.get("cuba_actor_count") or 0),
        "auth_user_count": int(evidence.get("auth_user_count") or 0),
        "raw_evidence": evidence,
    }


async def production_schema_evidence() -> dict[str, Any]:
    try:
        return _probe()
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0][:240] if str(exc).strip() else "unknown Supabase evidence error"
        return {
            "verified": False,
            "provider": "supabase",
            "canonical_database": "supabase",
            "reason": f"{type(exc).__name__}: {detail}",
            "missing_tables": [],
            "missing_columns": {},
            "rls_verified": False,
            "rls_reason": f"{type(exc).__name__}: {detail}",
            "rls_missing_tables": [],
            "credential_values_exposed": False,
        }
