from datetime import date, timedelta

from fastapi.testclient import TestClient

import global_supplier_sourcing_api as sourcing


class FakeBackend:
    def __init__(self, candidate):
        self.candidate = candidate
        self.inserted = []
        self.patched = []

    async def select(self, table, *, params=None):
        if table == "global_sourcing_requests":
            return [{"sourcing_request_id": "gsr_test", "product_need": "Industrial pump", "destination_country": "CU"}]
        if table == "global_supplier_candidates":
            return [self.candidate]
        return []

    async def patch(self, table, values, *, params):
        self.patched.append((table, values, params))
        self.candidate = {**self.candidate, **values}
        return [self.candidate]

    async def insert(self, table, row):
        self.inserted.append((table, row))
        return [row]


def quote(valid_until, *, verified=True):
    return {
        "unit_cost": 125.0,
        "currency": "USD",
        "moq": 20,
        "lead_time_days": 30,
        "incoterm": "FOB",
        "payment_terms": "30% deposit, 70% before shipment",
        "quote_reference": "SUP-Q-100",
        "quote_date": date.today().isoformat(),
        "valid_until": valid_until.isoformat(),
        "verified": verified,
    }


def test_quote_status_requires_current_verified_quote_and_ready_corridor():
    row = {
        "corridor_status": "READY",
        "source_evidence": {"supplier_quote": quote(date.today() + timedelta(days=30))},
    }
    status = sourcing.quote_status(row)
    assert status["complete"] is True
    assert status["selection_eligible"] is True
    assert status["comparison_basis"] == "UNIT_FOB"


def test_expired_quote_fails_closed():
    row = {
        "corridor_status": "READY",
        "source_evidence": {"supplier_quote": quote(date.today() - timedelta(days=1))},
    }
    status = sourcing.quote_status(row)
    assert status["selection_eligible"] is False
    assert "QUOTE_EXPIRED_OR_INVALID" in status["blockers"]


def test_employee_cannot_verify_supplier_quote(monkeypatch):
    monkeypatch.setattr(sourcing, "identity", lambda *_: {"role": "employee", "id": "staff"})
    client = TestClient(sourcing.app)
    response = client.put(
        "/global-sourcing/candidates/gsc_test/quote",
        headers={"X-Role": "employee", "Authorization": "Bearer test"},
        json={
            **quote(date.today() + timedelta(days=30)),
            "verified": True,
        },
    )
    assert response.status_code == 403
    assert "Only owner" in response.json()["detail"]


def test_selection_rejects_unverified_quote(monkeypatch):
    candidate = {
        "global_candidate_id": "gsc_test",
        "sourcing_request_id": "gsr_test",
        "supplier_country": "DE",
        "corridor_status": "READY",
        "source_evidence": {"supplier_quote": quote(date.today() + timedelta(days=30), verified=False)},
    }
    backend = FakeBackend(candidate)
    monkeypatch.setattr(sourcing, "get_backend", lambda: backend)
    monkeypatch.setattr(sourcing, "identity", lambda *_: {"role": "owner", "id": "owner"})
    client = TestClient(sourcing.app)
    response = client.post(
        "/global-sourcing/candidates/gsc_test/select",
        headers={"X-Role": "owner", "Authorization": "Bearer test"},
    )
    assert response.status_code == 409
    assert backend.patched == []


def test_owner_quote_save_records_audit_without_binding_acceptance(monkeypatch):
    candidate = {
        "global_candidate_id": "gsc_test",
        "sourcing_request_id": "gsr_test",
        "supplier_name": "Pump Works",
        "supplier_country": "DE",
        "corridor_status": "READY",
        "source_evidence": {},
    }
    backend = FakeBackend(candidate)
    monkeypatch.setattr(sourcing, "get_backend", lambda: backend)
    monkeypatch.setattr(sourcing, "identity", lambda *_: {"role": "owner", "id": "owner"})
    client = TestClient(sourcing.app)
    response = client.put(
        "/global-sourcing/candidates/gsc_test/quote",
        headers={"X-Role": "owner", "Authorization": "Bearer test"},
        json={**quote(date.today() + timedelta(days=30)), "verified": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["quote_status"]["selection_eligible"] is True
    assert body["binding_acceptance"] is False
    assert any(table == "global_sourcing_control_evidence" for table, _ in backend.inserted)
