from fastapi.testclient import TestClient
import shipment_api as shipment


class FakeBackend:
    def __init__(self):
        self.shipment = {
            "shipment_id": "shp_test",
            "trade_case_id": "mtc_test",
            "transport_mode": "ocean",
            "provider": "manual-test",
            "tracking_reference": "TESTTRACK123",
            "current_stage": "in_transit",
            "current_status": "in_transit",
            "customer_visible": True,
        }

    async def select(self, table, *, params=None):
        if table == "shipments":
            return [dict(self.shipment)]
        return []

    async def patch(self, table, values, *, params):
        if table == "shipments":
            self.shipment.update(values)
            return [dict(self.shipment)]
        return []


async def noop(*args, **kwargs):
    return None


def test_actual_delivery_is_persisted_and_sets_delivered_state(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(shipment, "get_backend", lambda: backend)
    monkeypatch.setattr(shipment, "identity", lambda *_args, **_kwargs: {"role": "owner", "id": "owner"})
    monkeypatch.setattr(shipment, "publish_event", noop)
    client = TestClient(shipment.app)
    response = client.patch(
        "/shipments/shp_test",
        headers={"X-Role": "owner", "Authorization": "Bearer test"},
        json={"actual_delivery_at": "2026-09-05T12:00:00Z"},
    )
    assert response.status_code == 200
    row = response.json()["shipment"]
    assert row["actual_delivery_at"] == "2026-09-05T12:00:00Z"
    assert row["current_stage"] == "delivered"
    assert row["current_status"] == "delivered"
