import asyncio

import unified_api as api


def test_shadow_verify_token_uses_canonical_whatsapp_fallback(monkeypatch):
    monkeypatch.delenv("META_WHATSAPP_VERIFY_TOKEN", raising=False)
    monkeypatch.setenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "shadow-test-token")
    monkeypatch.delenv("WHATSAPP_VERIFY_TOKEN", raising=False)

    assert api._whatsapp_shadow_verify_token() == "shadow-test-token"
    health = asyncio.run(api.meta_whatsapp_shadow_health())
    assert health["verify_token_configured"] is True
    assert health["production_authority"] is False
    assert health["auto_reply"] is False
    assert health["binding_commitments"] is False
