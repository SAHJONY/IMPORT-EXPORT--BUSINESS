from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException

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


def test_openclaw_bridge_signature_accepts_fresh_signed_body(monkeypatch):
    secret = "sahjony-openclaw-test-secret-123456"
    monkeypatch.setenv("OPENCLAW_APP_BRIDGE_SECRET", secret)
    raw = b'{"event_id":"evt_1"}'
    timestamp = str(int(time.time()))
    signature = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        (timestamp + ".").encode("utf-8") + raw,
        hashlib.sha256,
    ).hexdigest()
    whatsapp_api._verify_openclaw_signature(raw, timestamp, signature)


def test_openclaw_bridge_signature_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("OPENCLAW_APP_BRIDGE_SECRET", "sahjony-openclaw-test-secret-123456")
    with pytest.raises(HTTPException) as exc:
        whatsapp_api._verify_openclaw_signature(b"{}", str(int(time.time())), "sha256=invalid")
    assert exc.value.status_code == 401


def test_openclaw_provider_is_selected_from_environment(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVIDER", "openclaw")
    assert whatsapp_api._provider() == "openclaw"
