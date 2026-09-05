from fastapi.testclient import TestClient

import customer_crm_api as crm
import pricing_api as pricing
import global_supplier_sourcing_api as sourcing
import compliance_api as compliance
import payment_api as payments
import finance_api as finance
import shipment_api as shipments
import managed_trade_gateway_api as managed


OWNER = {"X-Role": "owner", "Authorization": "Bearer test"}


class MemoryStore:
    def __init__(self):
        self.tables = {}

    @staticmethod
    def _value(raw):
        if isinstance(raw, str) and raw.startswith("eq."):
            raw = raw[3:]
        if raw == "true":
            return True
        if raw == "false":
            return False
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

    async def pselect(self, table, filters=None, order_by=None, descending=False, limit=500):
        return [dict(r) for r in self.tables.get(table, []) if self._match(r, filters)][:limit]

    async def pinsert(self, table, payload):
        result = await self.insert(table, payload)
        return result[0] if isinstance(payload, dict) else result

    async def pupdate(self, table, values, filters=None):
        return await self.patch(table, values, params=filters or {})
async def noop(*_args, **_kwargs):
    return None


def wire_store(monkeypatch, store):
    for module in (crm, sourcing, compliance, shipments, managed):
        monkeypatch.setattr(module, "get_backend", lambda s=store: s)
    for module in (crm, sourcing, compliance, shipments, managed):
        if hasattr(module, "identity"):
            monkeypatch.setattr(module, "identity", lambda *_a, **_k: {"role": "owner", "id": "owner"})
    monkeypatch.setattr(pricing, "verify_owner_token", lambda _token: True)
    monkeypatch.setattr(payments, "verify_owner_token", lambda _token: True)
    monkeypatch.setattr(payments, "select_rows", store.pselect)
    monkeypatch.setattr(payments, "insert_row", store.pinsert)
    monkeypatch.setattr(payments, "update_rows", store.pupdate)
    monkeypatch.setattr(shipments, "publish_event", noop)
    monkeypatch.setattr(finance, "verify_owner_token", lambda _token: True)
    monkeypatch.setattr(finance, "select_rows", store.pselect)
    monkeypatch.setattr(finance, "insert_row", store.pinsert)
    monkeypatch.setattr(finance, "update_rows", store.pupdate)

    async def execution_evidence(case):
        return {"verified": True, "trade_references": [case["managed_case_id"], case["request_id"]], "checks": {}, "blockers": []}

    monkeypatch.setattr(managed, "execution_evidence", execution_evidence)
def test_business_flow_a2z_closes_without_external_side_effects(monkeypatch):
    store = MemoryStore()
    wire_store(monkeypatch, store)
    store.tables["ledger_accounts"] = [
        {"account_id": "cash", "code": "1000", "active": True},
        {"account_id": "revenue", "code": "4000", "active": True},
    ]

    crm_client = TestClient(crm.app)
    intake = crm_client.post("/crm/intake", json={
        "legal_name": "A2Z Test Buyer LLC", "contact_name": "Test Buyer",
        "email": "a2z-test@example.invalid", "country_code": "US",
        "product_need": "Industrial test product", "quantity": 100,
        "target_budget": 25000, "currency": "USD", "destination_country": "CU",
        "preferred_incoterm": "CIF",
    })
    assert intake.status_code == 200
    intake_id = intake.json()["intake"]["intake_id"]
    customer_id = intake.json()["customer"]["customer_id"]
    assert crm_client.patch(f"/crm/intakes/{intake_id}/qualify", headers=OWNER, json={"status": "QUALIFIED"}).status_code == 200
    promoted = crm_client.post(f"/crm/intakes/{intake_id}/promote", headers=OWNER)
    assert promoted.status_code == 200
    request_id = promoted.json()["managed_trade_request_id"]
    sourcing_id = promoted.json()["sourcing_request_id"]
    sourcing_client = TestClient(sourcing.app)
    candidate = sourcing_client.post(f"/global-sourcing/requests/{sourcing_id}/candidates", headers=OWNER, json={
        "supplier_name": "A2Z Supplier GmbH", "supplier_country": "DE",
        "product_match": "Industrial test product", "unit_cost": 100,
        "currency": "USD", "moq": 10, "lead_time_days": 20,
        "incoterm": "FOB", "payment_terms": "30/70",
    })
    assert candidate.status_code == 200
    global_candidate_id = candidate.json()["candidate"]["global_candidate_id"]
    quote = sourcing_client.put(f"/global-sourcing/candidates/{global_candidate_id}/quote", headers=OWNER, json={
        "unit_cost": 100, "currency": "USD", "moq": 10, "lead_time_days": 20,
        "incoterm": "FOB", "payment_terms": "30/70", "quote_reference": "A2Z-Q-1",
        "quote_date": "2026-09-05", "valid_until": "2026-10-05", "verified": True,
    })
    assert quote.status_code == 200

    pricing_client = TestClient(pricing.app)
    priced = pricing_client.post("/owner-pricing/preview/business", headers=OWNER, json={
        "supplier_cost": 10000, "international_freight": 2000,
        "compliance_cost": 500, "payment_cost": 250, "handling_cost": 250,
        "requested_margin_pct": 15,
    })
    assert priced.status_code == 200
    customer_price = priced.json()["customer_price"]
    assert customer_price > 13000
    managed_client = TestClient(managed.app)
    m_supplier = managed_client.post(f"/managed-trade/requests/{request_id}/suppliers", headers=OWNER, json={
        "supplier_name": "A2Z Supplier GmbH", "supplier_country": "DE",
        "product_match": "Industrial test product", "unit_cost": 100,
        "incoterm": "FOB", "payment_terms": "30/70",
    })
    assert m_supplier.status_code == 200
    candidate_id = m_supplier.json()["supplier_candidate"]["candidate_id"]
    assert managed_client.post(f"/managed-trade/requests/{request_id}/suppliers/{candidate_id}/select", headers=OWNER).status_code == 409
    awaitable = store.patch("managed_supplier_candidates", {
        "compliance_status": "PASS", "quality_status": "PASS", "bank_status": "PASS"
    }, params={"candidate_id": f"eq.{candidate_id}"})
    import asyncio
    asyncio.run(awaitable)
    assert managed_client.post(f"/managed-trade/requests/{request_id}/suppliers/{candidate_id}/select", headers=OWNER).status_code == 200
    opened = managed_client.post("/managed-trade/cases", headers=OWNER, json={
        "request_id": request_id, "supplier_candidate_id": candidate_id,
        "sahjony_role": "MANAGED_TRADE_ORCHESTRATOR", "customs_broker": "A2Z Broker",
        "freight_forwarder": "A2Z Forwarder", "settlement_provider": "A2Z Bank",
    })
    assert opened.status_code == 200
    case_id = opened.json()["case"]["managed_case_id"]
    compliance_client = TestClient(compliance.app)
    comp = compliance_client.post("/compliance", headers=OWNER, json={
        "trade_case_id": case_id, "customer_id": customer_id, "direction": "cross_trade",
        "origin_country": "DE", "destination_country": "CU", "incoterm": "CIF",
    })
    assert comp.status_code == 200
    compliance_id = comp.json()["compliance"]["compliance_id"]
    assert compliance_client.post(f"/compliance/{compliance_id}/owner-release", headers=OWNER).status_code == 409
    reqs = compliance_client.get(f"/compliance/{compliance_id}/requirements", headers=OWNER).json()["requirements"]
    for req in reqs:
        r = compliance_client.patch(
            f"/compliance/{compliance_id}/requirements/{req['requirement_id']}", headers=OWNER,
            json={"status": "satisfied", "evidence_document_id": "A2Z-EVIDENCE", "notes": "Sandbox evidence"},
        )
        assert r.status_code == 200
    assert compliance_client.post(f"/compliance/{compliance_id}/evaluate-release", headers=OWNER).json()["release_status"] == "ready"
    assert compliance_client.post(f"/compliance/{compliance_id}/owner-release", headers=OWNER).status_code == 200

    payment_client = TestClient(payments.app)
    pay = payment_client.post("/owner-payments/cases", headers=OWNER, json={
        "audience": "BUSINESS_CUSTOMER", "customer_reference": customer_id,
        "source_reference": case_id, "total_amount": customer_price, "currency": "USD",
        "quote_approved": True, "compliance_cleared": True, "payment_rail": "BANK_WIRE",
    })
    assert pay.status_code == 200
    payment_id = pay.json()["payment_case_id"]
    release_body = {"owner_note": "A2Z sandbox release", "compliance_still_cleared": True, "customer_funds_confirmed": True}
    assert payment_client.post(f"/owner-payments/cases/{payment_id}/authorize-shipment-release", headers=OWNER, json=release_body).status_code == 409
    funds = payment_client.post(f"/owner-payments/cases/{payment_id}/confirm-funds", headers=OWNER, json={
        "amount": customer_price, "currency": "USD", "external_reference": "A2Z-WIRE-1",
    })
    assert funds.status_code == 200 and funds.json()["status"] == "PAID"
    assert payment_client.post(f"/owner-payments/cases/{payment_id}/authorize-supplier-payout", headers=OWNER, json=release_body).status_code == 200
    assert payment_client.post(f"/owner-payments/cases/{payment_id}/authorize-shipment-release", headers=OWNER, json=release_body).status_code == 200
    assert payment_client.post(f"/owner-payments/cases/{payment_id}/authorize-release", headers=OWNER, json=release_body).status_code == 409

    for key in managed.PRE_RELEASE_KEYS:
        reviewed = managed_client.patch(f"/managed-trade/cases/{case_id}/milestones/{key}", headers=OWNER, json={
            "status": "PASS", "evidence_reference": f"A2Z:{key}", "notes": "Sandbox gate evidence",
        })
        assert reviewed.status_code == 200
    assert managed_client.post(f"/managed-trade/cases/{case_id}/release", headers=OWNER).status_code == 200
    assert managed_client.post(f"/managed-trade/cases/{case_id}/execute", headers=OWNER).status_code == 200

    shipment_client = TestClient(shipments.app)
    shipment = shipment_client.post("/shipments", headers=OWNER, json={
        "trade_case_id": case_id, "customer_id": customer_id, "transport_mode": "ocean",
        "provider": "manual-test", "tracking_reference": "A2ZTRACK123",
        "origin_name": "Hamburg", "destination_name": "Mariel",
    })
    assert shipment.status_code == 200
    shipment_id = shipment.json()["shipment"]["shipment_id"]
    delivered_patch = shipment_client.patch(f"/shipments/{shipment_id}", headers=OWNER, json={"actual_delivery_at": "2026-09-05T12:00:00Z"})
    assert delivered_patch.status_code == 200
    assert managed_client.post(f"/managed-trade/cases/{case_id}/delivered", headers=OWNER).status_code == 200
    finance_client = TestClient(finance.app)
    journal = finance_client.post("/finance/journals", headers=OWNER, json={
        "trade_case_id": case_id, "reference_type": "A2Z_TEST", "reference_id": payment_id,
        "description": "A2Z sandbox settlement", "currency": "USD", "entries": [
            {"account_id": "cash", "debit": customer_price, "credit": 0},
            {"account_id": "revenue", "debit": 0, "credit": customer_price},
        ],
    })
    assert journal.status_code == 200
    journal_id = journal.json()["journal"]["journal_id"]
    assert finance_client.post(f"/finance/journals/{journal_id}/post", headers=OWNER).status_code == 200
    rec = finance_client.post("/finance/reconciliations", headers=OWNER, json={
        "trade_case_id": case_id, "payment_id": payment_id, "bank_reference": "A2Z-WIRE-1",
        "expected_amount": customer_price, "received_amount": customer_price, "currency": "USD",
        "status": "matched", "matched_journal_id": journal_id,
    })
    assert rec.status_code == 200
    assert managed_client.post(f"/managed-trade/cases/{case_id}/reconcile", headers=OWNER).status_code == 200
    closed = managed_client.post(f"/managed-trade/cases/{case_id}/close", headers=OWNER)
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"
    assert closed.json()["release_allowed"] is False
