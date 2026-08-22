import hashlib
import hmac
import os
import secrets

from fastapi import Header, HTTPException

from database import get_connection


def _owner_token() -> str:
    token = os.getenv("OWNER_TOKEN")
    if not token:
        raise RuntimeError("OWNER_TOKEN must be configured; insecure fallback tokens are disabled")
    return token


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_owner(token: str | None = Header(None, alias="Authorization")):
    if not token or not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    provided = token.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, _owner_token()):
        raise HTTPException(status_code=403, detail="Invalid owner token")
    return True


def verify_participant(token: str | None = Header(None, alias="Authorization")):
    if not token or not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    provided = token.removeprefix("Bearer ").strip()
    token_hash = hash_token(provided)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT participant_id, business_id FROM participants WHERE token_hash = ?",
        (token_hash,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=403, detail="Invalid participant token")
    return {"participant_id": row["participant_id"], "business_id": row["business_id"]}


def generate_participant_token() -> str:
    return secrets.token_urlsafe(48)
