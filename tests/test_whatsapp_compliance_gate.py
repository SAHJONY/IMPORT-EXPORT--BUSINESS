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
