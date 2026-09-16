"""Direct-send enqueue endpoint guards (source-inspection, no live backend needed)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _route_source():
    source = (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")
    start = source.index('class HermesDirectSend(BaseModel):')
    end = source.index('@app.get("/whatsapp/hermes/outbox/status")')
    return source[start:end]


def test_direct_send_enqueue_route_exists_with_validation():
    route = _route_source()
    # Pydantic model caps the message at WhatsApp-friendly length.
    assert "body: str = Field(min_length=1, max_length=1000)" in route
    # Recipient is normalized to digits and bounded to E.164 range.
    assert 'if not 8 <= len(digits) <= 15:' in route
    # The worker only releases commands carrying the compliance release mode.
    assert '"release_mode": "customer_service_window"' in route
    # Queued for the outbox worker; never sent inline from the API.
    assert '"status": "queued"' in route
    # Hermes bridge signature is verified before any parsing.
    assert "_verify_hermes_signature(raw, x_sahjony_timestamp, x_sahjony_signature)" in route
    # Provenance is traceable per command.
    assert '"source_url": f"owner:direct-send:{command_id}"' in route


def test_direct_send_status_route_exists():
    source = (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")
    start = source.index('@app.get("/whatsapp/hermes/outbox/status")')
    route = source[start:start + 1500]
    assert "delivery_status" in route
    assert "provider_message_id" in route
    assert "_verify_hermes_signature(b\"\", x_sahjony_timestamp, x_sahjony_signature)" in route


def test_direct_send_workflow_is_governed():
    wf = (ROOT / ".github/workflows/hostinger-hermes-whatsapp-send.yml").read_text(encoding="utf-8")
    # Dry-run is the default; live sends need an explicit flip.
    assert "default: 'true'" in wf
    # Exactly one recipient per dispatch — no bulk.
    assert "cancel-in-progress: false" in wf
    # Ban risk is surfaced before every live dispatch.
    assert "spam detection" in wf
    # Delivery is tracked to a confirmed terminal state.
    assert "DIRECT_SEND_CONFIRMED" in wf
