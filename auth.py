import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from functools import lru_cache

import httpx
import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from database import get_connection

OWNER_EMAIL_DEFAULT = os.getenv("OWNER_EMAIL", "").strip().lower()
OWNER_SESSION_TTL_SECONDS = 8 * 60 * 60


def _true(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip().rstrip("/")


def _supabase_server_key() -> str:
    return (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.getenv("SUPABASE_SECRET_KEY", "").strip()
        or os.getenv("SUPABASE_KEY", "").strip()
    )


def supabase_auth_url() -> str:
    base = _supabase_url()
    return f"{base}/auth/v1" if base else ""


def supabase_auth_jwks_url() -> str:
    base = supabase_auth_url()
    return f"{base}/.well-known/jwks.json" if base else ""


# Backward-compatible aliases used by existing modules while identity is now Supabase.
def neon_auth_url() -> str:
    return supabase_auth_url()


def neon_auth_jwks_url() -> str:
    return supabase_auth_jwks_url()


@lru_cache(maxsize=1)
def _supabase_jwk_client() -> PyJWKClient:
    url = supabase_auth_jwks_url()
    if not url:
        raise RuntimeError("SUPABASE_URL is not configured")
    return PyJWKClient(url, cache_keys=True, lifespan=300)


def _verify_with_auth_server(token: str) -> dict | None:
    base = supabase_auth_url()
    key = _supabase_server_key()
    if not base or not key:
        return None
    try:
        response = httpx.get(
            f"{base}/user",
            headers={"apikey": key, "Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if response.status_code != 200:
            return None
        user = response.json()
        if not isinstance(user, dict) or not user.get("id"):
            return None
        return {
            "sub": str(user.get("id")),
            "email": user.get("email"),
            "phone": user.get("phone"),
            "user_metadata": user.get("user_metadata") or {},
            "app_metadata": user.get("app_metadata") or {},
            "role": "authenticated",
            "identity_provider": "supabase_auth",
        }
    except Exception:
        return None


def decode_supabase_jwt(token: str) -> dict | None:
    if token.count(".") != 2:
        return None
    try:
        header = jwt.get_unverified_header(token)
        alg = str(header.get("alg", ""))
        if alg in {"RS256", "ES256", "EdDSA"}:
            signing_key = _supabase_jwk_client().get_signing_key_from_jwt(token)
            claims = jwt.decode(token, signing_key.key, algorithms=[alg], options={"require": ["exp", "sub"], "verify_aud": False})
            if claims.get("role") not in {"authenticated", "service_role"}:
                return None
            claims["identity_provider"] = "supabase_auth"
            return claims
    except Exception:
        pass
    return _verify_with_auth_server(token)


# Compatibility name used throughout the existing application.
def decode_neon_jwt(token: str) -> dict | None:
    return decode_supabase_jwt(token)


def _membership(user_id: str, required_roles: set[str] | None = None) -> dict | None:
    base = _supabase_url()
    key = _supabase_server_key()
    if not base or not key or not user_id:
        return None
    try:
        params = {"select": "role,status,customer_id,employee_id,mfa_required", "user_id": f"eq.{user_id}", "status": "eq.active", "limit": "20"}
        response = httpx.get(
            f"{base}/rest/v1/app_memberships",
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        rows = response.json() if response.content else []
        for row in rows if isinstance(rows, list) else []:
            role = str(row.get("role") or "").lower()
            if required_roles is None or role in required_roles:
                return row
    except Exception:
        return None
    return None


def verify_employee_neon_token(token: str) -> dict | None:
    claims = decode_supabase_jwt(token)
    if not claims:
        return None
    membership = _membership(str(claims.get("sub") or ""), {"employee", "owner"})
    if not membership:
        return None
    return {**claims, "app_role": membership.get("role"), "employee_id": membership.get("employee_id")}


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
            if algorithm != "pbkdf2_sha256": return False
            derived = hashlib.pbkdf2_hmac("sha256", provided.encode(), salt.encode(), int(iterations)).hex()
            return hmac.compare_digest(derived, expected)
        except (ValueError, TypeError): return False
    plain = os.getenv("OWNER_PASSWORD")
    return bool(plain) and hmac.compare_digest(provided, plain)


def owner_mfa_required() -> bool:
    return _true("OWNER_MFA_REQUIRED")


def owner_totp_configured() -> bool:
    return bool(os.getenv("OWNER_TOTP_SECRET", "").strip())


def _totp_secret_bytes() -> bytes:
    raw = os.getenv("OWNER_TOTP_SECRET", "").strip().replace(" ", "").upper()
    if not raw: raise RuntimeError("OWNER_TOTP_SECRET must be configured when owner MFA is required")
    return base64.b32decode(raw + "=" * (-len(raw) % 8), casefold=True)


def _totp_at(counter: int) -> str:
    digest = hmac.new(_totp_secret_bytes(), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify_owner_totp(provided: str, *, at_time: int | None = None, window: int = 1) -> bool:
    if not provided or len(provided) != 6 or not provided.isdigit() or not owner_totp_configured(): return False
    counter = (int(time.time()) if at_time is None else int(at_time)) // 30
    try: return any(hmac.compare_digest(provided, _totp_at(counter + drift)) for drift in range(-window, window + 1))
    except RuntimeError: return False


def hash_token(token: str) -> str: return hashlib.sha256(token.encode("utf-8")).hexdigest()
def _b64url_encode(value: bytes) -> str: return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
def _b64url_decode(value: str) -> bytes: return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_owner_session(email: str, ttl_seconds: int = OWNER_SESSION_TTL_SECONDS, *, mfa_verified: bool = False) -> str:
    normalized=email.strip().lower()
    if owner_email() and normalized != owner_email(): raise ValueError("Owner identity mismatch")
    if owner_mfa_required() and not mfa_verified: raise RuntimeError("Owner MFA verification is required before issuing a privileged session")
    now=int(time.time()); payload={"role":"owner","email":normalized,"iat":now,"exp":now+ttl_seconds,"scope":"owner:full","mfa_verified":bool(mfa_verified)}
    encoded=_b64url_encode(json.dumps(payload,separators=(",",":"),sort_keys=True).encode())
    signature=hmac.new(_session_secret().encode(),encoded.encode("ascii"),hashlib.sha256).digest()
    return f"sahjony_owner.{encoded}.{_b64url_encode(signature)}"


def decode_owner_session(token: str) -> dict | None:
    # Preferred path: Supabase Auth user with active owner membership.
    claims = decode_supabase_jwt(token)
    if claims:
        membership = _membership(str(claims.get("sub") or ""), {"owner"})
        if membership:
            return {"role":"owner","scope":"owner:full","email":claims.get("email"),"sub":claims.get("sub"),"exp":claims.get("exp",int(time.time())+3600),"mfa_verified":True,"identity_provider":"supabase_auth"}
    # Temporary legacy owner-session compatibility during cutover.
    if not token.startswith("sahjony_owner."): return None
    try:
        _,encoded,supplied_signature=token.split(".",2)
        expected=hmac.new(_session_secret().encode(),encoded.encode("ascii"),hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(supplied_signature),expected): return None
        payload=json.loads(_b64url_decode(encoded).decode())
        if payload.get("role")!="owner" or payload.get("scope")!="owner:full" or int(payload.get("exp",0))<=int(time.time()): return None
        return payload
    except Exception: return None


def verify_owner_token(provided: str) -> bool: return decode_owner_session(provided) is not None


def verify_customer_token(provided: str):
    claims=decode_supabase_jwt(provided)
    if claims:
        membership=_membership(str(claims.get("sub") or ""), {"customer","employee","owner"})
        if not membership: return None
        return {"participant_id":str(claims.get("sub")),"business_id":membership.get("customer_id"),"email":claims.get("email"),"name":((claims.get("user_metadata") or {}).get("name") if isinstance(claims.get("user_metadata"),dict) else None),"identity_provider":"supabase_auth","app_role":membership.get("role")}
    return None


def verify_owner(token: str | None = Header(None, alias="Authorization")):
    if not token or not token.startswith("Bearer "): raise HTTPException(401,"Missing or malformed Authorization header")
    if not verify_owner_token(token.removeprefix("Bearer ").strip()): raise HTTPException(403,"Invalid or expired owner session")
    return True


def verify_participant(token: str | None = Header(None, alias="Authorization")):
    if not token or not token.startswith("Bearer "): raise HTTPException(401,"Missing or malformed Authorization header")
    info=verify_customer_token(token.removeprefix("Bearer ").strip())
    if not info: raise HTTPException(403,"Invalid or expired Supabase identity or inactive membership")
    return info


def generate_participant_token() -> str:
    raise RuntimeError("Legacy participant token issuance is disabled; use Supabase Auth")
