from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import urlsplit

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


_SUPABASE_ENV_NAMES = (
    "SUPABASE_POSTGRES_URL",
    "SUPABASE_DATABASE_URL",
    "SUPABASE_DB_URL",
)
_GENERIC_ENV_NAMES = (
    "POSTGRES_URL",
    "DATABASE_URL",
    "POSTGRES_PRISMA_URL",
)
_NEON_ENV_NAMES = (
    "NEON_DATABASE_URL",
    "NEON_POSTGRES_URL",
)


def _provider_for_url(value: str) -> str:
    """Classify a DSN without returning or logging any credential material."""
    try:
        host = (urlsplit(value).hostname or "").lower()
    except ValueError:
        host = ""
    if host.endswith(".supabase.co") or host.endswith(".supabase.com"):
        return "supabase"
    if host.endswith(".neon.tech"):
        return "neon"
    return "postgres"


def _database_candidates() -> list[tuple[str, str]]:
    """Return unique DSNs in governed provider order.

    Explicit Supabase variables always win. Supabase URLs found in generic
    variables are tried next, while every Neon URL remains a final fallback.
    """
    configured: list[tuple[str, str, str, int]] = []
    names = _SUPABASE_ENV_NAMES + _GENERIC_ENV_NAMES + _NEON_ENV_NAMES
    for position, name in enumerate(names):
        value = os.getenv(name, "").strip()
        if not value:
            continue
        provider = _provider_for_url(value)
        if name in _SUPABASE_ENV_NAMES:
            priority = 0
        elif provider == "supabase":
            priority = 1
        elif provider == "neon" or name in _NEON_ENV_NAMES:
            priority = 3
        else:
            priority = 2
        configured.append((name, value, provider, priority * 100 + position))

    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for _name, value, provider, _priority in sorted(configured, key=lambda item: item[3]):
        if value in seen:
            continue
        seen.add(value)
        candidates.append((provider, value))
    return candidates


def _table(name: str) -> sql.Identifier:
    if name not in _ALLOWED_TABLES:
        raise ValueError(f"Physical table is not allow-listed: {name}")
    return sql.Identifier(name)


def _connect():
    # Supabase Transaction Pooler is the canonical serverless connection path.
    # Disable psycopg server-side prepared statements: transaction poolers do not
    # guarantee session affinity and prepared statements can fail across requests.
    candidates = _database_candidates()
    if not candidates:
        raise RuntimeError("A Postgres database URL is required for governed physical ledgers")

    last_error: psycopg.Error | None = None
    for _provider, database_url in candidates:
        try:
            return psycopg.connect(
                database_url,
                autocommit=True,
                connect_timeout=10,
                row_factory=dict_row,
                prepare_threshold=None,
            )
        except psycopg.Error as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("No usable Postgres database URL is configured")


async def database_health() -> dict[str, Any]:
    """Probe the governed physical ledger without exposing connection details."""
    def run() -> dict[str, Any]:
        try:
            with _connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 AS ok")
                row = cur.fetchone()
            return {"status": "ok", "configured": True, "reachable": bool(row), "storage": "physical_postgres"}
        except RuntimeError:
            return {"status": "configuration_required", "configured": False, "reachable": False, "storage": "physical_postgres"}
        except psycopg.Error as exc:
            return {"status": "degraded", "configured": True, "reachable": False, "storage": "physical_postgres", "error_type": type(exc).__name__}
        except Exception as exc:
            return {"status": "degraded", "configured": True, "reachable": False, "storage": "physical_postgres", "error_type": type(exc).__name__}
    return await asyncio.to_thread(run)


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
