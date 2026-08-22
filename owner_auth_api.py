from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import (
    OWNER_SESSION_TTL_SECONDS,
    decode_owner_session,
    issue_owner_session,
    owner_email,
    owner_password_configured,
    verify_owner_password,
)


app = FastAPI(title="SAHJONY Owner Authentication", version="1.0.0", docs_url=None, redoc_url=None)


class OwnerLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)


@app.get("/owner-auth/health")
def owner_auth_health():
    return {
        "status": "ok",
        "service": "owner-auth",
        "owner_email": owner_email(),
        "password_configured": owner_password_configured(),
        "session_ttl_seconds": OWNER_SESSION_TTL_SECONDS,
        "full_owner_scope": True,
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
    try:
        token = issue_owner_session(normalized_email)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": "authenticated",
        "role": "owner",
        "email": normalized_email,
        "scope": "owner:full",
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
        "expires_at": payload["exp"],
    }
