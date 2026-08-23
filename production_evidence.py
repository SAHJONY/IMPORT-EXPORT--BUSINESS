from __future__ import annotations

import asyncio
import os
from typing import Any


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
    return ""


def _schema_evidence_sync() -> dict[str, Any]:
    url = _database_url()
    if not url:
        return {"verified": False, "provider": "unconfigured", "reason": "database URL missing"}

    import psycopg

    required_columns = {
        "cuba_partner_accounts": {"partner_id", "status", "referral_token_hash", "automatic_commission_payout"},
        "cuba_partner_referrals": {"referral_id", "partner_id", "referral_status", "commission_status", "currency"},
        "trade_payment_ledger": {
            "payment_case_id", "currency", "payment_status", "supplier_payout_allowed", "shipment_release_allowed",
            "supplier_payout_authorized_at", "shipment_release_authorized_at",
        },
        "trade_payment_events": {"event_id", "payment_case_id", "event_type", "currency", "created_at"},
    }

    with psycopg.connect(url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = ANY(%s)
                """,
                (list(required_columns),),
            )
            found: dict[str, set[str]] = {name: set() for name in required_columns}
            for table_name, column_name in cur.fetchall():
                if table_name in found:
                    found[table_name].add(column_name)

            missing_tables = [name for name, columns in found.items() if not columns]
            missing_columns = {
                name: sorted(columns - found[name])
                for name, columns in required_columns.items()
                if columns - found[name]
            }

            cur.execute(
                "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public' AND tablename='trade_payment_events'"
            )
            payment_event_indexes = int(cur.fetchone()[0])

    verified = not missing_tables and not missing_columns and payment_event_indexes >= 2
    return {
        "verified": verified,
        "provider": "neon_postgres",
        "required_tables": sorted(required_columns),
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "payment_event_index_count": payment_event_indexes,
        "evidence": "Direct information_schema/pg_indexes verification against the active DATABASE_URL",
    }


async def production_schema_evidence() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_schema_evidence_sync)
    except Exception as exc:
        return {
            "verified": False,
            "provider": "neon_postgres",
            "reason": f"schema verification failed: {type(exc).__name__}",
        }
