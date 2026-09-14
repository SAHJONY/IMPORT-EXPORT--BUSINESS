import asyncio
import time

import activation_api
import production_schema_evidence as pse


def test_schema_evidence_timeout_is_fail_closed(monkeypatch):
    def slow_probe():
        time.sleep(0.05)
        return {"verified": True, "rls_verified": True}
    monkeypatch.setattr(pse, "_probe", slow_probe)
    result = asyncio.run(pse.production_schema_evidence(timeout_seconds=0.001))
    assert result["verified"] is False
    assert result["rls_verified"] is False
    assert "Timeout" in result["reason"]


def test_connector_timeout_is_degraded(monkeypatch):
    async def slow_health():
        await asyncio.sleep(0.05)
        return {"all_configured_reachable": True}
    monkeypatch.setattr(activation_api.trade_connectors, "health", slow_health)
    result = asyncio.run(activation_api._bounded_connector_health(timeout_seconds=0.001))
    assert result["status"] == "degraded"
    assert result["all_configured_reachable"] is False
    assert result["by_name"] == {}
