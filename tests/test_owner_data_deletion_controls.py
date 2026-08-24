from fastapi.testclient import TestClient

import data_control_api
import gmail_delete_api


def test_safe_table_rejects_injection():
    assert data_control_api.safe_table("customer_accounts") == "customer_accounts"
    try:
        data_control_api.safe_table("customer_accounts; drop table x")
        assert False, "unsafe table must fail"
    except Exception:
        pass


def test_record_delete_requires_exact_confirmation(monkeypatch):
    monkeypatch.setattr(data_control_api, "owner", lambda _authorization: None)
    client = TestClient(data_control_api.app)
    response = client.request(
        "DELETE",
        "/data-control/records/customer_accounts",
        json={"confirmation": "yes", "field": "customer_id", "value": "cus_1"},
    )
    assert response.status_code == 409
    assert "DELETE" in response.json()["detail"]


def test_bulk_delete_requires_table_specific_phrase(monkeypatch):
    monkeypatch.setattr(data_control_api, "owner", lambda _authorization: None)
    client = TestClient(data_control_api.app)
    response = client.request(
        "DELETE",
        "/data-control/records/customer_accounts",
        json={"confirmation": "DELETE ALL", "delete_all": True},
    )
    assert response.status_code == 409
    assert "DELETE ALL customer_accounts" in response.json()["detail"]


def test_gmail_delete_requires_exact_confirmation(monkeypatch):
    monkeypatch.setattr(gmail_delete_api, "owner", lambda _authorization: None)
    client = TestClient(gmail_delete_api.app)
    response = client.post(
        "/native-email/messages/abc123/trash",
        json={"confirmation": "DELETE"},
    )
    assert response.status_code == 409
    assert "TRASH" in response.json()["detail"]


def test_gmail_permanent_delete_requires_stronger_phrase(monkeypatch):
    monkeypatch.setattr(gmail_delete_api, "owner", lambda _authorization: None)
    client = TestClient(gmail_delete_api.app)
    response = client.request(
        "DELETE",
        "/native-email/messages/abc123",
        json={"confirmation": "DELETE"},
    )
    assert response.status_code == 409
    assert "DELETE PERMANENTLY" in response.json()["detail"]
