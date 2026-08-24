from __future__ import annotations

import asyncio
import os
from typing import Any

import psycopg
from psycopg.rows import dict_row


_REQUIRED_TABLES = {
    "trade_payment_ledger",
    "trade_payment_events",
    "cuba_partner_accounts",
    "cuba_partner_referrals",
    "cuba_consumer_marketplace_requests",
    "ledger_accounts",
    "ledger_journals",
    "ledger_entries",
    "payment_reconciliations",
    "beneficiary_change_requests",
}

_REQUIRED_COLUMNS = {
    "trade_payment_ledger": {
        "case_id",
        "currency",
        "supplier_payout_authorized",
        "shipment_release_authorized",
    },
    "trade_payment_events": {"case_id", "event_type", "created_at"},
    "ledger_journals": {"journal_id", "currency", "status", "owner_approved"},
    "ledger_entries": {"entry_id", "journal_id", "account_id", "debit", "credit"},
    "payment_reconciliations": {"reconciliation_id", "currency", "status"},
    "beneficiary_change_requests": {
        "request_id",
        "requested_by_id",
        "verified_by",
        "approved_by",
        "status",
    },
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


def _probe() -> dict[str, Any]:
    with psycopg.connect(_database_url(), connect_timeout=10, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            present_tables: set[str] = set()
            for table in sorted(_REQUIRED_TABLES):
                cur.execute("SELECT to_regclass(%s) AS relation", (f"public.{table}",))
                row = cur.fetchone()
                if row and row["relation"] is not None:
                    present_tables.add(table)

            columns: dict[str, set[str]] = {name: set() for name in _REQUIRED_COLUMNS}
            for table in sorted(_REQUIRED_COLUMNS):
                if table not in present_tables:
                    continue
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    """,
                    (table,),
                )
                columns[table] = {row["column_name"] for row in cur.fetchall()}

            index_count = 0
            for table in sorted(present_tables):
                cur.execute(
                    "SELECT count(*) AS n FROM pg_indexes WHERE schemaname = 'public' AND tablename = %s",
                    (table,),
                )
                index_count += int(cur.fetchone()["n"])

            active_usd_accounts = 0
            if "ledger_accounts" in present_tables:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'ledger_accounts'
                    """
                )
                ledger_columns = {row["column_name"] for row in cur.fetchall()}
                if {"active", "currency"}.issubset(ledger_columns):
                    cur.execute(
                        "SELECT count(*) AS n FROM public.ledger_accounts WHERE active = true AND currency = 'USD'"
                    )
                    active_usd_accounts = int(cur.fetchone()["n"])

    missing_tables = sorted(_REQUIRED_TABLES - present_tables)
    missing_columns = {
        table: sorted(required - columns.get(table, set()))
        for table, required in _REQUIRED_COLUMNS.items()
        if table in present_tables and required - columns.get(table, set())
    }
    verified = (
        not missing_tables
        and not missing_columns
        and active_usd_accounts >= 12
        and index_count >= 1
    )
    return {
        "verified": verified,
        "provider": "neon_postgres",
        "required_table_count": len(_REQUIRED_TABLES),
        "present_table_count": len(present_tables),
        "index_count": index_count,
        "active_usd_accounts": active_usd_accounts,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "reason": None if verified else "Required production schema evidence is incomplete",
    }


async def production_schema_evidence() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_probe)
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0][:240] if str(exc).strip() else "unknown database error"
        return {
            "verified": False,
            "provider": "neon_postgres",
            "reason": f"{type(exc).__name__}: {detail}",
            "missing_tables": [],
            "missing_columns": {},
            "fail_closed": True,
        }
