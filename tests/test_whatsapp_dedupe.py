import os
import asyncio

import whatsapp_api


class FakeBackend:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.inserted = []

    async def select(self, table, *, params=None):
        return list(self.rows)

    async def insert(self, table, row):
        self.inserted.append((table, row))
        return [row]


def test_message_seen_true_for_existing_message(monkeypatch):
    backend = FakeBackend([{"message_id": "wamid.1"}])
    monkeypatch.setattr(whatsapp_api, "get_backend", lambda: backend)
    assert asyncio.run(whatsapp_api._message_seen("wamid.1")) is True


def test_message_seen_false_for_new_message(monkeypatch):
    backend = FakeBackend([])
    monkeypatch.setattr(whatsapp_api, "get_backend", lambda: backend)
    assert asyncio.run(whatsapp_api._message_seen("wamid.new")) is False


def test_enqueue_suppresses_recent_duplicate(monkeypatch):
    os.environ["WHATSAPP_AUTOMATION_ENABLED"] = "true"
    os.environ["SAHJONY_APP_BRIDGE_SECRET"] = "x" * 32
    existing = {
        "command_id": "waq_existing",
        "recipient": "5351055349",
        "body": "Hola",
        "dedupe_fingerprint": whatsapp_api.hashlib.sha256(b"5351055349|Hola").hexdigest(),
        "status": "sent",
        "created_at": whatsapp_api._now(),
    }
    backend = FakeBackend([existing])
    monkeypatch.setattr(whatsapp_api, "get_backend", lambda: backend)
    result = asyncio.run(whatsapp_api._enqueue_hermes_message(
        whatsapp_api.WhatsAppSend(to="+5351055349", body="Hola")
    ))
    assert result["status"] == "duplicate_suppressed"
    assert not backend.inserted
