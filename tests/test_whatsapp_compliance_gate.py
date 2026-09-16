import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import whatsapp_api as wa


class ComplianceBackend:
    def __init__(self, *, leads=None, inbound=None, recipient_outbound=None, recent_outbound=None):
        self.leads = leads or []
        self.inbound = inbound or []
        self.recipient_outbound = recipient_outbound or []
        self.recent_outbound = recent_outbound or []

    async def select(self, table, *, params=None):
        params = params or {}
        if table == "whatsapp_leads":
            return list(self.leads)
        if table == "whatsapp_messages":
            return list(self.inbound)
        if table == "outbound_notifications":
            if params.get("destination"):
                return list(self.recipient_outbound)
            return list(self.recent_outbound)
        return []


def inbound_row(*, age_hours=1, text="Hello"):
    when = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {"direction": "inbound", "text": text, "received_at": when.isoformat()}


def test_allows_verified_recent_inbound_session(monkeypatch):
    backend = ComplianceBackend(inbound=[inbound_row(age_hours=2)])
    monkeypatch.setattr(wa, "get_backend", lambda: backend)
    result = asyncio.run(wa._assert_compliant_session_outbound("+15551234567"))
    assert result["session_open"] is True
    assert result["mode"] == "customer_service_window"


def test_blocks_without_verified_inbound(monkeypatch):
    backend = ComplianceBackend()
    monkeypatch.setattr(wa, "get_backend", lambda: backend)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(wa._assert_compliant_session_outbound("+15551234567"))
    assert exc.value.status_code == 409
    assert "approved template required" in exc.value.detail


def test_blocks_outside_24_hour_window(monkeypatch):
    backend = ComplianceBackend(inbound=[inbound_row(age_hours=25)])
    monkeypatch.setattr(wa, "get_backend", lambda: backend)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(wa._assert_compliant_session_outbound("+15551234567"))
    assert exc.value.status_code == 409
    assert "24-hour" in exc.value.detail


def test_blocks_opted_out_lead(monkeypatch):
    backend = ComplianceBackend(
        leads=[{"status": "OPTED_OUT", "ai_followup_allowed": False}],
        inbound=[inbound_row(age_hours=1)],
    )
    monkeypatch.setattr(wa, "get_backend", lambda: backend)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(wa._assert_compliant_session_outbound("+15551234567"))
    assert exc.value.status_code == 403


def test_blocks_latest_stop_message(monkeypatch):
    backend = ComplianceBackend(inbound=[inbound_row(age_hours=1, text="STOP")])
    monkeypatch.setattr(wa, "get_backend", lambda: backend)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(wa._assert_compliant_session_outbound("+15551234567"))
    assert exc.value.status_code == 403


def test_blocks_recipient_rate_limit(monkeypatch):
    now = datetime.now(timezone.utc)
    rows = [
        {"delivery_status": "sent", "created_at": (now - timedelta(minutes=i + 1)).isoformat()}
        for i in range(6)
    ]
    backend = ComplianceBackend(inbound=[inbound_row(age_hours=1)], recipient_outbound=rows)
    monkeypatch.setattr(wa, "get_backend", lambda: backend)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(wa._assert_compliant_session_outbound("+15551234567"))
    assert exc.value.status_code == 429


class OwnerSessionBackend:
    def __init__(self):
        self.inserted = []

    async def insert(self, table, row):
        self.inserted.append((table, dict(row)))

    async def select(self, table, *, params=None):
        return []


def _hermes_request(payload):
    import json

    from starlette.requests import Request

    body = json.dumps(payload).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": []}, receive)


def _run_owner_event(monkeypatch, backend, direction):
    async def fake_owner(phone):
        return True

    monkeypatch.setattr(wa, "get_backend", lambda: backend)
    monkeypatch.setattr(wa, "_is_owner_whatsapp", fake_owner)
    monkeypatch.setattr(wa, "_verify_hermes_signature", lambda raw, ts, sig: None)
    payload = {
        "event_id": "evt_owner_1",
        "direction": direction,
        "message_id": "wamid_owner_1",
        "sender_id": "+12816628581",
        "recipient_id": "+12816628581",
        "content": "hola, prueba",
        "message_type": "text",
        "contact_name": "Juan",
    }
    return asyncio.run(wa.hermes_event(_hermes_request(payload), None, None))


def test_owner_private_inbound_records_verified_session(monkeypatch):
    backend = OwnerSessionBackend()
    result = _run_owner_event(monkeypatch, backend, "inbound")
    assert result["status"] == "accepted_owner_private"
    session_rows = [row for table, row in backend.inserted if table == "whatsapp_messages"]
    assert len(session_rows) == 1
    assert session_rows[0]["direction"] == "inbound"
    assert session_rows[0]["phone"] == "12816628581"
    private_rows = [row for table, row in backend.inserted if table == "business_events"]
    assert len(private_rows) == 1
    assert private_rows[0]["event_type"] == "owner_private_message"


def test_owner_private_outbound_does_not_create_session(monkeypatch):
    backend = OwnerSessionBackend()
    result = _run_owner_event(monkeypatch, backend, "outbound")
    assert result["status"] == "accepted_owner_private"
    session_rows = [row for table, row in backend.inserted if table == "whatsapp_messages"]
    assert session_rows == []
