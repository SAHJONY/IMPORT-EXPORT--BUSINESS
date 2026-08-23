from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx


class PersistentBackendConfigurationError(RuntimeError):
    pass


# Backwards-compatible name used throughout the application.
InsForgeConfigurationError = PersistentBackendConfigurationError


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


def persistent_backend_status() -> dict[str, Any]:
    database_url = bool(_database_url())
    insforge = bool(os.getenv("INSFORGE_BASE_URL", "").strip() and os.getenv("INSFORGE_API_KEY", "").strip())
    provider = "neon_postgres" if database_url else ("insforge" if insforge else "unconfigured")
    return {
        "configured": database_url or insforge,
        "provider": provider,
        "database_url_configured": database_url,
        "insforge_configured": insforge,
        "durable": database_url or insforge,
        "fail_closed": True,
    }


def _safe_table(table: str) -> str:
    if not table or not table.replace("_", "").isalnum():
        raise ValueError("Invalid table name")
    return table


def _record_key(row: dict[str, Any]) -> str:
    preferred = (
        "id", "event_id", "customer_id", "intake_id", "request_id", "case_id",
        "shipment_id", "document_id", "message_id", "payment_id", "supplier_id",
        "candidate_id", "authorization_id", "employee_id", "business_id", "country_id",
        "translation_id", "share_id", "engagement_id", "dossier_id", "incident_id",
        "account_id", "journal_id", "beneficiary_id", "sourcing_request_id",
    )
    for key in preferred:
        value = row.get(key)
        if value not in (None, ""):
            return f"{key}:{value}"
    for key, value in row.items():
        if key.endswith("_id") and value not in (None, ""):
            return f"{key}:{value}"
    return f"uuid:{uuid.uuid4()}"


def _coerce(value: str) -> Any:
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"null", "none"}:
        return None
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _matches(row: dict[str, Any], params: dict[str, str]) -> bool:
    for field, expression in params.items():
        if field in {"limit", "order", "offset", "select"}:
            continue
        actual = row.get(field)
        if not isinstance(expression, str):
            continue
        if "." not in expression:
            if str(actual) != expression:
                return False
            continue
        op, raw = expression.split(".", 1)
        expected = _coerce(raw)
        if op == "eq" and actual != expected:
            return False
        if op == "neq" and actual == expected:
            return False
        if op == "is":
            if expected is None and actual is not None:
                return False
            if expected is not None and actual != expected:
                return False
        if op == "in":
            values = raw.strip("()")
            allowed = {_coerce(item.strip()) for item in values.split(",") if item.strip()}
            if actual not in allowed:
                return False
        if op in {"gt", "gte", "lt", "lte"}:
            try:
                if op == "gt" and not actual > expected:
                    return False
                if op == "gte" and not actual >= expected:
                    return False
                if op == "lt" and not actual < expected:
                    return False
                if op == "lte" and not actual <= expected:
                    return False
            except TypeError:
                return False
        if op == "like":
            pattern = "^" + re.escape(str(expected)).replace(r"\*", ".*") + "$"
            if re.match(pattern, str(actual or ""), re.I) is None:
                return False
        if op == "ilike":
            pattern = "^" + re.escape(str(expected)).replace(r"\*", ".*") + "$"
            if re.match(pattern, str(actual or ""), re.I) is None:
                return False
    return True


class NeonPostgresBackend:
    """Durable logical-record backend for Neon/Postgres.

    Existing Trade OS modules use a PostgREST-like insert/select/patch contract. This
    adapter preserves that contract while storing each logical row as JSONB. It allows
    the whole application to run on a Vercel-provisioned Neon database without forcing
    every business module to be rewritten or requiring an InsForge project first.
    """

    def __init__(self) -> None:
        self.database_url = _database_url()
        if not self.database_url:
            raise PersistentBackendConfigurationError(
                "No durable database is configured. Configure DATABASE_URL/POSTGRES_URL for Neon/Postgres or INSFORGE_BASE_URL + INSFORGE_API_KEY."
            )
        self._bootstrapped = False
        self._bootstrap_lock = asyncio.Lock()

    def _connect(self):
        import psycopg
        return psycopg.connect(self.database_url, autocommit=True, connect_timeout=10)

    def _bootstrap_sync(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sahjony_trade_records (
                        logical_table TEXT NOT NULL,
                        record_key TEXT NOT NULL,
                        data JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (logical_table, record_key)
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_sahjony_trade_records_table_updated ON sahjony_trade_records (logical_table, updated_at DESC)"
                )

    async def _bootstrap(self) -> None:
        if self._bootstrapped:
            return
        async with self._bootstrap_lock:
            if not self._bootstrapped:
                await asyncio.to_thread(self._bootstrap_sync)
                self._bootstrapped = True

    async def metadata(self) -> dict[str, Any]:
        await self._bootstrap()

        def run() -> dict[str, Any]:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT current_database(), current_user, COUNT(*) FROM sahjony_trade_records")
                    database, user, count = cur.fetchone()
                    return {
                        "provider": "neon_postgres",
                        "database": database,
                        "user": user,
                        "logical_records": count,
                        "status": "ok",
                    }
        return await asyncio.to_thread(run)

    async def insert(self, table: str, rows: dict[str, Any] | list[dict[str, Any]]) -> Any:
        table = _safe_table(table)
        await self._bootstrap()
        payload = rows if isinstance(rows, list) else [rows]

        def run() -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            with self._connect() as conn:
                with conn.cursor() as cur:
                    for row in payload:
                        record_key = _record_key(row)
                        cur.execute(
                            """
                            INSERT INTO sahjony_trade_records (logical_table, record_key, data)
                            VALUES (%s, %s, %s::jsonb)
                            ON CONFLICT (logical_table, record_key)
                            DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                            RETURNING data
                            """,
                            (table, record_key, json.dumps(row, default=str)),
                        )
                        returned = cur.fetchone()[0]
                        result.append(returned if isinstance(returned, dict) else json.loads(returned))
            return result

        result = await asyncio.to_thread(run)
        return result

    async def select(self, table: str, *, params: dict[str, str] | None = None) -> Any:
        table = _safe_table(table)
        await self._bootstrap()
        params = params or {}

        def run() -> list[dict[str, Any]]:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT data FROM sahjony_trade_records WHERE logical_table = %s ORDER BY updated_at DESC",
                        (table,),
                    )
                    rows = [item[0] if isinstance(item[0], dict) else json.loads(item[0]) for item in cur.fetchall()]
            rows = [row for row in rows if _matches(row, params)]
            order = params.get("order", "")
            if order:
                field, _, direction = order.partition(".")
                rows.sort(key=lambda row: (row.get(field) is None, row.get(field)), reverse=direction.lower() == "desc")
            try:
                offset = max(0, int(params.get("offset", "0")))
            except ValueError:
                offset = 0
            try:
                limit = max(0, min(5000, int(params.get("limit", "5000"))))
            except ValueError:
                limit = 5000
            return rows[offset:offset + limit]

        return await asyncio.to_thread(run)

    async def patch(self, table: str, values: dict[str, Any], *, params: dict[str, str]) -> Any:
        table = _safe_table(table)
        await self._bootstrap()

        def run() -> list[dict[str, Any]]:
            updated: list[dict[str, Any]] = []
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT record_key, data FROM sahjony_trade_records WHERE logical_table = %s",
                        (table,),
                    )
                    existing = cur.fetchall()
                    for record_key, raw in existing:
                        row = raw if isinstance(raw, dict) else json.loads(raw)
                        if not _matches(row, params):
                            continue
                        merged = {**row, **values}
                        cur.execute(
                            "UPDATE sahjony_trade_records SET data = %s::jsonb, updated_at = NOW() WHERE logical_table = %s AND record_key = %s",
                            (json.dumps(merged, default=str), table, record_key),
                        )
                        updated.append(merged)
            return updated

        return await asyncio.to_thread(run)


class InsForgeBackend:
    """Trusted-server adapter for InsForge admin and database APIs."""

    def __init__(self) -> None:
        self.base_url = os.getenv("INSFORGE_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("INSFORGE_API_KEY", "")
        if not self.base_url or not self.api_key:
            raise PersistentBackendConfigurationError(
                "INSFORGE_BASE_URL and INSFORGE_API_KEY must be configured"
            )

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _records_url(self, table: str) -> str:
        return f"{self.base_url}/api/database/records/{_safe_table(table)}"

    async def metadata(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.base_url}/api/metadata", headers=self.headers)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {"raw": payload}

    async def insert(self, table: str, rows: dict[str, Any] | list[dict[str, Any]]) -> Any:
        payload = rows if isinstance(rows, list) else [rows]
        headers = {**self.headers, "Prefer": "return=representation"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(self._records_url(table), headers=headers, json=payload)
            response.raise_for_status()
            return response.json() if response.content else None

    async def select(self, table: str, *, params: dict[str, str] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(self._records_url(table), headers=self.headers, params=params or {})
            response.raise_for_status()
            return response.json() if response.content else []

    async def patch(self, table: str, values: dict[str, Any], *, params: dict[str, str]) -> Any:
        headers = {**self.headers, "Prefer": "return=representation"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.patch(self._records_url(table), headers=headers, params=params, json=values)
            response.raise_for_status()
            return response.json() if response.content else None


_backend: NeonPostgresBackend | InsForgeBackend | None = None


def get_backend() -> NeonPostgresBackend | InsForgeBackend:
    global _backend
    if _backend is None:
        status = persistent_backend_status()
        if status["database_url_configured"]:
            _backend = NeonPostgresBackend()
        elif status["insforge_configured"]:
            _backend = InsForgeBackend()
        else:
            raise PersistentBackendConfigurationError(
                "No durable trade backend is configured. Add a Neon/Postgres DATABASE_URL (preferred) or InsForge server credentials."
            )
    return _backend
