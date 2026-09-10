import pytest
from fastapi.testclient import TestClient

import telegram_api
import insforge_backend


class FakeBackend:
    def __init__(self):
        self.rows = []

    async def insert(self, table, row):
        assert table == "business_events"
        self.rows.append(row)
        return row


def _client(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(telegram_api, "_webhook_secret", lambda: "test-secret")
    monkeypatch.setattr(insforge_backend, "get_backend", lambda: backend)
    return TestClient(telegram_api.app), backend


def test_telegram_webhook_captures_business_event(monkeypatch):
    client, backend = _client(monkeypatch)
    payload = {"update_id": 10, "message": {"message_id": 5, "text": "Need a container quote", "chat": {"id": 77, "type": "private"}, "from": {"id": 77, "username": "buyer"}}}
    response = client.post("/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"})
    assert response.status_code == 200
    assert response.json()["captured_events"] == 1
    assert backend.rows[0]["event_type"] == "telegram_inbound"
    assert backend.rows[0]["payload"]["binding_commitments_allowed"] is False
    assert backend.rows[0]["payload"]["trade_intake_created"] is False


def test_telegram_webhook_rejects_bad_secret(monkeypatch):
    client, backend = _client(monkeypatch)
    response = client.post("/telegram/webhook", json={"update_id": 11}, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    assert response.status_code == 403
    assert backend.rows == []


def test_channel_post_is_captured_without_owner_authority(monkeypatch):
    client, backend = _client(monkeypatch)
    payload = {"update_id": 12, "channel_post": {"message_id": 9, "text": "Market update", "chat": {"id": -1001, "type": "channel", "title": "SAHJONY"}}}
    response = client.post("/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"})
    body = response.json()
    assert response.status_code == 200
    assert body["has_channel_post"] is True
    assert body["owner_authority_granted"] is False
    assert body["autonomous_commitment_executed"] is False
    assert backend.rows[0]["source_type"] == "telegram_channel"


def test_canonical_bot_username_is_sahjony_global_trade():
    assert telegram_api.CANONICAL_BOT_USERNAME == "@SahjonyGlobalTradeBot"


def test_direct_message_generates_and_sends_sofia_reply(monkeypatch):
    client, _ = _client(monkeypatch)

    async def fake_reply(text, contact_name):
        assert text == "Hola Sofia"
        assert contact_name == "Juan"
        return "Hola Juan. ¿En qué operación comercial te ayudo?"

    async def fake_telegram_call(method, payload=None):
        assert method == "sendMessage"
        assert payload["chat_id"] == "77"
        assert payload["reply_to_message_id"] == 5
        return {"ok": True, "result": {"message_id": 6}}

    monkeypatch.setattr(telegram_api, "generate_sofia_reply", fake_reply)
    monkeypatch.setattr(telegram_api, "_telegram_call", fake_telegram_call)
    payload = {"update_id": 13, "message": {"message_id": 5, "text": "Hola Sofia", "chat": {"id": 77, "type": "private"}, "from": {"id": 77, "first_name": "Juan", "is_bot": False}}}
    response = client.post("/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"})
    assert response.status_code == 200
    assert response.json()["sofia_reply"]["sent"] is True


def test_channel_post_is_not_auto_replied(monkeypatch):
    client, _ = _client(monkeypatch)
    payload = {"update_id": 14, "channel_post": {"message_id": 9, "text": "Public update", "chat": {"id": -1001, "type": "channel", "title": "SAHJONY"}}}
    response = client.post("/telegram/webhook", json=payload, headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"})
    assert response.status_code == 200
    assert response.json()["sofia_reply"]["attempted"] is False
