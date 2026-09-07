from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
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

app = FastAPI(title="SAHJONY Supabase Identity & Owner Authentication", version="2.1.0", docs_url=None, redoc_url=None)

class OwnerMfaRecoveryRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class OwnerMfaRecoveryResetRequest(BaseModel):
    state: str = Field(min_length=24, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")
    confirm: str = Field(pattern=r"^RESET_OLD_TOTP$")


class OwnerLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    mfa_code: str | None = Field(default=None, min_length=6, max_length=6, pattern=r"^\d{6}$")

class IdentityLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(pattern=r"^(customer|employee)$")

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
    "collaboration_access_events","communication_events","communication_policy_events","compliance_audit_events",
    "country_activation_audit","cuba_trade_audit","customer_crm_audit","document_storage_events","energy_audit_events",
    "energy_provider_ingestion_events","lead_scout_audit","managed_trade_audit","owner_data_deletion_audit",
    "trade_agent_audit","translation_audit_events","us_import_audit",
}
COMMON_DATASETS = [
    {"table":"crm_intakes","label":"CRM leads / intakes"},{"table":"customer_intakes","label":"Customer intakes"},
    {"table":"external_trade_prospects","label":"External trade prospects / Cuba CRM"},{"table":"global_leads","label":"Global research leads"},
    {"table":"country_leads","label":"Country CRM leads"},{"table":"business_events","label":"Messages / business events"},
    {"table":"outbound_notifications","label":"Outbound email / WhatsApp messages"},{"table":"email_messages","label":"Email messages"},
    {"table":"email_threads","label":"Email threads"},{"table":"trade_cases","label":"Trade cases"},
    {"table":"sourcing_requests","label":"Sourcing requests"},{"table":"suppliers","label":"Suppliers"},
    {"table":"documents","label":"Document records"},{"table":"shipments","label":"Shipment records"},
    {"table":"system_integrations","label":"System integration configuration (protected)"},
]

def _supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip().rstrip("/")

def _supabase_key() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip() or os.getenv("SUPABASE_SECRET_KEY", "").strip() or os.getenv("SUPABASE_KEY", "").strip()

def _supabase_password_login(email: str, password: str) -> dict[str, Any]:
    base,key=_supabase_url(),_supabase_key()
    if not base or not key:
        raise HTTPException(status_code=503,detail="Supabase Auth is not configured in the production environment")
    try:
        response=httpx.post(f"{base}/auth/v1/token",params={"grant_type":"password"},headers={"apikey":key,"Content-Type":"application/json"},json={"email":email,"password":password},timeout=15)
    except Exception as exc:
        raise HTTPException(status_code=503,detail="Supabase Auth is temporarily unreachable") from exc
    if response.status_code!=200:
        raise HTTPException(status_code=401,detail="Invalid credentials")
    payload=response.json() if response.content else {}
    access_token=str(payload.get("access_token") or "")
    claims=decode_supabase_jwt(access_token)
    if not claims:
        raise HTTPException(status_code=401,detail="Supabase session could not be verified")
    return {"auth":payload,"access_token":access_token,"claims":claims}

def _owner_session_payload(authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401,detail="Missing owner session")
    token=authorization.removeprefix("Bearer ").strip()

    # Canonical Owner browser sessions are Supabase access tokens.  Verify the
    # token, active owner membership, and AAL2 before authorizing Owner OS.
    claims=decode_supabase_jwt(token)
    if claims:
        membership=_membership(str(claims.get("sub") or ""), {"owner"})
        if not membership:
            raise HTTPException(status_code=403,detail="This Supabase account is not authorized as owner")
        configured_owner=owner_email()
        email=str(claims.get("email") or "").strip().lower()
        if configured_owner and email!=configured_owner:
            raise HTTPException(status_code=403,detail="This Supabase account is not the configured owner")
        # If JWKS verification fell back to /auth/v1/user, enrich only after
        # that server-side verification.  These unverified fields are accepted
        # solely because the same token has already been validated above.
        if claims.get("aal") is None:
            try:
                import jwt as pyjwt
                raw=pyjwt.decode(token, options={"verify_signature":False,"verify_exp":False,"verify_aud":False})
                if str(raw.get("sub") or "")==str(claims.get("sub") or ""):
                    claims={**raw, **claims}
            except Exception:
                pass
        if str(claims.get("aal") or "aal1").lower()!="aal2":
            raise HTTPException(status_code=403,detail="Owner MFA is not yet verified at AAL2")
        return {
            "email": email,
            "scope": "owner:full",
            "identity_provider": "supabase_auth",
            "mfa_verified": True,
            "exp": claims.get("exp"),
            "sub": claims.get("sub"),
        }

    # Backward-compatible application session support for existing internal
    # callers. This path is not used by the public Owner login page.
    payload=decode_owner_session(token)
    if not payload:
        raise HTTPException(status_code=401,detail="Invalid or expired owner session")
    return payload

def _validate_table(table: str, *, include_system: bool) -> str:
    table=_safe_table(table.strip())
    if table in IMMUTABLE_TABLES: raise HTTPException(status_code=403,detail="Deletion audit records are immutable")
    if table in PROTECTED_TABLES and not include_system: raise HTTPException(status_code=403,detail="This is a protected system dataset. Enable include_system to manage it.")
    return table

def _normalize_filters(filters: dict[str,str]) -> dict[str,str]:
    clean={}
    for key,value in filters.items():
        if not re.fullmatch(r"[A-Za-z0-9_]+",key): raise HTTPException(status_code=400,detail=f"Invalid filter field: {key}")
        text=str(value).strip()
        if text: clean[key]=text if "." in text else f"eq.{text}"
    return clean

async def _delete_records(table: str, filters: dict[str,str]) -> int:
    backend=get_backend()
    if hasattr(backend,"_connect"):
        def run()->int:
            deleted=0
            with backend._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT record_key,data FROM sahjony_trade_records WHERE logical_table=%s",(table,))
                    for record_key,raw in cur.fetchall():
                        row=raw if isinstance(raw,dict) else json.loads(raw)
                        if filters and not _matches(row,filters): continue
                        cur.execute("DELETE FROM sahjony_trade_records WHERE logical_table=%s AND record_key=%s",(table,record_key)); deleted+=cur.rowcount
            return deleted
        import asyncio
        return await asyncio.to_thread(run)
    if hasattr(backend,"delete"):
        result=await backend.delete(table,params=filters)
        return len(result) if isinstance(result,list) else (1 if result else 0)
    headers={**backend.headers,"Prefer":"return=representation"}
    async with httpx.AsyncClient(timeout=30) as client:
        response=await client.delete(backend._records_url(table),headers=headers,params=filters); response.raise_for_status()
        if not response.content:return 0
        payload=response.json(); return len(payload) if isinstance(payload,list) else 1

@app.get("/identity/health")
def identity_health_v2():
    configured=bool(_supabase_url() and _supabase_key())
    return {"status":"ok" if configured else "configuration_required","service":"sahjony-identity","provider":"supabase_auth","configured":configured,"customer_login":True,"employee_login":True,"owner_login":True,"membership_authorization":True,"customer_self_signup":True,"fail_closed":True}

@app.post("/identity/login")
def identity_login(payload: IdentityLoginRequest):
    normalized=payload.email.strip().lower(); result=_supabase_password_login(normalized,payload.password); claims=result["claims"]
    allowed={"customer","employee","owner"} if payload.role=="customer" else {"employee","owner"}
    membership=_membership(str(claims.get("sub") or ""),allowed)
    if not membership: raise HTTPException(status_code=403,detail=f"This Supabase account is not authorized for {payload.role} access")
    return {"status":"authenticated","role":payload.role,"app_role":membership.get("role"),"user_id":claims.get("sub"),"email":claims.get("email"),"identity_provider":"supabase_auth","token":result["access_token"],"expires_in":result["auth"].get("expires_in",3600)}

@app.get("/identity/session-v2")
def identity_session_v2(x_role: str | None=Header(None,alias="X-Role"),authorization: str | None=Header(None,alias="Authorization")):
    if x_role not in {"customer","employee"}: raise HTTPException(status_code=400,detail="X-Role must be customer or employee")
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(status_code=401,detail="Missing Authorization")
    claims=decode_supabase_jwt(authorization.removeprefix("Bearer ").strip())
    if not claims: raise HTTPException(status_code=403,detail="Invalid Supabase identity")
    allowed={"customer","employee","owner"} if x_role=="customer" else {"employee","owner"}
    membership=_membership(str(claims.get("sub") or ""),allowed)
    if not membership: raise HTTPException(status_code=403,detail="Inactive or insufficient application membership")
    return {"status":"authenticated","role":x_role,"app_role":membership.get("role"),"user_id":claims.get("sub"),"email":claims.get("email"),"identity_provider":"supabase_auth"}

def _state_hash(state: str) -> str:
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _recovery_amr(claims: dict[str, Any]) -> list[dict[str, Any]]:
    value=claims.get("amr")
    return [entry for entry in value if isinstance(entry,dict)] if isinstance(value,list) else []


@app.post("/owner-auth/recovery/request")
async def owner_mfa_recovery_request(payload: OwnerMfaRecoveryRequest):
    normalized=payload.email.strip().lower()
    configured_owner=owner_email()
    # Keep the response non-enumerating while refusing to send for any other account.
    if configured_owner and normalized!=configured_owner:
        return {"status":"accepted","detail":"If this is the authorized Owner account, a recovery email will be sent."}
    base,key=_supabase_url(),_supabase_key()
    if not base or not key:
        raise HTTPException(status_code=503,detail="Supabase Auth is not configured")
    state=secrets.token_urlsafe(32)
    now=datetime.now(timezone.utc)
    grant={
        "id": f"owner_mfa_recovery_{secrets.token_urlsafe(12)}",
        "state_hash": _state_hash(state),
        "owner_email": normalized,
        "created_at": now.isoformat(),
        "expires_at": (now+timedelta(minutes=15)).isoformat(),
        "used_at": None,
        "purpose": "replace_stale_totp",
    }
    await get_backend().insert("owner_mfa_recovery_grants", grant)
    redirect_to=f"https://www.sahjony.com/owner-mfa-recovery.html?lang=en-US&state={state}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.post(
                f"{base}/auth/v1/recover",
                headers={"apikey":key,"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                json={"email":normalized,"redirect_to":redirect_to},
            )
    except Exception as exc:
        raise HTTPException(status_code=503,detail="Supabase recovery email is temporarily unavailable") from exc
    if response.status_code==429:
        raise HTTPException(status_code=429,detail="Recovery email rate limit exceeded. Wait for the Auth email window to refill, then request exactly one new email.")
    if response.status_code not in {200,204}:
        raise HTTPException(status_code=503,detail="Supabase could not start Owner recovery")
    return {"status":"sent","detail":"Open only the newest Owner recovery email. The link contains a one-time server-bound recovery state."}


@app.post("/owner-auth/recovery/reset-factor")
async def owner_mfa_recovery_reset_factor(
    payload: OwnerMfaRecoveryResetRequest,
    authorization: str | None=Header(None,alias="Authorization"),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401,detail="Missing Supabase recovery session")
    token=authorization.removeprefix("Bearer ").strip()
    verified=decode_supabase_jwt(token)
    if not verified:
        raise HTTPException(status_code=401,detail="Invalid Supabase recovery session")
    user_id=str(verified.get("sub") or "")
    email=str(verified.get("email") or "").strip().lower()
    configured_owner=owner_email()
    if configured_owner and email!=configured_owner:
        raise HTTPException(status_code=403,detail="Recovery session does not belong to the configured Owner")
    if not _membership(user_id,{"owner"}):
        raise HTTPException(status_code=403,detail="Recovery session is not authorized as Owner")

    # Read AMR only after the exact bearer token has been verified by Supabase/JWKS.
    raw=verified
    if not _recovery_amr(raw):
        try:
            import jwt as pyjwt
            candidate=pyjwt.decode(token, options={"verify_signature":False,"verify_exp":False,"verify_aud":False})
            if str(candidate.get("sub") or "")==user_id:
                raw={**candidate, **verified}
        except Exception:
            pass

    state_hash=_state_hash(payload.state)
    grants=await get_backend().select("owner_mfa_recovery_grants",params={"state_hash":f"eq.{state_hash}","used_at":"is.null","limit":"5"})
    if not grants:
        raise HTTPException(status_code=403,detail="Recovery state is invalid, expired, or already used")
    grant=grants[0]
    try:
        created=datetime.fromisoformat(str(grant.get("created_at") or "").replace("Z","+00:00"))
        expires=datetime.fromisoformat(str(grant.get("expires_at") or "").replace("Z","+00:00"))
    except Exception as exc:
        raise HTTPException(status_code=403,detail="Recovery state is invalid") from exc
    now=datetime.now(timezone.utc)
    if created.tzinfo is None: created=created.replace(tzinfo=timezone.utc)
    if expires.tzinfo is None: expires=expires.replace(tzinfo=timezone.utc)
    if now>expires or str(grant.get("owner_email") or "").lower()!=email:
        raise HTTPException(status_code=403,detail="Recovery state is invalid or expired")

    fresh_email_proof=False
    for entry in _recovery_amr(raw):
        method=str(entry.get("method") or "").lower()
        try: ts=float(entry.get("timestamp") or 0)
        except Exception: ts=0
        if method in {"otp","magiclink"} and ts>=created.timestamp()-60 and ts<=now.timestamp()+60:
            fresh_email_proof=True
            break
    if not fresh_email_proof:
        raise HTTPException(status_code=403,detail="Open the newest recovery email link to prove recent mailbox control before replacing MFA")

    # Consume first: replay attempts fail closed even if a downstream admin call fails.
    used_at=now.isoformat()
    await get_backend().patch("owner_mfa_recovery_grants",{"used_at":used_at},params={"state_hash":f"eq.{state_hash}"})

    base,key=_supabase_url(),_supabase_key()
    headers={"apikey":key,"Authorization":f"Bearer {key}","Content-Type":"application/json"}
    async with httpx.AsyncClient(timeout=20) as client:
        factors_response=await client.get(f"{base}/auth/v1/admin/users/{user_id}/factors",headers=headers)
        if factors_response.status_code!=200:
            raise HTTPException(status_code=502,detail="Supabase could not list Owner MFA factors")
        factors_payload=factors_response.json() if factors_response.content else []
        if isinstance(factors_payload,dict):
            factors=factors_payload.get("factors") or factors_payload.get("data") or []
        else:
            factors=factors_payload
        verified_totp=[f for f in factors if isinstance(f,dict) and str(f.get("factor_type") or f.get("type") or "").lower()=="totp" and str(f.get("status") or "").lower()=="verified"]
        for factor in verified_totp:
            factor_id=str(factor.get("id") or "")
            if not factor_id: continue
            deleted=await client.delete(f"{base}/auth/v1/admin/users/{user_id}/factors/{factor_id}",headers=headers)
            if deleted.status_code not in {200,204}:
                raise HTTPException(status_code=502,detail="Supabase could not remove the stale Owner TOTP factor")

    await get_backend().insert("owner_mfa_recovery_audit",{
        "id":f"owner_mfa_recovery_audit_{secrets.token_urlsafe(12)}",
        "owner_email":email,
        "user_id":user_id,
        "verified_totp_removed":len(verified_totp),
        "performed_at":used_at,
        "method":"server_bound_recovery_email_state",
        "secrets_exposed":False,
    })
    return {"status":"ready_to_reenroll","removed_factors":len(verified_totp),"secrets_exposed":False}


@app.get("/owner-auth/health")
def owner_auth_health():
    return {"status":"ok" if owner_password_configured() else "configuration_required","service":"owner-auth","identity_provider":"supabase_auth","owner_email":owner_email(),"supabase_auth_configured":owner_password_configured(),"mfa_required":owner_mfa_required(),"mfa_configured":owner_totp_configured(),"session_ttl_seconds":OWNER_SESSION_TTL_SECONDS,"full_owner_scope":True,"owner_data_deletion":True,"fail_closed":True,"audit_retention_days":AUDIT_RETENTION_DAYS,"audit_ledgers_immutable":True}

@app.post("/owner-auth/login")
def owner_login(payload: OwnerLoginRequest):
    normalized=payload.email.strip().lower(); configured_owner=owner_email()
    if configured_owner and normalized!=configured_owner: raise HTTPException(status_code=401,detail="Invalid owner credentials")
    result=_supabase_password_login(normalized,payload.password); claims=result["claims"]
    membership=_membership(str(claims.get("sub") or ""),{"owner"})
    if not membership: raise HTTPException(status_code=403,detail="This Supabase account is not authorized as owner")
    mfa_verified=False
    if owner_mfa_required():
        if not owner_totp_configured(): raise HTTPException(status_code=503,detail="Owner MFA is required but the application TOTP secret is not configured")
        if not payload.mfa_code or not verify_owner_totp(payload.mfa_code): raise HTTPException(status_code=401,detail="Invalid owner MFA code")
        mfa_verified=True
    try: token=issue_owner_session(normalized,mfa_verified=mfa_verified)
    except RuntimeError as exc: raise HTTPException(status_code=503,detail=str(exc)) from exc
    return {"status":"authenticated","role":"owner","email":normalized,"scope":"owner:full","identity_provider":"supabase_auth","mfa_verified":mfa_verified,"token":token,"expires_in":OWNER_SESSION_TTL_SECONDS}

@app.get("/owner-auth/session")
def owner_session(authorization: str | None=Header(None,alias="Authorization")):
    payload=_owner_session_payload(authorization)
    return {"status":"authenticated","role":"owner","email":payload.get("email"),"scope":payload.get("scope","owner:full"),"identity_provider":payload.get("identity_provider","supabase_auth"),"mfa_verified":payload.get("mfa_verified") is True,"expires_at":payload.get("exp")}

@app.get("/owner-auth/data/datasets")
def owner_data_datasets(authorization: str | None=Header(None,alias="Authorization")):
    _owner_session_payload(authorization); return {"datasets":COMMON_DATASETS,"advanced_table_access":True,"protected_tables":sorted(PROTECTED_TABLES),"immutable_tables":sorted(IMMUTABLE_TABLES)}

@app.post("/owner-auth/data/preview")
async def owner_data_preview(payload: OwnerDataPreviewRequest,authorization: str | None=Header(None,alias="Authorization")):
    _owner_session_payload(authorization); table=_validate_table(payload.table,include_system=payload.include_system); filters=_normalize_filters(payload.filters); rows=await get_backend().select(table,params={**filters,"limit":str(payload.limit)}); return {"table":table,"count":len(rows),"rows":rows,"filters":filters}

@app.post("/owner-auth/data/delete")
async def owner_data_delete(payload: OwnerDataDeleteRequest,authorization: str | None=Header(None,alias="Authorization")):
    session=_owner_session_payload(authorization); table=_validate_table(payload.table,include_system=payload.include_system); filters=_normalize_filters(payload.filters); expected="DELETE" if filters else "DELETE ALL"
    if payload.confirm.strip().upper()!=expected: raise HTTPException(status_code=400,detail=f"Type {expected} exactly to confirm this deletion")
    before=await get_backend().select(table,params={**filters,"limit":"5000"})
    if not before:return {"status":"no_match","table":table,"deleted":0}
    deleted=await _delete_records(table,filters); audit={"id":f"del_{secrets.token_urlsafe(16)}","table":table,"deleted_count":deleted,"filter_fields":sorted(filters.keys()),"delete_all":not bool(filters),"system_dataset":table in PROTECTED_TABLES,"reason":payload.reason,"owner_email":session.get("email"),"performed_at":datetime.now(timezone.utc).isoformat()}; await get_backend().insert("owner_data_deletion_audit",audit); return {"status":"deleted","table":table,"deleted":deleted,"audit_id":audit["id"]}
