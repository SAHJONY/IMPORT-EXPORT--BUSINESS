from fastapi.testclient import TestClient

import finance_api as finance


OWNER = {"X-Role": "owner", "Authorization": "Bearer test"}
EMP_A = {"X-Role": "employee", "Authorization": "Bearer test", "X-Employee-Id": "employee-a"}
EMP_B = {"X-Role": "employee", "Authorization": "Bearer test", "X-Employee-Id": "employee-b"}


class MemoryFinanceStore:
    def __init__(self):
        self.tables = {
            "ledger_accounts": [
                {"account_id": "cash", "code": "1000", "active": True},
                {"account_id": "revenue", "code": "4000", "active": True},
            ]
        }

    def _match(self, row, filters):
        return all(str(row.get(k)) == str(v) for k, v in (filters or {}).items())

    async def select(self, table, *, filters=None, order_by=None, descending=False, limit=300):
        rows = [dict(r) for r in self.tables.get(table, []) if self._match(r, filters)]
        return rows[:limit]

    async def insert(self, table, row):
        stored = dict(row)
        self.tables.setdefault(table, []).append(stored)
        return dict(stored)

    async def update(self, table, values, *, filters):
        out = []
        for row in self.tables.get(table, []):
            if self._match(row, filters):
                row.update(values)
                out.append(dict(row))
        return out


def wire(monkeypatch, store):
    monkeypatch.setattr(finance, "select_rows", store.select)
    monkeypatch.setattr(finance, "insert_row", store.insert)
    monkeypatch.setattr(finance, "update_rows", store.update)

    def fake_identity(role, _authorization, employee_id):
        if role == "owner":
            return {"role": "owner", "id": "owner"}
        return {"role": "employee", "id": employee_id or "staff"}

    monkeypatch.setattr(finance, "identity", fake_identity)


def test_double_entry_post_reconcile_and_reverse_controls(monkeypatch):
    store = MemoryFinanceStore()
    wire(monkeypatch, store)
    client = TestClient(finance.app)

    unbalanced = client.post("/finance/journals", headers=EMP_A, json={
        "description": "Unbalanced certification attempt",
        "entries": [
            {"account_id": "cash", "debit": 100, "credit": 0},
            {"account_id": "revenue", "debit": 0, "credit": 99},
        ],
    })
    assert unbalanced.status_code == 400

    created = client.post("/finance/journals", headers=EMP_A, json={
        "trade_case_id": "cert-case",
        "description": "Finance control certification",
        "entries": [
            {"account_id": "cash", "debit": 100, "credit": 0},
            {"account_id": "revenue", "debit": 0, "credit": 100},
        ],
    })
    assert created.status_code == 200
    journal_id = created.json()["journal"]["journal_id"]

    assert client.post(f"/finance/journals/{journal_id}/post", headers=EMP_A).status_code == 403
    posted = client.post(f"/finance/journals/{journal_id}/post", headers=OWNER)
    assert posted.status_code == 200
    assert posted.json()["status"] == "posted"

    matched = client.post("/finance/reconciliations", headers=EMP_B, json={
        "trade_case_id": "cert-case",
        "payment_id": "cert-payment",
        "expected_amount": 100,
        "received_amount": 100,
        "status": "matched",
        "matched_journal_id": journal_id,
    })
    assert matched.status_code == 200
    assert matched.json()["reconciliation"]["status"] == "matched"

    assert client.post(f"/finance/journals/{journal_id}/reverse", headers=EMP_B).status_code == 403
    reversed_result = client.post(f"/finance/journals/{journal_id}/reverse", headers=OWNER)
    assert reversed_result.status_code == 200
    reversal = reversed_result.json()["reversal_journal"]
    assert reversal["reference_type"] == "REVERSAL"
    assert reversal["reference_id"] == journal_id


def test_beneficiary_maker_checker_requires_three_way_separation(monkeypatch):
    store = MemoryFinanceStore()
    wire(monkeypatch, store)
    client = TestClient(finance.app)

    requested = client.post("/finance/beneficiary-changes", headers=EMP_A, json={
        "counterparty_type": "supplier",
        "counterparty_id": "supplier-cert",
        "new_bank_fingerprint": "fingerprint-new-001",
    })
    assert requested.status_code == 200
    request_id = requested.json()["request"]["request_id"]

    self_verify = client.post(
        f"/finance/beneficiary-changes/{request_id}/verify",
        headers=EMP_A,
        json={"verification_method": "independent callback"},
    )
    assert self_verify.status_code == 409

    verified = client.post(
        f"/finance/beneficiary-changes/{request_id}/verify",
        headers=EMP_B,
        json={"verification_method": "independent callback"},
    )
    assert verified.status_code == 200
    assert verified.json()["verified_by"] == "employee-b"

    assert client.post(f"/finance/beneficiary-changes/{request_id}/approve", headers=EMP_B).status_code == 403
    approved = client.post(f"/finance/beneficiary-changes/{request_id}/approve", headers=OWNER)
    assert approved.status_code == 200
    assert approved.json()["approved_by"] == "owner"


def test_owner_cannot_approve_change_the_owner_verified(monkeypatch):
    store = MemoryFinanceStore()
    wire(monkeypatch, store)
    client = TestClient(finance.app)

    requested = client.post("/finance/beneficiary-changes", headers=EMP_A, json={
        "counterparty_type": "supplier",
        "counterparty_id": "supplier-cert-2",
        "new_bank_fingerprint": "fingerprint-new-002",
    })
    request_id = requested.json()["request"]["request_id"]

    assert client.post(
        f"/finance/beneficiary-changes/{request_id}/verify",
        headers=OWNER,
        json={"verification_method": "owner callback verification"},
    ).status_code == 200
    assert client.post(f"/finance/beneficiary-changes/{request_id}/approve", headers=OWNER).status_code == 409
