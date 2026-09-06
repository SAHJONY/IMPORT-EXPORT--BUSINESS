import os
from fastapi.testclient import TestClient

import telegram_api

client = TestClient(telegram_api.app)


def test_health_flags_canonical_bot_identity(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_USERNAME', '@SahjonyGlobalTradeBot')
    response = client.get('/telegram/health')
    body = response.json()
    assert body['canonical_bot_username'] == '@SahjonyGlobalTradeBot'
    assert body['bot_identity_matches_canonical'] is True


def test_health_flags_stale_bot_username(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_USERNAME', '@sahjonyllc')
    response = client.get('/telegram/health')
    body = response.json()
    assert body['bot_identity_matches_canonical'] is False
