from __future__ import annotations

import asyncio
import os
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


_ALLOWED_TABLES = {
    "trade_payment_ledger",
    "cuba_partner_accounts",
    "cuba_partner_referrals",
    "trade_payment_events",
    "ledger_accounts",
    "ledger_journals",
    "ledger_entries",
    "payment_reconciliations",
    "beneficiary_change_requests",
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
    raise RuntimeError("A Postgres database URL is required for governed physical ledgers")


def _table(name: str) -> sql.Identifier:
    if name not in _ALLOWED_TABLES:
        raise ValueError(f"Physical table is not allow-listed: {name}")
    return sql.Identifier(name)


def _connect():
    # Supabase Transaction Pooler is the canonical serverless connection path.
    # Disable psycopg server-side prepared statements: transaction poolers do not
    # guarantee session affinity and prepared statements can fail across requests.
    return psycopg.connect(
        _database_url(),
        autocommit=True,
        connect_timeout=10,
        row_factory=dict_row,
        prepare_threshold=None,
    )


async def insert_row(table: str, row: dict[str, Any]) -> dict[str, Any]:
    if not row:
        raise ValueError("Cannot insert an empty row")
    table_id = _table(table)
    columns = list(row.keys())
    values = [row[c] for c in columns]

    def run() -> dict[str, Any]:
        statement = sql.SQL("INSERT INTO public.{} ({}) VALUES ({}) RETURNING *").format(
            table_id,
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(statement, values)
            result = cur.fetchone()
            return dict(result or {})

    return await asyncio.to_thread(run)


async def select_rows(
    table: str,
    *,
    filters: dict[str, Any] | None = None,
    order_by: str | None = None,
    descending: bool = False,
    limit: int = 300,
) -> list[dict[str, Any]]:
    table_id = _table(table)
    filters = filters or {}
    limit = max(1, min(int(limit), 1000))

    def run() -> list[dict[str, Any]]:
        clauses: list[sql.Composed] = []
        values: list[Any] = []
        for key, value in filters.items():
            clauses.append(sql.SQL("{} = {}").format(sql.Identifier(key), sql.Placeholder()))
            values.append(value)
        statement = sql.SQL("SELECT * FROM public.{}").format(table_id)
        if clauses:
            statement += sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses)
        if order_by:
            statement += sql.SQL(" ORDER BY {} {}").format(
                sql.Identifier(order_by),
                sql.SQL("DESC" if descending else "ASC"),
            )
        statement += sql.SQL(" LIMIT {}") .format(sql.Literal(limit))
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(statement, values)
            return [dict(row) for row in cur.fetchall()]

    return await asyncio.to_thread(run)


async def update_rows(table: str, values: dict[str, Any], *, filters: dict[str, Any]) -> list[dict[str, Any]]:
    if not values:
        raise ValueError("Cannot update with an empty values mapping")
    if not filters:
        raise ValueError("Physical table updates require filters")
    table_id = _table(table)

    def run() -> list[dict[str, Any]]:
        set_parts = [sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in values]
        where_parts = [sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in filters]
        params = list(values.values()) + list(filters.values())
        statement = (
            sql.SQL("UPDATE public.{} SET ").format(table_id)
            + sql.SQL(", ").join(set_parts)
            + sql.SQL(" WHERE ")
            + sql.SQL(" AND ").join(where_parts)
            + sql.SQL(" RETURNING *")
        )
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(statement, params)
            return [dict(row) for row in cur.fetchall()]

    return await asyncio.to_thread(run)
