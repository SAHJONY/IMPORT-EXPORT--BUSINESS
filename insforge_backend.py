from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from typing import Any

import httpx


class PersistentBackendConfigurationError(RuntimeError):
    pass


InsForgeConfigurationError = PersistentBackendConfigurationError


def _database_url() -> str:
    for name in ("DATABASE_URL", "POSTGRES_URL", "NEON_DATABASE_URL", "NEON_POSTGRES_URL", "POSTGRES_PRISMA_URL"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _supabase_config() -> tuple[str, str]:
    base = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
    )
    return base, key


def persistent_backend_status() -> dict[str, Any]:
    supabase_url, supabase_key = _supabase_config()
    supabase = bool(supabase_url and supabase_key)
    database_url = bool(_database_url())
    insforge = bool(os.getenv("INSFORGE_BASE_URL", "").strip() and os.getenv("INSFORGE_API_KEY", "").strip())
    provider = "supabase" if supabase else ("postgres_legacy" if database_url else ("insforge" if insforge else "unconfigured"))
    return {
        "configured": supabase or database_url or insforge,
        "provider": provider,
        "supabase_configured": supabase,
        "database_url_configured": database_url,
        "insforge_configured": insforge,
        "durable": supabase or database_url or insforge,
        "canonical": "supabase",
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
    if lower == "true": return True
    if lower == "false": return False
    if lower in {"null", "none"}: return None
    try:
        return float(value) if "." in value else int(value)
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
            if str(actual) != expression: return False
            continue
        op, raw = expression.split(".", 1)
        expected = _coerce(raw)
        if op == "eq" and actual != expected: return False
        if op == "neq" and actual == expected: return False
        if op == "is":
            if expected is None and actual is not None: return False
            if expected is not None and actual != expected: return False
        if op == "in":
            allowed = {_coerce(item.strip()) for item in raw.strip("()").split(",") if item.strip()}
            if actual not in allowed: return False
        if op in {"gt", "gte", "lt", "lte"}:
            try:
                if op == "gt" and not actual > expected: return False
                if op == "gte" and not actual >= expected: return False
                if op == "lt" and not actual < expected: return False
                if op == "lte" and not actual <= expected: return False
            except TypeError:
                return False
        if op in {"like", "ilike"}:
            pattern = "^" + re.escape(str(expected)).replace(r"\*", ".*") + "$"
            flags = re.I if op == "ilike" else 0
            if re.match(pattern, str(actual or ""), flags) is None: return False
    return True


class SupabaseBackend:
    """Canonical durable backend for the entire SAHJONY Global Trade application."""

    def __init__(self) -> None:
        self.base_url, self.service_key = _supabase_config()
        if not self.base_url or not self.service_key:
            raise PersistentBackendConfigurationError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }

    @property
    def records_url(self) -> str:
        return f"{self.base_url}/rest/v1/sahjony_trade_records"

    async def metadata(self) -> dict[str, Any]:
        headers = {**self.headers, "Prefer": "count=exact"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(self.records_url, headers=headers, params={"select": "logical_table", "limit": "1"})
            response.raise_for_status()
            content_range = response.headers.get("content-range", "")
            total = content_range.rsplit("/", 1)[-1] if "/" in content_range else None
            try: total = int(total) if total not in (None, "*") else None
            except ValueError: total = None
            return {"provider": "supabase", "logical_records": total, "status": "ok", "canonical": True}

    async def insert(self, table: str, rows: dict[str, Any] | list[dict[str, Any]]) -> Any:
        logical_table = _safe_table(table)
        payload = rows if isinstance(rows, list) else [rows]
        body = [
            {"logical_table": logical_table, "record_key": _record_key(row), "data": row}
            for row in payload
        ]
        headers = {**self.headers, "Prefer": "resolution=merge-duplicates,return=representation"}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(self.records_url, headers=headers, params={"on_conflict": "logical_table,record_key"}, json=body)
            response.raise_for_status()
            result = response.json() if response.content else []
        return [item.get("data", item) for item in result] if isinstance(result, list) else result

    async def select(self, table: str, *, params: dict[str, str] | None = None) -> Any:
        logical_table = _safe_table(table)
        params = params or {}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                self.records_url,
                headers=self.headers,
                params={"logical_table": f"eq.{logical_table}", "select": "data,record_key,updated_at", "limit": "10000"},
            )
            response.raise_for_status()
            payload = response.json() if response.content else []
        rows = [item.get("data") for item in payload if isinstance(item, dict) and isinstance(item.get("data"), dict)]
        rows = [row for row in rows if _matches(row, params)]
        order = params.get("order", "")
        if order:
            field, _, direction = order.partition(".")
            rows.sort(key=lambda row: (row.get(field) is None, row.get(field)), reverse=direction.lower() == "desc")
        try: offset = max(0, int(params.get("offset", "0")))
        except ValueError: offset = 0
        try: limit = max(0, min(10000, int(params.get("limit", "5000"))))
        except ValueError: limit = 5000
        return rows[offset:offset + limit]

    async def patch(self, table: str, values: dict[str, Any], *, params: dict[str, str]) -> Any:
        logical_table = _safe_table(table)
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                self.records_url,
                headers=self.headers,
                params={"logical_table": f"eq.{logical_table}", "select": "record_key,data", "limit": "10000"},
            )
            response.raise_for_status()
            existing = response.json() if response.content else []
            updated: list[dict[str, Any]] = []
            headers = {**self.headers, "Prefer": "return=minimal"}
            for item in existing:
                row = item.get("data") if isinstance(item, dict) else None
                record_key = item.get("record_key") if isinstance(item, dict) else None
                if not isinstance(row, dict) or not record_key or not _matches(row, params):
                    continue
                merged = {**row, **values}
                patch_response = await client.patch(
                    self.records_url,
                    headers=headers,
                    params={"logical_table": f"eq.{logical_table}", "record_key": f"eq.{record_key}"},
                    json={"data": merged},
                )
                patch_response.raise_for_status()
                updated.append(merged)
            return updated


class PostgresLegacyBackend:
    """Compatibility fallback only. Supabase is canonical whenever configured."""

    def __init__(self) -> None:
        self.database_url = _database_url()
        if not self.database_url:
            raise PersistentBackendConfigurationError("No PostgreSQL DATABASE_URL is configured")
        self._bootstrapped = False
        self._bootstrap_lock = asyncio.Lock()

    def _connect(self):
        import psycopg
        return psycopg.connect(self.database_url, autocommit=True, connect_timeout=10)

    def _bootstrap_sync(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""CREATE TABLE IF NOT EXISTS sahjony_trade_records (logical_table TEXT NOT NULL, record_key TEXT NOT NULL, data JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), PRIMARY KEY (logical_table, record_key))""")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_sahjony_trade_records_table_updated ON sahjony_trade_records (logical_table, updated_at DESC)")

    async def _bootstrap(self) -> None:
        if self._bootstrapped: return
        async with self._bootstrap_lock:
            if not self._bootstrapped:
                await asyncio.to_thread(self._bootstrap_sync)
                self._bootstrapped = True

    async def metadata(self) -> dict[str, Any]:
        await self._bootstrap()
        def run():
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT current_database(), current_user, COUNT(*) FROM sahjony_trade_records")
                    database, user, count = cur.fetchone()
                    return {"provider": "postgres_legacy", "database": database, "user": user, "logical_records": count, "status": "ok"}
        return await asyncio.to_thread(run)

    async def insert(self, table: str, rows: dict[str, Any] | list[dict[str, Any]]) -> Any:
        table = _safe_table(table); await self._bootstrap(); payload = rows if isinstance(rows, list) else [rows]
        def run():
            result=[]
            with self._connect() as conn:
                with conn.cursor() as cur:
                    for row in payload:
                        key=_record_key(row)
                        cur.execute("INSERT INTO sahjony_trade_records (logical_table,record_key,data) VALUES (%s,%s,%s::jsonb) ON CONFLICT (logical_table,record_key) DO UPDATE SET data=EXCLUDED.data,updated_at=NOW() RETURNING data",(table,key,json.dumps(row,default=str)))
                        result.append(cur.fetchone()[0])
            return result
        return await asyncio.to_thread(run)

    async def select(self, table: str, *, params: dict[str, str] | None = None) -> Any:
        table=_safe_table(table); await self._bootstrap(); params=params or {}
        def run():
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT data FROM sahjony_trade_records WHERE logical_table=%s ORDER BY updated_at DESC",(table,))
                    rows=[item[0] for item in cur.fetchall()]
            rows=[r for r in rows if _matches(r,params)]
            try: offset=max(0,int(params.get("offset","0")))
            except ValueError: offset=0
            try: limit=max(0,min(10000,int(params.get("limit","5000"))))
            except ValueError: limit=5000
            return rows[offset:offset+limit]
        return await asyncio.to_thread(run)

    async def patch(self, table: str, values: dict[str, Any], *, params: dict[str, str]) -> Any:
        table=_safe_table(table); await self._bootstrap()
        def run():
            updated=[]
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT record_key,data FROM sahjony_trade_records WHERE logical_table=%s",(table,))
                    for key,row in cur.fetchall():
                        if not _matches(row,params): continue
                        merged={**row,**values}
                        cur.execute("UPDATE sahjony_trade_records SET data=%s::jsonb,updated_at=NOW() WHERE logical_table=%s AND record_key=%s",(json.dumps(merged,default=str),table,key))
                        updated.append(merged)
            return updated
        return await asyncio.to_thread(run)


NeonPostgresBackend = PostgresLegacyBackend


class InsForgeBackend:
    def __init__(self) -> None:
        self.base_url = os.getenv("INSFORGE_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("INSFORGE_API_KEY", "")
        if not self.base_url or not self.api_key:
            raise PersistentBackendConfigurationError("INSFORGE_BASE_URL and INSFORGE_API_KEY must be configured")
    @property
    def headers(self): return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
    def _records_url(self, table: str): return f"{self.base_url}/api/database/records/{_safe_table(table)}"
    async def metadata(self):
        async with httpx.AsyncClient(timeout=10) as client:
            r=await client.get(f"{self.base_url}/api/metadata",headers=self.headers); r.raise_for_status(); return r.json()
    async def insert(self, table: str, rows):
        payload=rows if isinstance(rows,list) else [rows]
        async with httpx.AsyncClient(timeout=20) as client:
            r=await client.post(self._records_url(table),headers={**self.headers,"Prefer":"return=representation"},json=payload); r.raise_for_status(); return r.json() if r.content else None
    async def select(self, table: str, *, params=None):
        async with httpx.AsyncClient(timeout=20) as client:
            r=await client.get(self._records_url(table),headers=self.headers,params=params or {}); r.raise_for_status(); return r.json() if r.content else []
    async def patch(self, table: str, values, *, params):
        async with httpx.AsyncClient(timeout=20) as client:
            r=await client.patch(self._records_url(table),headers={**self.headers,"Prefer":"return=representation"},params=params,json=values); r.raise_for_status(); return r.json() if r.content else None


_backend: SupabaseBackend | PostgresLegacyBackend | InsForgeBackend | None = None


def get_backend() -> SupabaseBackend | PostgresLegacyBackend | InsForgeBackend:
    global _backend
    if _backend is None:
        status = persistent_backend_status()
        if status["supabase_configured"]:
            _backend = SupabaseBackend()
        elif status["database_url_configured"]:
            _backend = PostgresLegacyBackend()
        elif status["insforge_configured"]:
            _backend = InsForgeBackend()
        else:
            raise PersistentBackendConfigurationError("No durable backend is configured. Configure Supabase server credentials.")
    return _backend
