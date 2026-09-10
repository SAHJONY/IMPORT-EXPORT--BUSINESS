from pathlib import Path


LOGIN = (Path(__file__).parents[1] / "public" / "owner-login.html").read_text()


def test_owner_login_uses_same_origin_server_authentication():
    assert 'fetch("/owner-auth/login"' in LOGIN
    assert 'sessionStorage.setItem("sahjony.owner.token", body.token)' in LOGIN
    assert "signInWithPassword" not in LOGIN


def test_login_does_not_require_the_optional_supabase_cdn():
    assert "window.supabase?.createClient" in LOGIN
    assert "if (!sb)" in LOGIN


def test_mfa_ui_follows_server_policy():
    assert 'fetch("/owner-auth/health"' in LOGIN
    assert "if (policy.mfa_required)" in LOGIN
    assert "await authenticateOwner(code)" in LOGIN
