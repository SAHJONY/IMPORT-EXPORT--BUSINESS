from fastapi.testclient import TestClient

import business_os_api


def test_owner_control_requires_auth() -> None:
    client = TestClient(business_os_api.app)
    assert client.get("/business-os/owner/control").status_code == 401


def test_juan_has_full_owner_control(monkeypatch) -> None:
    monkeypatch.setattr(business_os_api, "verify_owner_token", lambda token: token == "valid")
    client = TestClient(business_os_api.app)
    response = client.get("/business-os/owner/control", headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200
    body = response.json()
    assert body["owner_name"] == "Juan Gonzalez"
    assert body["access_tier"] == "superadmin"
    assert body["scope"] == "owner:full"
    assert body["commercial_access_fee"] == 0
    assert body["reporting"]["time"] == "06:00"
    assert body["reporting"]["timezone"] == "America/Chicago"
    assert body["secrets_exposed"] is False
