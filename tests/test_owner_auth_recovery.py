import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import owner_auth_api as api


class FakeBackend:
    def __init__(self, grants=None):
        self.grants = list(grants or [])
        self.inserted = []
        self.patched = []

    async def insert(self, table, row):
        self.inserted.append((table, row))
        if table == "owner_mfa_recovery_grants":
            self.grants.append(row)
        return [row]

    async def select(self, table, *, params=None):
        if table != "owner_mfa_recovery_grants":
            return []
        expected = (params or {}).get("state_hash", "").removeprefix("eq.")
        return [g for g in self.grants if g.get("state_hash") == expected and g.get("used_at") is None]

    async def patch(self, table, values, *, params):
        self.patched.append((table, values, params))
        expected = params.get("state_hash", "").removeprefix("eq.")
        for grant in self.grants:
            if grant.get("state_hash") == expected:
                grant.update(values)
        return self.grants


def _owner_env(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-test-key-that-is-long")


def test_supabase_aal2_token_is_accepted_as_canonical_owner_session(monkeypatch):
    _owner_env(monkeypatch)
    monkeypatch.setattr(api, "decode_supabase_jwt", lambda token: {
        "sub": "owner-user-id", "email": "owner@example.com", "aal": "aal2", "exp": 9999999999
    })
    monkeypatch.setattr(api, "_membership", lambda user_id, roles: {"role": "owner"})
    payload = api._owner_session_payload("Bearer canonical-supabase-token")
    assert payload["mfa_verified"] is True
    assert payload["scope"] == "owner:full"


def test_supabase_aal1_token_is_rejected_for_owner_os(monkeypatch):
    _owner_env(monkeypatch)
    monkeypatch.setenv("OWNER_MFA_REQUIRED", "true")
    monkeypatch.setattr(api, "decode_supabase_jwt", lambda token: {
        "sub": "owner-user-id", "email": "owner@example.com", "aal": "aal1", "exp": 9999999999
    })
    monkeypatch.setattr(api, "_membership", lambda user_id, roles: {"role": "owner"})
    with pytest.raises(HTTPException) as exc:
        api._owner_session_payload("Bearer aal1-token")
    assert exc.value.status_code == 403


def test_recovery_request_stores_only_hash_and_never_returns_plain_state(monkeypatch):
    _owner_env(monkeypatch)
    backend = FakeBackend()
    monkeypatch.setattr(api, "get_backend", lambda: backend)
    monkeypatch.setattr(api.secrets, "token_urlsafe", lambda n: "STATEVALUE1234567890123456789012345678901234" if n == 32 else "grantid123456789")

    sent = {}
    class Response:
        status_code = 200
        content = b"{}"
    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kwargs):
            sent["url"] = url
            sent["json"] = kwargs["json"]
            return Response()
    monkeypatch.setattr(api.httpx, "AsyncClient", Client)

    result = asyncio.run(api.owner_mfa_recovery_request(api.OwnerMfaRecoveryRequest(email="owner@example.com")))
    assert result["status"] == "sent"
    assert "STATEVALUE" not in str(result)
    assert len(backend.inserted) == 1
    grant = backend.inserted[0][1]
    assert grant["state_hash"] == api._state_hash("STATEVALUE1234567890123456789012345678901234")
    assert "STATEVALUE1234567890123456789012345678901234" in sent["json"]["redirect_to"]


def test_recovery_reset_requires_recent_email_proof_and_deletes_only_verified_totp(monkeypatch):
    _owner_env(monkeypatch)
    state = "RECOVERYSTATE123456789012345678901234567890"
    now = datetime.now(timezone.utc)
    backend = FakeBackend([{
        "id": "grant-1",
        "state_hash": api._state_hash(state),
        "owner_email": "owner@example.com",
        "created_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "used_at": None,
    }])
    monkeypatch.setattr(api, "get_backend", lambda: backend)
    monkeypatch.setattr(api, "decode_supabase_jwt", lambda token: {
        "sub": "owner-user-id",
        "email": "owner@example.com",
        "amr": [{"method": "otp", "timestamp": int(now.timestamp())}],
    })
    monkeypatch.setattr(api, "_membership", lambda user_id, roles: {"role": "owner"})

    deleted_urls = []
    class Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload
            self.content = b"x" if payload is not None else b""
        def json(self): return self._payload
    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, **kwargs):
            return Response(200, {"factors": [
                {"id": "verified-totp", "factor_type": "totp", "status": "verified"},
                {"id": "unverified-totp", "factor_type": "totp", "status": "unverified"},
                {"id": "phone-factor", "factor_type": "phone", "status": "verified"},
            ]})
        async def delete(self, url, **kwargs):
            deleted_urls.append(url)
            return Response(204)
    monkeypatch.setattr(api.httpx, "AsyncClient", Client)

    result = asyncio.run(api.owner_mfa_recovery_reset_factor(
        api.OwnerMfaRecoveryResetRequest(state=state, confirm="RESET_OLD_TOTP"),
        authorization="Bearer verified-recovery-session",
    ))
    assert result["status"] == "ready_to_reenroll"
    assert result["removed_factors"] == 1
    assert len(deleted_urls) == 1 and deleted_urls[0].endswith("/verified-totp")
    assert backend.grants[0]["used_at"] is not None
    audits = [row for table, row in backend.inserted if table == "owner_mfa_recovery_audit"]
    assert audits and audits[0]["secrets_exposed"] is False


def test_recovery_reset_rejects_password_only_session(monkeypatch):
    _owner_env(monkeypatch)
    state = "RECOVERYSTATE123456789012345678901234567890"
    now = datetime.now(timezone.utc)
    backend = FakeBackend([{
        "id": "grant-1", "state_hash": api._state_hash(state), "owner_email": "owner@example.com",
        "created_at": now.isoformat(), "expires_at": (now + timedelta(minutes=10)).isoformat(), "used_at": None,
    }])
    monkeypatch.setattr(api, "get_backend", lambda: backend)
    monkeypatch.setattr(api, "decode_supabase_jwt", lambda token: {
        "sub": "owner-user-id", "email": "owner@example.com",
        "amr": [{"method": "password", "timestamp": int(now.timestamp())}],
    })
    monkeypatch.setattr(api, "_membership", lambda user_id, roles: {"role": "owner"})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.owner_mfa_recovery_reset_factor(
            api.OwnerMfaRecoveryResetRequest(state=state, confirm="RESET_OLD_TOTP"),
            authorization="Bearer password-only-session",
        ))
    assert exc.value.status_code == 403
    assert backend.grants[0]["used_at"] is None


# --- Policy-aware session validation (OWNER_MFA_REQUIRED=false must not
# bounce valid owner sessions; AAL2 is enforced only when the policy requires it)


def _app_token_no_mfa(secret):
    import base64
    import hashlib
    import hmac
    import json as _json
    import time as _time

    now = int(_time.time())
    payload = {
        "role": "owner",
        "email": "owner@example.com",
        "iat": now,
        "exp": now + 3600,
        "scope": "owner:full",
        "mfa_verified": False,
        "identity_provider": "supabase_auth",
    }
    encoded = base64.urlsafe_b64encode(_json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(hmac.new(secret.encode(), encoded.encode("ascii"), hashlib.sha256).digest()).decode().rstrip("=")
    return f"sahjony_owner.{encoded}.{sig}"


def test_supabase_aal1_token_accepted_when_mfa_not_required(monkeypatch):
    _owner_env(monkeypatch)
    monkeypatch.delenv("OWNER_MFA_REQUIRED", raising=False)
    monkeypatch.setattr(api, "decode_supabase_jwt", lambda token: {
        "sub": "owner-user-id", "email": "owner@example.com", "aal": "aal1", "exp": 9999999999
    })
    monkeypatch.setattr(api, "_membership", lambda user_id, roles: {"role": "owner"})
    payload = api._owner_session_payload("Bearer aal1-token")
    assert payload["scope"] == "owner:full"
    # Verified at the policy's assurance level (MFA not required).
    assert payload["mfa_verified"] is True


def test_supabase_aal2_token_accepted_when_mfa_not_required(monkeypatch):
    _owner_env(monkeypatch)
    monkeypatch.delenv("OWNER_MFA_REQUIRED", raising=False)
    monkeypatch.setattr(api, "decode_supabase_jwt", lambda token: {
        "sub": "owner-user-id", "email": "owner@example.com", "aal": "aal2", "exp": 9999999999
    })
    monkeypatch.setattr(api, "_membership", lambda user_id, roles: {"role": "owner"})
    payload = api._owner_session_payload("Bearer aal2-token")
    assert payload["mfa_verified"] is True


def test_app_session_without_mfa_verified_accepted_when_mfa_not_required(monkeypatch):
    _owner_env(monkeypatch)
    monkeypatch.delenv("OWNER_MFA_REQUIRED", raising=False)
    monkeypatch.setenv("OWNER_SESSION_SECRET", "test-session-secret")
    token = api.issue_owner_session("owner@example.com", mfa_verified=False)
    payload = api._owner_session_payload("Bearer " + token)
    assert payload["scope"] == "owner:full"
    assert payload["mfa_verified"] is False


def test_app_session_without_mfa_verified_rejected_when_mfa_required(monkeypatch):
    _owner_env(monkeypatch)
    monkeypatch.setenv("OWNER_MFA_REQUIRED", "true")
    monkeypatch.setenv("OWNER_SESSION_SECRET", "test-session-secret")
    token = _app_token_no_mfa("test-session-secret")
    assert api.decode_owner_session(token) is None
    with pytest.raises(HTTPException) as exc:
        api._owner_session_payload("Bearer " + token)
    assert exc.value.status_code == 401


def test_owner_session_endpoint_reports_mfa_policy_flag(monkeypatch):
    _owner_env(monkeypatch)
    monkeypatch.setenv("OWNER_SESSION_SECRET", "test-session-secret")

    monkeypatch.delenv("OWNER_MFA_REQUIRED", raising=False)
    token = api.issue_owner_session("owner@example.com", mfa_verified=False)
    body = api.owner_session("Bearer " + token)
    assert body["mfa_required"] is False
    assert body["mfa_verified"] is False

    monkeypatch.setenv("OWNER_MFA_REQUIRED", "true")
    body = None
    # Token issued without MFA must not validate once the policy requires it.
    with pytest.raises(HTTPException) as exc:
        api.owner_session("Bearer " + token)
    assert exc.value.status_code == 401
