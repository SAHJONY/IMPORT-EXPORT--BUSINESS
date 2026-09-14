from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_hermes_outbox_avoids_unindexed_json_database_sort():
    source = (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")
    start = source.index('@app.get("/whatsapp/hermes/outbox")')
    end = source.index('@app.post("/whatsapp/hermes/outbox/ack")')
    outbox_route = source[start:end]
    assert '"status": "in.(queued,dispatching)"' in outbox_route
    assert "rows.sort(" in outbox_route
    assert '"order": "created_at.asc"' not in outbox_route


def test_owner_queue_orders_in_memory():
    source = (ROOT / "communication_os_api.py").read_text(encoding="utf-8")
    start = source.index('@app.get("/communications-os/command-center")')
    route = source[start:]
    queue_query = next(line for line in route.splitlines() if "whatsapp_queue = await" in line)
    assert 'params={"limit": "250"}' in queue_query
    assert '"order"' not in queue_query
    assert "sorted(whatsapp_queue or []" in route
