from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import (
    OWNER_SESSION_TTL_SECONDS,
    decode_owner_session,
    issue_owner_session,
    owner_email,
    owner_mfa_required,
    owner_password_configured,
    owner_totp_configured,
    verify_owner_password,
    verify_owner_totp,
)


app = FastAPI(title="SAHJONY Owner Authentication", version="1.1.0", docs_url=None, redoc_url=None)


class OwnerLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    mfa_code: str | None = Field(default=None, min_length=6, max_length=6, pattern=r"^\d{6}$")


@app.get("/owner-auth/health")
def owner_auth_health():
    return {
        "status": "ok",
        "service": "owner-auth",
        "owner_email": owner_email(),
        "password_configured": owner_password_configured(),
        "mfa_required": owner_mfa_required(),
        "mfa_configured": owner_totp_configured(),
        "session_ttl_seconds": OWNER_SESSION_TTL_SECONDS,
        "full_owner_scope": True,
        "fail_closed": True,
    }


@app.post("/owner-auth/login")
def owner_login(payload: OwnerLoginRequest):
    normalized_email = payload.email.strip().lower()
    if normalized_email != owner_email():
        raise HTTPException(status_code=401, detail="Invalid owner credentials")
    if not owner_password_configured():
        raise HTTPException(
            status_code=503,
            detail="Owner password is not configured in the production environment",
        )
    if not verify_owner_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid owner credentials")

    mfa_verified = False
    if owner_mfa_required():
        if not owner_totp_configured():
            raise HTTPException(
                status_code=503,
                detail="Owner MFA is required but OWNER_TOTP_SECRET is not configured",
            )
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
        "mfa_verified": mfa_verified,
        "token": token,
        "expires_in": OWNER_SESSION_TTL_SECONDS,
    }


@app.get("/owner-auth/session")
def owner_session(authorization: str | None = Header(None, alias="Authorization")):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing owner session")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_owner_session(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired owner session")
    return {
        "status": "authenticated",
        "role": "owner",
        "email": payload["email"],
        "scope": payload["scope"],
        "mfa_verified": payload.get("mfa_verified") is True,
        "expires_at": payload["exp"],
    }
