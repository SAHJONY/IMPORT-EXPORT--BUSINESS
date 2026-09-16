"""Sofia intake auto-assign: POST /crm/intake with utm_medium=sofia assigns
the created intake to employee 'sofia'; all other intakes are unchanged.

Email stays mandatory (IntakeIn.validate_email) — no relaxation built here;
Sofia collects email in-conversation per the approved plan.
"""
from fastapi.testclient import TestClient

import customer_crm_api as crm


class MemoryStore:
    def __init__(self):
        self.tables = {}

    @staticmethod
    def _value(raw):
        if isinstance(raw, str) and raw.startswith("eq."):
            raw = raw[3:]
        return raw

    def _match(self, row, filters):
        for key, raw in (filters or {}).items():
            if key in {"limit", "order"}:
                continue
            if str(row.get(key)) != str(self._value(raw)):
                return False
        return True

    async def select(self, table, *, params=None):
        rows = [dict(r) for r in self.tables.get(table, []) if self._match(r, params)]
        limit = int((params or {}).get("limit", len(rows)) or len(rows))
        return rows[:limit]

    async def insert(self, table, payload):
        rows = payload if isinstance(payload, list) else [payload]
        self.tables.setdefault(table, []).extend(dict(r) for r in rows)
        return [dict(r) for r in rows] if isinstance(payload, list) else [dict(payload)]

    async def patch(self, table, values, *, params):
        out = []
        for row in self.tables.get(table, []):
            if self._match(row, params):
                row.update(values)
                out.append(dict(row))
        return out


def wire(monkeypatch, store):
    monkeypatch.setattr(crm, "get_backend", lambda: store)


def base_payload(**overrides):
    payload = {
        "legal_name": "Sofia Test Buyer LLC",
        "contact_name": "Test Buyer",
        "email": "sofia-test@example.invalid",
        "country_code": "US",
        "product_need": "Industrial test product",
        "destination_country": "CU",
    }
    payload.update(overrides)
    return payload


def post_intake(monkeypatch, payload):
    store = MemoryStore()
    wire(monkeypatch, store)
    client = TestClient(crm.app)
    resp = client.post("/crm/intake", json=payload)
    assert resp.status_code == 200, resp.text
    return store, resp.json()


def test_sofia_utm_medium_assigns_sofia(monkeypatch):
    store, body = post_intake(monkeypatch, base_payload(
        utm_source="whatsapp", utm_medium="sofia", utm_campaign="sofia_concierge", lead_type="RFQ"))
    intake = body["intake"]
    assert intake["assigned_employee_id"] == "sofia"
    persisted = store.tables["customer_trade_intakes"][-1]
    assert persisted["assigned_employee_id"] == "sofia"
    # audited write: the assignment decision is recorded
    audits = [r for r in store.tables["customer_crm_audit"] if r["event_type"] == "intake_created"]
    assert audits, "intake_created audit row missing"
    assert audits[-1]["payload"]["assigned_employee_id"] == "sofia"
    assert audits[-1]["payload"]["first_touch"]["utm_medium"] == "sofia"


def test_sofia_utm_medium_case_insensitive(monkeypatch):
    store, body = post_intake(monkeypatch, base_payload(utm_source="whatsapp", utm_medium="Sofia"))
    assert body["intake"]["assigned_employee_id"] == "sofia"


def test_other_utm_medium_unchanged(monkeypatch):
    store, body = post_intake(monkeypatch, base_payload(
        utm_source="facebook", utm_medium="group", utm_campaign="partner_recruitment_cuba"))
    assert "assigned_employee_id" not in body["intake"]
    assert "assigned_employee_id" not in store.tables["customer_trade_intakes"][-1]
    audits = [r for r in store.tables["customer_crm_audit"] if r["event_type"] == "intake_created"]
    assert audits[-1]["payload"]["assigned_employee_id"] is None


def test_no_utm_unchanged(monkeypatch):
    store, body = post_intake(monkeypatch, base_payload())
    assert "assigned_employee_id" not in body["intake"]
    assert "assigned_employee_id" not in store.tables["customer_trade_intakes"][-1]


def test_email_still_mandatory(monkeypatch):
    """No email relaxation: missing/invalid email is still rejected with 422."""
    store = MemoryStore()
    wire(monkeypatch, store)
    client = TestClient(crm.app)
    payload = base_payload(utm_source="whatsapp", utm_medium="sofia")
    del payload["email"]
    assert client.post("/crm/intake", json=payload).status_code == 422
    payload["email"] = "not-an-email"
    assert client.post("/crm/intake", json=payload).status_code == 422
