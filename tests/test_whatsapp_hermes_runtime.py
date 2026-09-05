import asyncio

import whatsapp_api as wa


def test_inbound_uses_sofia_hermes_runtime(monkeypatch):
    calls = {}

    async def fake_owner(_phone): return False
    async def fake_upsert(*args, **kwargs): return "lead_test"
    async def fake_event(*args, **kwargs): return None
    async def fake_generate(text, contact_name):
        calls["generate"] = (text, contact_name)
        return "Hermes/Sofia reply"
    async def fake_send(cfg, **kwargs):
        calls["send"] = kwargs
        return {"status": "queued"}

    monkeypatch.setattr(wa, "_is_owner_whatsapp", fake_owner)
    monkeypatch.setattr(wa, "_upsert_whatsapp_lead", fake_upsert)
    monkeypatch.setattr(wa, "_record_inbound_event", fake_event)
    monkeypatch.setattr(wa, "_generate_ai_reply", fake_generate)
    monkeypatch.setattr(wa, "_send_text", fake_send)
    monkeypatch.setattr(wa, "_ai_auto_reply_enabled", lambda: True)
    monkeypatch.setattr(wa, "hermes_configured", lambda: True)
    monkeypatch.setattr(wa, "_openai_ready", lambda: False)
    monkeypatch.setattr(wa, "_send_ready", lambda cfg: True)

    asyncio.run(wa._process_inbound({}, phone="+15551234567", message_id="m1", message_type="text", text="Necesito aceite", contact_name="Cliente"))

    assert calls["generate"] == ("Necesito aceite", "Cliente")
    assert calls["send"]["body"] == "Hermes/Sofia reply"
    assert calls["send"]["lead_id"] == "lead_test"
