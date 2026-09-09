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


def test_expired_dispatch_lease_fails_closed(monkeypatch):
    expired = {
        "command_id": "waq_expired",
        "recipient": "5351055349",
        "body": "Hola",
        "status": "dispatching",
        "attempts": 1,
        "lease_token": "stale-lease",
        "lease_expires_at": "2020-01-01T00:00:00+00:00",
    }
    backend = FakeBackend([expired])
    monkeypatch.setattr(whatsapp_api, "get_backend", lambda: backend)
    monkeypatch.setattr(whatsapp_api, "_verify_hermes_signature", lambda *args, **kwargs: None)

    result = asyncio.run(whatsapp_api.hermes_outbox(limit=10))

    assert result["commands"] == []
    assert result["count"] == 0
    assert len(backend.inserted) == 1
    _, quarantined = backend.inserted[0]
    assert quarantined["status"] == "needs_review"
    assert quarantined["last_error"] == "dispatch_lease_expired_fail_closed"
    assert quarantined["lease_token"] is None
    assert quarantined["lease_expires_at"] is None
