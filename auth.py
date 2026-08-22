import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Header, HTTPException

from database import get_connection


OWNER_EMAIL_DEFAULT = "sahjonycapitalllc@outlook.com"
OWNER_SESSION_TTL_SECONDS = 8 * 60 * 60


def _true(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _production_identity_required() -> bool:
    return _true("PRODUCTION_MODE") and os.getenv("AUTH_PROVIDER", "").strip().lower() == "insforge" and not _true("ALLOW_LEGACY_LOCAL_AUTH")


def owner_email() -> str:
    return os.getenv("OWNER_EMAIL", OWNER_EMAIL_DEFAULT).strip().lower()


def _owner_token_optional() -> str | None:
    token = os.getenv("OWNER_TOKEN", "").strip()
    return token or None


def _session_secret() -> str:
    secret = os.getenv("OWNER_SESSION_SECRET", "").strip() or (_owner_token_optional() or "")
    if not secret:
        raise RuntimeError("OWNER_SESSION_SECRET or OWNER_TOKEN must be configured")
    return secret


def owner_password_configured() -> bool:
    return bool(os.getenv("OWNER_PASSWORD_HASH", "").strip() or os.getenv("OWNER_PASSWORD", ""))


def verify_owner_password(provided: str) -> bool:
    stored_hash = os.getenv("OWNER_PASSWORD_HASH", "").strip()
    if stored_hash:
        try:
            algorithm, iterations, salt, expected = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            derived = hashlib.pbkdf2_hmac(
                "sha256",
                provided.encode("utf-8"),
                salt.encode("utf-8"),
                int(iterations),
            ).hex()
            return hmac.compare_digest(derived, expected)
        except (ValueError, TypeError):
            return False
    plain = os.getenv("OWNER_PASSWORD")
    return bool(plain) and hmac.compare_digest(provided, plain)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_owner_session(email: str, ttl_seconds: int = OWNER_SESSION_TTL_SECONDS) -> str:
    normalized = email.strip().lower()
    if normalized != owner_email():
        raise ValueError("Owner identity mismatch")
    now = int(time.time())
    payload = {
        "role": "owner",
        "email": normalized,
        "iat": now,
        "exp": now + ttl_seconds,
        "scope": "owner:full",
    }
    encoded = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = hmac.new(_session_secret().encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"sahjony_owner.{encoded}.{_b64url_encode(signature)}"


def decode_owner_session(token: str) -> dict | None:
    if not token.startswith("sahjony_owner."):
        return None
    try:
        _, encoded, supplied_signature = token.split(".", 2)
        expected_signature = hmac.new(
            _session_secret().encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64url_decode(supplied_signature), expected_signature):
            return None
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
        if payload.get("role") != "owner" or payload.get("scope") != "owner:full":
            return None
        if str(payload.get("email", "")).lower() != owner_email():
            return None
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, RuntimeError):
        return None


def verify_owner_token(provided: str) -> bool:
    legacy = _owner_token_optional()
    if legacy and hmac.compare_digest(provided, legacy):
        return True
    return decode_owner_session(provided) is not None


def verify_customer_token(provided: str):
    # The SQLite participant-token path is transitional only. Production InsForge mode must
    # use verified JWT identities + app_memberships/RLS; it fails closed until that client flow is wired.
    if _production_identity_required():
        return None
    token_hash = hash_token(provided)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT participant_id, business_id FROM participants WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"participant_id": row["participant_id"], "business_id": row["business_id"]}


def verify_owner(token: str | None = Header(None, alias="Authorization")):
    if not token or not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    provided = token.removeprefix("Bearer ").strip()
    if not verify_owner_token(provided):
        raise HTTPException(status_code=403, detail="Invalid or expired owner session")
    return True


def verify_participant(token: str | None = Header(None, alias="Authorization")):
    if _production_identity_required():
        raise HTTPException(status_code=503, detail="Legacy participant tokens are disabled in production; use verified InsForge Auth identity")
    if not token or not token.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    provided = token.removeprefix("Bearer ").strip()
    info = verify_customer_token(provided)
    if not info:
        raise HTTPException(status_code=403, detail="Invalid participant token")
    return info


def generate_participant_token() -> str:
    if _production_identity_required():
        raise RuntimeError("Legacy participant token issuance is disabled in production")
    return secrets.token_urlsafe(48)
