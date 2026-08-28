from __future__ import annotations

import whatsapp_api


def test_webhook_verify_token_accepts_canonical_name(monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "canonical_verify_token_123")
    monkeypatch.delenv("WHATSAPP_VERIFY_TOKEN", raising=False)
    assert whatsapp_api._env_config()["verify_token"] == "canonical_verify_token_123"


def test_webhook_verify_token_keeps_legacy_alias(monkeypatch):
    monkeypatch.delenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", raising=False)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "legacy_verify_token_123")
    assert whatsapp_api._env_config()["verify_token"] == "legacy_verify_token_123"


def test_whatsapp_full_configuration_requires_signature_secret():
    cfg = {
        "access_token": "EAA-test",
        "phone_number_id": "123",
        "verify_token": "verify-token",
        "app_secret": "",
        "graph_api_version": "v1.0",
    }
    assert whatsapp_api._send_ready(cfg) is True
    assert whatsapp_api._webhook_ready(cfg) is False
    assert whatsapp_api._configured(cfg) is False


def test_opt_out_detection_is_explicit():
    assert whatsapp_api._opt_out("STOP") is True
    assert whatsapp_api._opt_out("No me escribas") is True
    assert whatsapp_api._opt_out("Necesito una cotización") is False
