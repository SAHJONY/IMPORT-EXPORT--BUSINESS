from production_readiness import evaluate_production_readiness


REQUIRED_ENV = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "service-role-test",
    "SUPABASE_STORAGE_BUCKET": "trade-documents",
    "AUTH_PROVIDER": "supabase_auth",
    "ALLOW_LEGACY_LOCAL_AUTH": "false",
    "OWNER_MFA_REQUIRED": "true",
    "OWNER_TOTP_SECRET": "JBSWY3DPEHPK3PXP",
    "OPENAI_API_KEY": "openai_test",
    "ANTHROPIC_API_KEY": "anthropic_test",
    "AI_BRAIN_E2E_VERIFIED": "true",
    "OFAC_DIRECT_SCREENING": "true",
    "TARIFF_DATA_PROVIDER": "authoritative-test-provider",
    "LOGISTICS_DATA_PROVIDER": "live-test-provider",
    "CARRIER_E2E_VERIFIED": "true",
    "FX_EXECUTION_PROVIDER": "live-test-provider",
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

SUPABASE_SCHEMA_EVIDENCE = {
    "verified": True,
    "provider": "supabase",
    "present_table_count": 10,
    "rls_verified": True,
    "rls_enabled_table_count": 10,
    "rls_required_table_count": 10,
}


def test_readiness_fails_closed_without_external_dependencies(monkeypatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    for key in ["DATABASE_URL", "POSTGRES_URL", "NEON_DATABASE_URL", "NEON_POSTGRES_URL", "POSTGRES_PRISMA_URL"]:
        monkeypatch.delenv(key, raising=False)
    result = evaluate_production_readiness(runtime_ok=True)
    assert result["production_ready"] is False
    assert result["release_gate"] == "HOLD"
    assert "persistent_backend" in result["blockers"]
    assert "e2e_trade_workflow" in result["blockers"]


def test_readiness_reaches_100_only_when_every_critical_gate_is_explicit(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("production_readiness._safe_evidence", lambda *_: {"verified": True})
    result = evaluate_production_readiness(runtime_ok=True, persistence_schema_evidence=SUPABASE_SCHEMA_EVIDENCE)
    assert result["score"] == 100
    assert result["production_ready"] is True
    assert result["release_gate"] == "READY"
    assert result["blockers"] == []


def test_runtime_failure_blocks_release_even_with_all_dependencies(monkeypatch):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("production_readiness._safe_evidence", lambda *_: {"verified": True})
    result = evaluate_production_readiness(runtime_ok=False, persistence_schema_evidence=SUPABASE_SCHEMA_EVIDENCE)
    assert result["production_ready"] is False
    assert "production_runtime" in result["blockers"]


def test_legacy_neon_auth_is_not_accepted_as_production_identity(monkeypatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AUTH_PROVIDER", "neon_auth")
    monkeypatch.setenv("ALLOW_LEGACY_LOCAL_AUTH", "false")
    result = evaluate_production_readiness(runtime_ok=True)
    gate = next(g for g in result["gates"] if g["name"] == "production_identity")
    assert gate["passed"] is False
    assert result["identity_provider"] == "supabase_auth"


def test_legacy_neon_database_url_does_not_satisfy_canonical_backend_gate(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@example.neon.tech/neondb?sslmode=require")
    result = evaluate_production_readiness(runtime_ok=True)
    gate = next(g for g in result["gates"] if g["name"] == "persistent_backend")
    assert gate["passed"] is False
    assert "Supabase configured=False" in gate["evidence"]


def test_owner_mfa_gate_requires_real_totp_secret(monkeypatch):
    monkeypatch.setenv("OWNER_MFA_REQUIRED", "true")
    monkeypatch.delenv("OWNER_TOTP_SECRET", raising=False)
    result = evaluate_production_readiness(runtime_ok=True)
    gate = next(g for g in result["gates"] if g["name"] == "owner_mfa")
    assert gate["passed"] is False
    monkeypatch.setenv("OWNER_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    result = evaluate_production_readiness(runtime_ok=True)
    gate = next(g for g in result["gates"] if g["name"] == "owner_mfa")
    assert gate["passed"] is True
