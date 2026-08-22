import pytest

from production_readiness import evaluate_production_readiness
from trade_connectors import TradeConnectorRegistry


@pytest.mark.asyncio
async def test_ofac_screen_uses_current_dataset_shape_without_network(monkeypatch):
    registry = TradeConnectorRegistry()
    sample = "name,program,country\nExample Trading LLC,TEST,US\nOther Entity,TEST,CA\n"

    async def fake_cached_text(key, url, ttl_seconds):
        return sample, "2026-08-22T15:00:00+00:00"

    monkeypatch.setattr(registry, "_cached_text", fake_cached_text)
    result = await registry.ofac_screen("Example Trading")
    assert result["candidate_match"] is True
    assert result["match_count"] >= 1
    assert result["release_effect"] == "REVIEW"


@pytest.mark.asyncio
async def test_ecb_reference_cross_rate_without_network(monkeypatch):
    registry = TradeConnectorRegistry()
    sample = """<?xml version='1.0' encoding='UTF-8'?>
    <Envelope><Cube><Cube time='2026-08-21'><Cube currency='USD' rate='1.20'/><Cube currency='MXN' rate='24.00'/></Cube></Cube></Envelope>"""

    async def fake_cached_text(key, url, ttl_seconds):
        return sample, "2026-08-22T15:00:00+00:00"

    monkeypatch.setattr(registry, "_cached_text", fake_cached_text)
    result = await registry.fx_reference("USD", "MXN")
    assert result["rate"] == 20.0
    assert result["usage"] == "planning_reference_only"


def test_readiness_accepts_only_live_screening_health(monkeypatch):
    for key in [
        "INSFORGE_BASE_URL", "INSFORGE_API_KEY", "INSFORGE_ANON_KEY",
        "TARIFF_DATA_PROVIDER", "LOGISTICS_DATA_PROVIDER", "FX_EXECUTION_PROVIDER",
    ]:
        monkeypatch.setenv(key, "configured")
    monkeypatch.setenv("AUTH_PROVIDER", "insforge")
    monkeypatch.setenv("OWNER_MFA_REQUIRED", "true")
    monkeypatch.setenv("INSFORGE_STORAGE_ENABLED", "true")
    monkeypatch.setenv("AUDIT_RETENTION_DAYS", "365")
    monkeypatch.setenv("BACKUPS_ENABLED", "true")
    monkeypatch.setenv("VERCEL_MONITORING_ENABLED", "true")
    monkeypatch.setenv("E2E_TRADE_WORKFLOW_VERIFIED", "true")

    health = {
        "by_name": {
            "ofac_sanctions_data": {"configured": True, "reachable": True},
            "tariff_classification": {"configured": True, "reachable": True},
            "logistics_tracking": {"configured": True, "reachable": True},
            "fx_execution": {"configured": True, "reachable": True},
        }
    }
    result = evaluate_production_readiness(runtime_ok=True, connector_health=health)
    assert result["score"] == 100
    assert result["production_ready"] is True

    health["by_name"]["ofac_sanctions_data"]["reachable"] = False
    blocked = evaluate_production_readiness(runtime_ok=True, connector_health=health)
    assert blocked["production_ready"] is False
    assert "restricted_party_screening" in blocked["blockers"]
