from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import InsForgeBackend, NeonPostgresBackend, get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY Owner Data Control", version="1.0.0", docs_url=None, redoc_url=None)

_TABLE_RE = re.compile(r"^[A-Za-z0-9_]{1,96}$")
KNOWN_TABLES = [
    "customer_accounts", "customer_trade_intakes", "customer_crm_audit",
    "communications_events", "communications_timeline", "business_email_events",
    "global_sourcing_requests", "managed_trade_requests", "intermediary_engagements",
    "shipments", "documents", "compliance_records", "commercial_records",
    "finance_journals", "finance_ledger", "country_crm_leads", "country_crm_accounts",
    "cuba_private_businesses", "cuba_private_sector_leads", "lead_scout_leads",
    "energy_buyers", "energy_sellers", "energy_matches", "energy_deals",
    "data_deletion_audit",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if not verify_owner_token(token):
        raise HTTPException(403, "Invalid owner credential")


def safe_table(table: str) -> str:
    if not _TABLE_RE.fullmatch(table or ""):
        raise HTTPException(400, "Invalid logical table name")
    return table


def record_key(row: dict[str, Any]) -> str:
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
    raise HTTPException(409, "Record has no stable identifier and cannot be safely deleted")


class DeleteRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=160)
    field: str | None = Field(default=None, max_length=96)
    value: str | None = Field(default=None, max_length=500)
    delete_all: bool = False
    reason: str | None = Field(default=None, max_length=1000)


async def inventory_rows() -> list[dict[str, Any]]:
    backend = get_backend()
    if isinstance(backend, NeonPostgresBackend):
        await backend._bootstrap()
        def run() -> list[dict[str, Any]]:
            with backend._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT logical_table, COUNT(*) FROM sahjony_trade_records GROUP BY logical_table ORDER BY logical_table")
                    return [{"table": row[0], "count": int(row[1])} for row in cur.fetchall()]
        import asyncio
        return await asyncio.to_thread(run)
    rows = []
    for table in KNOWN_TABLES:
        try:
            values = await backend.select(table, params={"limit": "5000"}) or []
            if values:
                rows.append({"table": table, "count": len(values)})
        except Exception:
            continue
    return rows


async def delete_rows(table: str, params: dict[str, str]) -> list[dict[str, Any]]:
    backend = get_backend()
    matches = await backend.select(table, params={**params, "limit": "5000"}) or []
    if not matches:
        return []
    if isinstance(backend, NeonPostgresBackend):
        keys = [record_key(row) for row in matches]
        await backend._bootstrap()
        def run() -> None:
            with backend._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM sahjony_trade_records WHERE logical_table = %s AND record_key = ANY(%s)",
                        (table, keys),
                    )
        import asyncio
        await asyncio.to_thread(run)
        return matches
    if isinstance(backend, InsForgeBackend):
        headers = {**backend.headers, "Prefer": "return=representation"}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(backend._records_url(table), headers=headers, params=params)
            response.raise_for_status()
        return matches
    raise HTTPException(501, "Persistent backend does not support deletion")


async def audit_delete(table: str, count: int, *, field: str | None, value: str | None, delete_all: bool, reason: str | None) -> None:
    try:
        await get_backend().insert("data_deletion_audit", {
            "event_id": f"del_{secrets.token_urlsafe(10)}",
            "actor_role": "owner",
            "event_type": "data_deleted",
            "logical_table": table,
            "deleted_count": count,
            "filter_field": field,
            "filter_value": value,
            "delete_all": delete_all,
            "reason": reason,
            "created_at": now(),
        })
    except Exception:
        pass


@app.get("/data-control/health")
async def health() -> dict[str, Any]:
    status = persistent_backend_status()
    return {
        "status": "ok" if status["configured"] else "configuration_required",
        "service": "owner-data-control",
        "owner_only": True,
        "supports_record_delete": True,
        "supports_bulk_purge": True,
        "audit_tombstones": True,
        "persistence": status["provider"],
    }


@app.get("/data-control/inventory")
async def inventory(authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    owner(authorization)
    return {"tables": await inventory_rows()}


@app.get("/data-control/records/{table}")
async def records(
    table: str,
    limit: int = Query(default=50, ge=1, le=250),
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    owner(authorization)
    table = safe_table(table)
    rows = await get_backend().select(table, params={"limit": str(limit)}) or []
    return {"table": table, "records": rows}


@app.delete("/data-control/records/{table}")
async def delete_data(
    table: str,
    payload: DeleteRequest,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    owner(authorization)
    table = safe_table(table)
    if payload.delete_all:
        expected = f"DELETE ALL {table}"
        if payload.confirmation != expected:
            raise HTTPException(409, f"Bulk purge requires exact confirmation: {expected}")
        params: dict[str, str] = {}
    else:
        if payload.confirmation != "DELETE":
            raise HTTPException(409, "Record deletion requires exact confirmation: DELETE")
        if not payload.field or payload.value is None:
            raise HTTPException(400, "field and value are required for record deletion")
        if not _TABLE_RE.fullmatch(payload.field):
            raise HTTPException(400, "Invalid filter field")
        params = {payload.field: f"eq.{payload.value}"}
    deleted = await delete_rows(table, params)
    await audit_delete(table, len(deleted), field=payload.field, value=payload.value, delete_all=payload.delete_all, reason=payload.reason)
    return {"status": "deleted", "table": table, "deleted_count": len(deleted), "delete_all": payload.delete_all}
