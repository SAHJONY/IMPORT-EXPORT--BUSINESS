import pytest

from auth import decode_owner_session, issue_owner_session, owner_email, verify_owner_token


def _configure_owner(monkeypatch):
    monkeypatch.setenv("OWNER_EMAIL", "owner@example.com")
    monkeypatch.setenv("OWNER_SESSION_SECRET", "test-session-secret-that-is-long-enough")
    monkeypatch.setenv("OWNER_TOKEN", "legacy-owner-token")
    monkeypatch.setenv("OWNER_MFA_REQUIRED", "true")
    monkeypatch.setenv("OWNER_TOTP_SECRET", "JBSWY3DPEHPK3PXP")


def test_owner_session_cannot_be_issued_without_mfa_when_required(monkeypatch):
    _configure_owner(monkeypatch)
    with pytest.raises(RuntimeError, match="MFA verification is required"):
        issue_owner_session(owner_email())


def test_mfa_verified_owner_session_is_accepted(monkeypatch):
    _configure_owner(monkeypatch)
    token = issue_owner_session(owner_email(), mfa_verified=True)
    payload = decode_owner_session(token)
    assert payload is not None
    assert payload["mfa_verified"] is True
    assert verify_owner_token(token) is True


def test_legacy_owner_token_is_disabled_when_mfa_required(monkeypatch):
    _configure_owner(monkeypatch)
    assert verify_owner_token("legacy-owner-token") is False
