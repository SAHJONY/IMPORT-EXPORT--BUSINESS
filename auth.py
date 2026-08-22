import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Header, HTTPException, Request

from database import get_connection


def _required_secret(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} must be configured")
    return value


def _owner_token() -> str:
    return _required_secret("OWNER_TOKEN")


def _employee_token() -> str:
    return _required_secret("EMPLOYEE_TOKEN")


def _session_secret() -> str:
    return _required_secret("AUTH_SESSION_SECRET")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_owner(token: str | None = Header(None, alias="Authorization")):
    if not token or not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    provided = token.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, _owner_token()):
        raise HTTPException(status_code=403, detail="Invalid owner token")
    return True


def verify_employee_token(provided: str) -> bool:
    return hmac.compare_digest(provided, _employee_token())


def verify_owner_token(provided: str) -> bool:
    return hmac.compare_digest(provided, _owner_token())


def _participant_from_token(provided: str):
    token_hash = hash_token(provided)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT participant_id, business_id FROM participants WHERE token_hash = ?", (token_hash,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {"participant_id": row["participant_id"], "business_id": row["business_id"]}


def verify_participant(token: str | None = Header(None, alias="Authorization")):
    if not token or not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    info = _participant_from_token(token.removeprefix("Bearer ").strip())
    if not info:
        raise HTTPException(status_code=403, detail="Invalid participant token")
    return info


def verify_customer_token(provided: str):
    return _participant_from_token(provided)


def create_browser_session(role: str, subject: str = "") -> str:
    payload = {"role": role, "sub": subject, "exp": int(time.time()) + 8 * 60 * 60}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    signature = hmac.new(_session_secret().encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def read_browser_session(request: Request):
    token = request.cookies.get("trade_os_session")
    if not token or "." not in token:
        return None
    encoded, signature = token.rsplit(".", 1)
    expected = hmac.new(_session_secret().encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def require_browser_role(request: Request, role: str):
    session = read_browser_session(request)
    if not session or session.get("role") != role:
        return None
    return session


def generate_participant_token() -> str:
    return secrets.token_urlsafe(48)
