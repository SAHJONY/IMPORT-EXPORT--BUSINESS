from production_readiness import evaluate_production_readiness


REQUIRED_ENV = {
    "INSFORGE_BASE_URL": "https://example.insforge.app",
    "INSFORGE_API_KEY": "ik_test",
    "INSFORGE_ANON_KEY": "anon_test",
    "AUTH_PROVIDER": "insforge",
    "ALLOW_LEGACY_LOCAL_AUTH": "false",
    "INSFORGE_RLS_VERIFIED": "true",
    "INSFORGE_SCHEMAS_APPLIED": "true",
    "OWNER_MFA_REQUIRED": "true",
    "OPENAI_API_KEY": "openai_test",
    "ANTHROPIC_API_KEY": "anthropic_test",
    "OPENAI_EXECUTIVE_MODEL": "openai-test-model",
    "ANTHROPIC_FRONTIER_MODEL": "anthropic-test-model",
    "ANTHROPIC_AGENT_MODEL": "anthropic-agent-test-model",
    "AI_BRAIN_E2E_VERIFIED": "true",
    "OFAC_DIRECT_SCREENING": "true",
    "TARIFF_DATA_PROVIDER": "authoritative-test-provider",
    "LOGISTICS_DATA_PROVIDER": "live-test-provider",
    "CARRIER_E2E_VERIFIED": "true",
    "FX_EXECUTION_PROVIDER": "live-test-provider",
    "INSFORGE_STORAGE_ENABLED": "true",
    "INSFORGE_S3_ENDPOINT": "https://example.insforge.app/storage/v1/s3",
    "INSFORGE_S3_ACCESS_KEY_ID": "access-test",
    "INSFORGE_S3_SECRET_ACCESS_KEY": "secret-test",
    "INSFORGE_STORAGE_BUCKET": "trade-documents",
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
    "AUDIT_RETENTION_DAYS": "365",
    "BACKUPS_ENABLED": "true",
    "BACKUP_RESTORE_TESTED": "true",
    "VERCEL_MONITORING_ENABLED": "true",
    "FIRST_LIVE_TRADE_CERTIFIED": "true",
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


def test_neon_auth_is_accepted_as_production_identity(monkeypatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AUTH_PROVIDER", "neon_auth")
    monkeypatch.setenv("NEON_AUTH_PROVISIONED", "true")
    monkeypatch.setenv("ALLOW_LEGACY_LOCAL_AUTH", "false")
    result = evaluate_production_readiness(runtime_ok=True)
    gate = next(g for g in result["gates"] if g["name"] == "production_identity")
    assert gate["passed"] is True
    assert result["identity_provider"] == "neon_auth"
