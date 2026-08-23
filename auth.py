import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from database import get_connection

OWNER_EMAIL_DEFAULT = "sahjonycapitalllc@outlook.com"
OWNER_SESSION_TTL_SECONDS = 8 * 60 * 60
NEON_AUTH_URL_DEFAULT = "https://ep-empty-shadow-ayfporoz.neonauth.c-5.us-east-2.aws.neon.tech/neondb/auth"
NEON_AUTH_JWKS_URL_DEFAULT = NEON_AUTH_URL_DEFAULT + "/.well-known/jwks.json"


def _true(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _production_identity_required() -> bool:
    provider = os.getenv("AUTH_PROVIDER", "").strip().lower()
    return _true("PRODUCTION_MODE") and provider in {"insforge", "neon", "neon_auth"} and not _true("ALLOW_LEGACY_LOCAL_AUTH")


def neon_auth_url() -> str:
    return os.getenv("NEON_AUTH_URL", NEON_AUTH_URL_DEFAULT).strip().rstrip("/")


def neon_auth_jwks_url() -> str:
    return os.getenv("NEON_AUTH_JWKS_URL", NEON_AUTH_JWKS_URL_DEFAULT).strip()


@lru_cache(maxsize=1)
def _neon_jwk_client() -> PyJWKClient:
    return PyJWKClient(neon_auth_jwks_url(), cache_keys=True, lifespan=300)


def decode_neon_jwt(token: str) -> dict | None:
    if token.count(".") != 2:
        return None
    try:
        header = jwt.get_unverified_header(token)
        alg = str(header.get("alg", ""))
        if alg not in {"RS256", "ES256", "EdDSA"}:
            return None
        signing_key = _neon_jwk_client().get_signing_key_from_jwt(token)
        options = {"require": ["exp", "sub"], "verify_aud": False}
        claims = jwt.decode(token, signing_key.key, algorithms=[alg], options=options)
        if claims.get("banned") is True:
            return None
        return claims
    except Exception:
        return None


def _allowed_employee_emails() -> set[str]:
    raw = os.getenv("NEON_EMPLOYEE_EMAILS", "")
    return {x.strip().lower() for x in raw.split(",") if x.strip()}


def verify_employee_neon_token(token: str) -> dict | None:
    claims = decode_neon_jwt(token)
    if not claims:
        return None
    role = str(claims.get("role", "")).strip().lower()
    email = str(claims.get("email", "")).strip().lower()
    if role in {"employee", "staff", "admin"} or email in _allowed_employee_emails():
        return claims
    return None


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
            derived = hashlib.pbkdf2_hmac("sha256", provided.encode(), salt.encode(), int(iterations)).hex()
            return hmac.compare_digest(derived, expected)
        except (ValueError, TypeError):
            return False
    plain = os.getenv("OWNER_PASSWORD")
    return bool(plain) and hmac.compare_digest(provided, plain)


def owner_mfa_required() -> bool:
    return _true("OWNER_MFA_REQUIRED")


def owner_totp_configured() -> bool:
    return bool(os.getenv("OWNER_TOTP_SECRET", "").strip())


def _totp_secret_bytes() -> bytes:
    raw = os.getenv("OWNER_TOTP_SECRET", "").strip().replace(" ", "").upper()
    if not raw:
        raise RuntimeError("OWNER_TOTP_SECRET must be configured when owner MFA is required")
    try:
        return base64.b32decode(raw + "=" * (-len(raw) % 8), casefold=True)
    except Exception as exc:
        raise RuntimeError("OWNER_TOTP_SECRET is not valid base32") from exc


def _totp_at(counter: int) -> str:
    digest = hmac.new(_totp_secret_bytes(), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify_owner_totp(provided: str, *, at_time: int | None = None, window: int = 1) -> bool:
    if not provided or len(provided) != 6 or not provided.isdigit():
        return False
    if not owner_totp_configured():
        return False
    now = int(time.time()) if at_time is None else int(at_time)
    counter = now // 30
    try:
        return any(hmac.compare_digest(provided, _totp_at(counter + drift)) for drift in range(-window, window + 1))
    except RuntimeError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_owner_session(email: str, ttl_seconds: int = OWNER_SESSION_TTL_SECONDS, *, mfa_verified: bool = False) -> str:
    normalized = email.strip().lower()
    if normalized != owner_email():
        raise ValueError("Owner identity mismatch")
    if owner_mfa_required() and not mfa_verified:
        raise RuntimeError("Owner MFA verification is required before issuing a privileged session")
    now = int(time.time())
    payload = {
        "role": "owner",
        "email": normalized,
        "iat": now,
        "exp": now + ttl_seconds,
        "scope": "owner:full",
        "mfa_verified": bool(mfa_verified),
    }
    encoded = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(_session_secret().encode(), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"sahjony_owner.{encoded}.{_b64url_encode(signature)}"


def decode_owner_session(token: str) -> dict | None:
    if not token.startswith("sahjony_owner."):
        return None
    try:
        _, encoded, supplied_signature = token.split(".", 2)
        expected_signature = hmac.new(_session_secret().encode(), encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(supplied_signature), expected_signature):
            return None
        payload = json.loads(_b64url_decode(encoded).decode())
        if payload.get("role") != "owner" or payload.get("scope") != "owner:full":
            return None
        if str(payload.get("email", "")).lower() != owner_email():
            return None
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        if owner_mfa_required() and payload.get("mfa_verified") is not True:
            return None
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, RuntimeError):
        return None


def verify_owner_token(provided: str) -> bool:
    legacy = _owner_token_optional()
    if legacy and not owner_mfa_required() and hmac.compare_digest(provided, legacy):
        return True
    return decode_owner_session(provided) is not None


def verify_customer_token(provided: str):
    claims = decode_neon_jwt(provided)
    if claims:
        return {
            "participant_id": str(claims.get("sub")),
            "business_id": claims.get("activeOrganizationId") or claims.get("organizationId"),
            "email": claims.get("email"),
            "name": claims.get("name"),
            "identity_provider": "neon_auth",
        }
    if _production_identity_required():
        return None
    token_hash = hash_token(provided)
    conn = get_connection()
    try:
        row = conn.execute("SELECT participant_id, business_id FROM participants WHERE token_hash = ?", (token_hash,)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"participant_id": row["participant_id"], "business_id": row["business_id"], "identity_provider": "legacy"}


def verify_owner(token: str | None = Header(None, alias="Authorization")):
    if not token or not token.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    if not verify_owner_token(token.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid or expired owner session")
    return True


def verify_participant(token: str | None = Header(None, alias="Authorization")):
    if not token or not token.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    info = verify_customer_token(token.removeprefix("Bearer ").strip())
    if not info:
        raise HTTPException(403, "Invalid or expired customer identity")
    return info


def generate_participant_token() -> str:
    if _production_identity_required():
        raise RuntimeError("Legacy participant token issuance is disabled in production")
    return secrets.token_urlsafe(48)
