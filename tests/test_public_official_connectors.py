import asyncio

from production_readiness import evaluate_production_readiness
from trade_connectors import TradeConnectorRegistry


FULL_READY_ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-test",
    "SUPABASE_STORAGE_BUCKET": "trade-documents",
    "AUTH_PROVIDER": "supabase_auth",
    "ALLOW_LEGACY_LOCAL_AUTH": "false",
    "OWNER_MFA_REQUIRED": "true",
    "OWNER_TOTP_SECRET": "JBSWY3DPEHPK3PXP",
    "OPENAI_API_KEY": "openai_test",
    "ANTHROPIC_API_KEY": "anthropic_test",
    "OPENAI_EXECUTIVE_MODEL": "openai-test-model",
    "ANTHROPIC_FRONTIER_MODEL": "anthropic-test-model",
    "ANTHROPIC_AGENT_MODEL": "anthropic-agent-test-model",
    "AI_BRAIN_E2E_VERIFIED": "true",
    "SIGNED_DOCUMENT_STORAGE_VERIFIED": "true",
    "TRANSLATION_PROVIDER": "azure",
    "AZURE_TRANSLATOR_ENDPOINT": "https://api.cognitive.microsofttranslator.com",
    "AZURE_TRANSLATOR_KEY": "translator-test",
    "MULTILINGUAL_E2E_VERIFIED": "true",
    "COUNTRY_ACTIVATION_E2E_VERIFIED": "true",
    "GLOBAL_SUPPLIER_SOURCING_E2E_VERIFIED": "true",
    "MANAGED_TRADE_GATEWAY_E2E_VERIFIED": "true",
    "INTERMEDIARY_MODE_E2E_VERIFIED": "true",
    "BUSINESS_OPERATIONAL_READINESS_E2E_VERIFIED": "true",
    "CUBA_PRIVATE_BUSINESS_E2E_VERIFIED": "true",
    "CUBA_AUTHORIZED_TRADE_E2E_VERIFIED": "true",
    "COLLABORATION_E2E_VERIFIED": "true",
    "ACCOUNTING_LEDGER_VERIFIED": "true",
    "PAYMENT_RECONCILIATION_VERIFIED": "true",
    "BENEFICIARY_MAKER_CHECKER_VERIFIED": "true",
    "CARRIER_E2E_VERIFIED": "true",
    "AUDIT_RETENTION_DAYS": "365",
    "BACKUPS_ENABLED": "true",
    "BACKUP_RESTORE_TESTED": "true",
    "VERCEL_MONITORING_ENABLED": "true",
    "FIRST_LIVE_TRADE_CERTIFIED": "true",
    "E2E_TRADE_WORKFLOW_VERIFIED": "true",
}

SUPABASE_SCHEMA_EVIDENCE = {
    "verified": True,
    "provider": "supabase",
    "present_table_count": 10,
    "rls_verified": True,
    "rls_enabled_table_count": 10,
    "rls_required_table_count": 10,
}


def test_ofac_screen_uses_current_dataset_shape_without_network(monkeypatch):
    registry = TradeConnectorRegistry()
    sample = "name,program,country\nExample Trading LLC,TEST,US\nOther Entity,TEST,CA\n"

    async def fake_cached_text(key, url, ttl_seconds):
        return sample, "2026-08-22T15:00:00+00:00"

    monkeypatch.setattr(registry, "_cached_text", fake_cached_text)
    result = asyncio.run(registry.ofac_screen("Example Trading"))
    assert result["candidate_match"] is True
    assert result["match_count"] >= 1
    assert result["release_effect"] == "REVIEW"


def test_ecb_reference_cross_rate_without_network(monkeypatch):
    registry = TradeConnectorRegistry()
    sample = """<?xml version='1.0' encoding='UTF-8'?>
    <Envelope><Cube><Cube time='2026-08-21'><Cube currency='USD' rate='1.20'/><Cube currency='MXN' rate='24.00'/></Cube></Cube></Envelope>"""

    async def fake_cached_text(key, url, ttl_seconds):
        return sample, "2026-08-22T15:00:00+00:00"

    monkeypatch.setattr(registry, "_cached_text", fake_cached_text)
    result = asyncio.run(registry.fx_reference("USD", "MXN"))
    assert result["rate"] == 20.0
    assert result["usage"] == "planning_reference_only"


def test_readiness_accepts_only_live_screening_health(monkeypatch):
    for key, value in FULL_READY_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("production_readiness._safe_evidence", lambda *_: {"verified": True})

    health = {
        "by_name": {
            "ofac_sanctions_data": {"configured": True, "reachable": True},
            "tariff_classification": {"configured": True, "reachable": True},
            "logistics_tracking": {"configured": True, "reachable": True},
            "fx_execution": {"configured": True, "reachable": True},
        }
    }
    result = evaluate_production_readiness(
        runtime_ok=True,
        connector_health=health,
        persistence_schema_evidence=SUPABASE_SCHEMA_EVIDENCE,
    )
    assert result["score"] == 100
    assert result["production_ready"] is True

    health["by_name"]["ofac_sanctions_data"]["reachable"] = False
    blocked = evaluate_production_readiness(
        runtime_ok=True,
        connector_health=health,
        persistence_schema_evidence=SUPABASE_SCHEMA_EVIDENCE,
    )
    assert blocked["production_ready"] is False
    assert "restricted_party_screening" in blocked["blockers"]
