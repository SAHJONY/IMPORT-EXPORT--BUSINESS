import asyncio

import whatsapp_cloud_primary_api as api


def test_whatsapp_health_survives_missing_backlog_backend(monkeypatch):
    async def empty_dict(*_args, **_kwargs):
        return {}

    async def backlog_unavailable(*_args, **_kwargs):
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(api, "_config", empty_dict)
    monkeypatch.setattr(api, "_named_openclaw_gateway_state", empty_dict)
    monkeypatch.setattr(api, "_openclaw_gateway_state", empty_dict)
    monkeypatch.setattr(api, "diagnose", empty_dict)
    monkeypatch.setattr(api, "intelligence_health", empty_dict)
    monkeypatch.setattr(api, "growth_health", empty_dict)
    monkeypatch.setattr(api, "self_selling_health", empty_dict)
    monkeypatch.setattr(api, "crm_bridge_status", empty_dict)
    monkeypatch.setattr(api, "find_unanswered", backlog_unavailable)
    monkeypatch.setattr(api, "hermes_whatsapp_health", lambda: {})

    result = asyncio.run(api.whatsapp_health_hostinger_authority())
    assert result["status"] == "configuration_required"
    assert result["send_ready"] is False
    assert result["backlog_recovery"]["available"] is False
    assert result["backlog_recovery"]["pending_conversations"] == 0
