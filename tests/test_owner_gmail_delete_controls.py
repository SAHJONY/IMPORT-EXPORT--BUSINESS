from fastapi.testclient import TestClient

import gmail_delete_api


def test_trash_requires_exact_confirmation(monkeypatch):
    monkeypatch.setattr(gmail_delete_api, "owner", lambda _authorization: None)
    client = TestClient(gmail_delete_api.app)
    response = client.post("/native-email/messages/abc123/trash", json={"confirmation": "DELETE"})
    assert response.status_code == 409
    assert "TRASH" in response.json()["detail"]


def test_permanent_delete_requires_strong_confirmation(monkeypatch):
    monkeypatch.setattr(gmail_delete_api, "owner", lambda _authorization: None)
    client = TestClient(gmail_delete_api.app)
    response = client.request("DELETE", "/native-email/messages/abc123", json={"confirmation": "DELETE"})
    assert response.status_code == 409
    assert "DELETE PERMANENTLY" in response.json()["detail"]


def test_message_id_validation_rejects_injection():
    assert gmail_delete_api.safe_message_id("abc_123-Z") == "abc_123-Z"
    try:
        gmail_delete_api.safe_message_id("abc/../../etc")
        assert False, "unsafe Gmail id must fail"
    except Exception:
        pass
