from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import (
    OWNER_SESSION_TTL_SECONDS,
    _membership,
    decode_owner_session,
    decode_supabase_jwt,
    issue_owner_session,
    owner_email,
    owner_mfa_required,
    owner_password_configured,
    owner_totp_configured,
    verify_owner_totp,
)
from insforge_backend import _matches, _safe_table, get_backend
from governance_policy import AUDIT_RETENTION_DAYS


app = FastAPI(title="SAHJONY Owner Authentication", version="2.0.0", docs_url=None, redoc_url=None)


class OwnerLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    mfa_code: str | None = Field(default=None, min_length=6, max_length=6, pattern=r"^\d{6}$")


class OwnerDataPreviewRequest(BaseModel):
    table: str = Field(min_length=1, max_length=120)
    filters: dict[str, str] = Field(default_factory=dict)
    limit: int = Field(default=50, ge=1, le=250)
    include_system: bool = False


class OwnerDataDeleteRequest(BaseModel):
    table: str = Field(min_length=1, max_length=120)
    filters: dict[str, str] = Field(default_factory=dict)
    confirm: str = Field(min_length=6, max_length=32)
    reason: str | None = Field(default=None, max_length=500)
    include_system: bool = False


PROTECTED_TABLES = {"system_integrations"}
IMMUTABLE_TABLES = {
    "collaboration_access_events",
    "communication_events",
    "communication_policy_events",
    "compliance_audit_events",
    "country_activation_audit",
    "cuba_trade_audit",
    "customer_crm_audit",
    "document_storage_events",
    "energy_audit_events",
    "energy_provider_ingestion_events",
    "lead_scout_audit",
    "managed_trade_audit",
    "owner_data_deletion_audit",
    "trade_agent_audit",
    "translation_audit_events",
    "us_import_audit",
}
COMMON_DATASETS = [
    {"table": "crm_intakes", "label": "CRM leads / intakes"},
    {"table": "customer_intakes", "label": "Customer intakes"},
    {"table": "external_trade_prospects", "label": "External trade prospects / Cuba CRM"},
    {"table": "global_leads", "label": "Global research leads"},
    {"table": "country_leads", "label": "Country CRM leads"},
    {"table": "business_events", "label": "Messages / business events"},
    {"table": "outbound_notifications", "label": "Outbound email / WhatsApp messages"},
    {"table": "email_messages", "label": "Email messages"},
    {"table": "email_threads", "label": "Email threads"},
    {"table": "trade_cases", "label": "Trade cases"},
    {"table": "sourcing_requests", "label": "Sourcing requests"},
    {"table": "suppliers", "label": "Suppliers"},
    {"table": "documents", "label": "Document records"},
    {"table": "shipments", "label": "Shipment records"},
    {"table": "system_integrations", "label": "System integration configuration (protected)"},
]


def _supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip().rstrip("/")


def _supabase_key() -> str:
    return (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
    )


def _owner_session_payload(authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing owner session")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_owner_session(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired owner session")
    return payload


def _validate_table(table: str, *, include_system: bool) -> str:
    table = _safe_table(table.strip())
    if table in IMMUTABLE_TABLES:
        raise HTTPException(status_code=403, detail="Deletion audit records are immutable")
    if table in PROTECTED_TABLES and not include_system:
        raise HTTPException(status_code=403, detail="This is a protected system dataset. Enable include_system to manage it.")
    return table


def _normalize_filters(filters: dict[str, str]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for key, value in filters.items():
        if not re.fullmatch(r"[A-Za-z0-9_]+", key):
            raise HTTPException(status_code=400, detail=f"Invalid filter field: {key}")
        text = str(value).strip()
        if not text:
            continue
        clean[key] = text if "." in text else f"eq.{text}"
    return clean


async def _delete_records(table: str, filters: dict[str, str]) -> int:
    backend = get_backend()
    if hasattr(backend, "_connect"):
        def run() -> int:
            deleted = 0
            with backend._connect() as conn:  # type: ignore[attr-defined]
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT record_key, data FROM sahjony_trade_records WHERE logical_table = %s",
                        (table,),
                    )
                    for record_key, raw in cur.fetchall():
                        row = raw if isinstance(raw, dict) else json.loads(raw)
                        if filters and not _matches(row, filters):
                            continue
                        cur.execute(
                            "DELETE FROM sahjony_trade_records WHERE logical_table = %s AND record_key = %s",
                            (table, record_key),
                        )
                        deleted += cur.rowcount
            return deleted
        import asyncio
        return await asyncio.to_thread(run)

    if hasattr(backend, "delete"):
        result = await backend.delete(table, params=filters)  # type: ignore[attr-defined]
        return len(result) if isinstance(result, list) else (1 if result else 0)

    headers = {**backend.headers, "Prefer": "return=representation"}  # type: ignore[attr-defined]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.delete(backend._records_url(table), headers=headers, params=filters)  # type: ignore[attr-defined]
        response.raise_for_status()
        if not response.content:
            return 0
        payload = response.json()
        return len(payload) if isinstance(payload, list) else 1


@app.get("/owner-auth/health")
def owner_auth_health():
    return {
        "status": "ok" if owner_password_configured() else "configuration_required",
        "service": "owner-auth",
        "identity_provider": "supabase_auth",
        "owner_email": owner_email(),
        "supabase_auth_configured": owner_password_configured(),
        "mfa_required": owner_mfa_required(),
        "mfa_configured": owner_totp_configured(),
        "session_ttl_seconds": OWNER_SESSION_TTL_SECONDS,
        "full_owner_scope": True,
        "owner_data_deletion": True,
        "fail_closed": True,
        "audit_retention_days": AUDIT_RETENTION_DAYS,
        "audit_ledgers_immutable": True,
    }


@app.post("/owner-auth/login")
def owner_login(payload: OwnerLoginRequest):
    normalized_email = payload.email.strip().lower()
    configured_owner = owner_email()
    if configured_owner and normalized_email != configured_owner:
        raise HTTPException(status_code=401, detail="Invalid owner credentials")

    base = _supabase_url()
    key = _supabase_key()
    if not base or not key:
        raise HTTPException(status_code=503, detail="Supabase Auth is not configured in the production environment")

    try:
        response = httpx.post(
            f"{base}/auth/v1/token",
            params={"grant_type": "password"},
            headers={"apikey": key, "Content-Type": "application/json"},
            json={"email": normalized_email, "password": payload.password},
            timeout=15,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Supabase Auth is temporarily unreachable") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid owner credentials")
    auth_payload = response.json() if response.content else {}
    access_token = str(auth_payload.get("access_token") or "")
    claims = decode_supabase_jwt(access_token)
    if not claims:
        raise HTTPException(status_code=401, detail="Supabase owner session could not be verified")

    membership = _membership(str(claims.get("sub") or ""), {"owner"})
    if not membership:
        raise HTTPException(status_code=403, detail="This Supabase account is not authorized as owner")

    mfa_verified = False
    if owner_mfa_required():
        if not owner_totp_configured():
            raise HTTPException(status_code=503, detail="Owner MFA is required but the application TOTP secret is not configured")
        if not payload.mfa_code or not verify_owner_totp(payload.mfa_code):
            raise HTTPException(status_code=401, detail="Invalid owner MFA code")
        mfa_verified = True

    try:
        token = issue_owner_session(normalized_email, mfa_verified=mfa_verified)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "status": "authenticated",
        "role": "owner",
        "email": normalized_email,
        "scope": "owner:full",
        "identity_provider": "supabase_auth",
        "mfa_verified": mfa_verified,
        "token": token,
        "expires_in": OWNER_SESSION_TTL_SECONDS,
    }


@app.get("/owner-auth/session")
def owner_session(authorization: str | None = Header(None, alias="Authorization")):
    payload = _owner_session_payload(authorization)
    return {
        "status": "authenticated",
        "role": "owner",
        "email": payload.get("email"),
        "scope": payload.get("scope", "owner:full"),
        "identity_provider": payload.get("identity_provider", "supabase_auth"),
        "mfa_verified": payload.get("mfa_verified") is True,
        "expires_at": payload.get("exp"),
    }


@app.get("/owner-auth/data/datasets")
def owner_data_datasets(authorization: str | None = Header(None, alias="Authorization")):
    _owner_session_payload(authorization)
    return {
        "datasets": COMMON_DATASETS,
        "advanced_table_access": True,
        "protected_tables": sorted(PROTECTED_TABLES),
        "immutable_tables": sorted(IMMUTABLE_TABLES),
    }


@app.post("/owner-auth/data/preview")
async def owner_data_preview(payload: OwnerDataPreviewRequest, authorization: str | None = Header(None, alias="Authorization")):
    _owner_session_payload(authorization)
    table = _validate_table(payload.table, include_system=payload.include_system)
    filters = _normalize_filters(payload.filters)
    rows = await get_backend().select(table, params={**filters, "limit": str(payload.limit)})
    return {"table": table, "count": len(rows), "rows": rows, "filters": filters}


@app.post("/owner-auth/data/delete")
async def owner_data_delete(payload: OwnerDataDeleteRequest, authorization: str | None = Header(None, alias="Authorization")):
    session = _owner_session_payload(authorization)
    table = _validate_table(payload.table, include_system=payload.include_system)
    filters = _normalize_filters(payload.filters)
    expected = "DELETE" if filters else "DELETE ALL"
    if payload.confirm.strip().upper() != expected:
        raise HTTPException(status_code=400, detail=f"Type {expected} exactly to confirm this deletion")

    before = await get_backend().select(table, params={**filters, "limit": "5000"})
    if not before:
        return {"status": "no_match", "table": table, "deleted": 0}

    deleted = await _delete_records(table, filters)
    audit = {
        "id": f"del_{secrets.token_urlsafe(16)}",
        "table": table,
        "deleted_count": deleted,
        "filter_fields": sorted(filters.keys()),
        "delete_all": not bool(filters),
        "system_dataset": table in PROTECTED_TABLES,
        "reason": payload.reason,
        "owner_email": session.get("email"),
        "performed_at": datetime.now(timezone.utc).isoformat(),
    }
    await get_backend().insert("owner_data_deletion_audit", audit)
    return {"status": "deleted", "table": table, "deleted": deleted, "audit_id": audit["id"]}
