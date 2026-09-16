import pytest
from fastapi import HTTPException
import owner_auth_api

class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code
        self.content = b""
    def json(self):
        return {}

@pytest.mark.parametrize("status, expected", [(400, 401), (401, 401), (429, 503), (500, 503), (504, 503), (418, 502)])
def test_supabase_password_login_maps_upstream_status(monkeypatch, status, expected):
    monkeypatch.setattr(owner_auth_api, "_supabase_url", lambda: "https://example.supabase.co")
    monkeypatch.setattr(owner_auth_api, "_supabase_key", lambda: "test-key")
    monkeypatch.setattr(owner_auth_api.httpx, "post", lambda *a, **k: FakeResponse(status))
    with pytest.raises(HTTPException) as exc:
        owner_auth_api._supabase_password_login("owner@example.com", "secret")
    assert exc.value.status_code == expected

def test_supabase_timeout_is_not_reported_as_bad_credentials(monkeypatch):
    monkeypatch.setattr(owner_auth_api, "_supabase_url", lambda: "https://example.supabase.co")
    monkeypatch.setattr(owner_auth_api, "_supabase_key", lambda: "test-key")
    monkeypatch.setattr(owner_auth_api.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    with pytest.raises(HTTPException) as exc:
        owner_auth_api._supabase_password_login("owner@example.com", "secret")
    assert exc.value.status_code == 503
    assert "temporarily unreachable" in str(exc.value.detail)
