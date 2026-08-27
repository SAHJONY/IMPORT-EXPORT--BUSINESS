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
    "marketplace_suppliers",
    "marketplace_products",
    "marketplace_rfqs",
    "global_sourcing_requests",
    "global_supplier_candidates",
    "global_sourcing_control_evidence",
}

_REQUIRED_COLUMNS = {
    "trade_payment_ledger": {
        "payment_case_id",
        "currency",
        "payment_status",
        "supplier_payout_allowed",
        "shipment_release_allowed",
        "supplier_payout_authorized_at",
        "shipment_release_authorized_at",
    },
    "trade_payment_events": {"event_id", "payment_case_id", "event_type", "currency", "created_at"},
    "cuba_partner_accounts": {"partner_id", "status", "referral_token_hash", "automatic_commission_payout"},
    "cuba_partner_referrals": {"referral_id", "partner_id", "referral_status", "commission_status", "currency"},
    "cuba_consumer_marketplace_requests": {"request_id", "status", "status_token_hash", "payment_allowed", "shipment_allowed"},
    "ledger_accounts": {"account_id", "code", "account_type", "currency", "active"},
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
    "marketplace_suppliers": {"supplier_id", "supplier_type", "verification_tier", "source_url", "status"},
    "marketplace_products": {"product_id", "supplier_id", "price_type", "media_rights_status", "published", "inventory_owned_by_sahjony"},
    "marketplace_rfqs": {"rfq_id", "qualification_status", "status", "inventory_owned_by_sahjony", "sahjony_capital_required"},
    "global_sourcing_requests": {"sourcing_request_id", "destination_country", "worldwide_search", "status"},
    "global_supplier_candidates": {"global_candidate_id", "sourcing_request_id", "source_evidence", "corridor_status", "selected"},
    "global_sourcing_control_evidence": {"evidence_id", "global_candidate_id", "control_key", "verified"},
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
        and index_count >= 10
    )
    return {
        "verified": verified,
        "provider": "neon_postgres",
        "canonical_database": "active_vercel_database_url",
        "required_table_count": len(_REQUIRED_TABLES),
        "present_table_count": len(present_tables),
        "index_count": index_count,
        "active_usd_accounts": active_usd_accounts,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
        "reason": None if verified else "Required canonical production schema evidence is incomplete",
    }


async def production_schema_evidence() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_probe)
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0][:240] if str(exc).strip() else "unknown database error"
        return {
            "verified": False,
            "provider": "neon_postgres",
            "canonical_database": "active_vercel_database_url",
            "reason": f"{type(exc).__name__}: {detail}",
            "missing_tables": [],
            "missing_columns": {},
            "fail_closed": True,
        }
