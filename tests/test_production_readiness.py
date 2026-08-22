import os

from production_readiness import evaluate_production_readiness


REQUIRED_ENV = {
    "INSFORGE_BASE_URL": "https://example.insforge.app",
    "INSFORGE_API_KEY": "ik_test",
    "INSFORGE_ANON_KEY": "anon_test",
    "AUTH_PROVIDER": "insforge",
    "OWNER_MFA_REQUIRED": "true",
    "OFAC_DIRECT_SCREENING": "true",
    "TARIFF_DATA_PROVIDER": "authoritative-test-provider",
    "LOGISTICS_DATA_PROVIDER": "live-test-provider",
    "FX_DATA_PROVIDER": "live-test-provider",
    "INSFORGE_STORAGE_ENABLED": "true",
    "AUDIT_RETENTION_DAYS": "365",
    "BACKUPS_ENABLED": "true",
    "VERCEL_MONITORING_ENABLED": "true",
    "E2E_TRADE_WORKFLOW_VERIFIED": "true",
}


def test_readiness_fails_closed_without_external_dependencies(monkeypatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    result = evaluate_production_readiness(runtime_ok=True)
    assert result["production_ready"] is False
    assert result["release_gate"] == "HOLD"
    assert "insforge_backend" in result["blockers"]
    assert "e2e_trade_workflow" in result["blockers"]


def test_readiness_reaches_100_only_when_every_critical_gate_is_explicit(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    result = evaluate_production_readiness(runtime_ok=True)
    assert result["score"] == 100
    assert result["production_ready"] is True
    assert result["release_gate"] == "READY"
    assert result["blockers"] == []


def test_runtime_failure_blocks_release_even_with_all_dependencies(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    result = evaluate_production_readiness(runtime_ok=False)
    assert result["production_ready"] is False
    assert "production_runtime" in result["blockers"]
