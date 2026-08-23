from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ReadinessGate:
    name: str
    passed: bool
    critical: bool
    evidence: str
    remediation: str


def _present(name: str) -> bool:
    return bool(os.getenv(name, '').strip())


def _true(name: str) -> bool:
    return os.getenv(name, 'false').strip().lower() == 'true'


def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)).strip() or default)
    except ValueError:
        return default


def _connector_pass(connector_health: dict[str, Any] | None, name: str) -> bool:
    if not connector_health:
        return False
    item = connector_health.get('by_name', {}).get(name, {})
    return bool(item.get('configured') and item.get('reachable'))


def _persistent_backend_status() -> tuple[bool, str]:
    database = any(_present(name) for name in (
        'DATABASE_URL', 'POSTGRES_URL', 'NEON_DATABASE_URL', 'NEON_POSTGRES_URL', 'POSTGRES_PRISMA_URL'
    ))
    insforge = _present('INSFORGE_BASE_URL') and _present('INSFORGE_API_KEY')
    if database:
        return True, 'Neon/Postgres durable persistence configured'
    if insforge:
        return True, 'InsForge durable persistence configured'
    return False, 'No durable persistence provider configured'


def _production_identity_status(auth_provider: str) -> tuple[bool, str, str]:
    legacy_disabled = not _true('ALLOW_LEGACY_LOCAL_AUTH')
    if auth_provider in {'neon', 'neon_auth'}:
        ok = legacy_disabled
        return ok, 'Neon Auth JWT/JWKS identity selected; legacy local participant auth disabled', 'Keep AUTH_PROVIDER=neon_auth and ALLOW_LEGACY_LOCAL_AUTH=false; override NEON_AUTH_URL/NEON_AUTH_JWKS_URL when moving branches.'
    if auth_provider == 'insforge':
        ok = legacy_disabled and _present('INSFORGE_ANON_KEY')
        return ok, 'InsForge JWT identity selected; legacy local participant auth disabled', 'Configure INSFORGE_ANON_KEY and keep ALLOW_LEGACY_LOCAL_AUTH=false.'
    return False, 'No approved production identity provider selected', 'Set AUTH_PROVIDER=neon_auth (current architecture) or AUTH_PROVIDER=insforge and configure the matching identity settings.'


def evaluate_production_readiness(*, runtime_ok: bool = True, e2e_ok: bool | None = None, connector_health: dict[str, Any] | None = None) -> dict[str, Any]:
    auth_provider = os.getenv('AUTH_PROVIDER', 'neon_auth').strip().lower() or 'neon_auth'
    if e2e_ok is None:
        e2e_ok = _true('E2E_TRADE_WORKFLOW_VERIFIED')

    if connector_health:
        screening_ok = _connector_pass(connector_health, 'ofac_sanctions_data')
        tariff_ok = _connector_pass(connector_health, 'tariff_classification')
        logistics_ok = _connector_pass(connector_health, 'logistics_tracking')
        fx_ok = _connector_pass(connector_health, 'fx_execution')
        screening_evidence = 'Live authoritative OFAC SLS connector reachable'
        tariff_evidence = 'Authoritative tariff/classification provider reachable'
        logistics_evidence = 'Live logistics provider reachable'
        fx_evidence = 'Executable/settlement FX provider reachable'
    else:
        screening_ok = _present('TRADE_GOV_API_KEY') or _true('OFAC_DIRECT_SCREENING')
        tariff_ok = _present('TARIFF_DATA_PROVIDER')
        logistics_ok = _present('LOGISTICS_DATA_PROVIDER')
        fx_ok = _present('FX_EXECUTION_PROVIDER') or _present('FX_DATA_PROVIDER')
        screening_evidence = 'Government screening connector configured'
        tariff_evidence = 'Tariff/classification provider configured'
        logistics_evidence = 'Logistics provider configured'
        fx_evidence = 'FX provider configured'

    translation_provider_ok = os.getenv('TRANSLATION_PROVIDER', '').strip().lower() == 'azure' and _present('AZURE_TRANSLATOR_ENDPOINT') and _present('AZURE_TRANSLATOR_KEY')
    secure_storage_configured = all(_present(x) for x in ['INSFORGE_S3_ENDPOINT', 'INSFORGE_S3_ACCESS_KEY_ID', 'INSFORGE_S3_SECRET_ACCESS_KEY', 'INSFORGE_STORAGE_BUCKET'])
    production_identity, identity_evidence, identity_remediation = _production_identity_status(auth_provider)
    persistent_backend_ok, persistent_backend_evidence = _persistent_backend_status()
    persistence_isolation_ok = _true('PERSISTENCE_ISOLATION_VERIFIED') or _true('INSFORGE_RLS_VERIFIED')
    persistence_schema_ok = _true('PERSISTENCE_SCHEMA_VERIFIED') or _true('INSFORGE_SCHEMAS_APPLIED')
    ai_provider_configured = _present('OPENAI_API_KEY') and _present('ANTHROPIC_API_KEY')

    gates = [
        ReadinessGate('production_runtime', runtime_ok, True, 'HTTP runtime health', 'Deploy a healthy production revision.'),
        ReadinessGate('persistent_backend', persistent_backend_ok, True, persistent_backend_evidence, 'Attach Neon/Postgres to Vercel (DATABASE_URL/POSTGRES_URL) or configure InsForge server credentials.'),
        ReadinessGate('production_identity', production_identity, True, identity_evidence, identity_remediation),
        ReadinessGate('persistence_isolation_verified', persistence_isolation_ok, True, 'Live tenant/role persistence isolation verification recorded', 'Run owner/staff/customer isolation tests and set PERSISTENCE_ISOLATION_VERIFIED=true only after evidence is recorded.'),
        ReadinessGate('persistence_schema_verified', persistence_schema_ok, True, 'Production persistence schema/bootstrap verification recorded', 'Verify the active durable backend schema and set PERSISTENCE_SCHEMA_VERIFIED=true only after the test passes.'),
        ReadinessGate('owner_mfa', _true('OWNER_MFA_REQUIRED'), True, 'Owner MFA policy enabled', 'Require MFA for owner/admin access.'),
        ReadinessGate('ai_brain_providers', ai_provider_configured and _true('AI_BRAIN_E2E_VERIFIED'), True, 'OpenAI + Anthropic credentials and AI Brain E2E verification; model routing uses application defaults or explicit overrides', 'Configure ANTHROPIC_API_KEY, verify GPT/Claude routing and consensus, and prove ADVISORY_ONLY cannot cross transaction authority boundaries.'),
        ReadinessGate('restricted_party_screening', screening_ok, True, screening_evidence, 'Restore/configure authoritative sanctions screening connectivity.'),
        ReadinessGate('tariff_classification', tariff_ok, True, tariff_evidence, 'Configure authoritative tariff/HTS data provider.'),
        ReadinessGate('logistics_provider', logistics_ok and _true('CARRIER_E2E_VERIFIED'), True, logistics_evidence + '; carrier E2E verified', 'Verify real milestone normalization/ETA/exception flow.'),
        ReadinessGate('fx_execution_provider', fx_ok, True, fx_evidence, 'Configure bank/settlement FX provider.'),
        ReadinessGate('secure_document_storage', _true('INSFORGE_STORAGE_ENABLED') and secure_storage_configured and _true('SIGNED_DOCUMENT_STORAGE_VERIFIED'), True, 'Private signed document storage verified', 'Verify signed upload/download, malware gate, retention and legal hold.'),
        ReadinessGate('global_translation', translation_provider_ok and _true('MULTILINGUAL_E2E_VERIFIED'), True, 'Translation provider plus multilingual E2E verified', 'Verify language persistence, RTL and source preservation.'),
        ReadinessGate('country_activation_governance', _true('COUNTRY_ACTIVATION_E2E_VERIFIED'), True, 'Country/corridor activation governance verified', 'Verify READY/LIMITED/BLOCKED derivation and hypothetical/live isolation.'),
        ReadinessGate('global_supplier_sourcing', _true('GLOBAL_SUPPLIER_SOURCING_E2E_VERIFIED'), True, 'Worldwide candidate sourcing, origin/destination corridor controls and owner supplier selection verified', 'Run a permitted corridor E2E and prove BLOCKED/LIMITED candidates cannot be selected.'),
        ReadinessGate('managed_trade_gateway', _true('MANAGED_TRADE_GATEWAY_E2E_VERIFIED'), True, 'SAHJONY request intake, supplier sourcing/due diligence, role assignment, milestone gating and owner release verified', 'Run an E2E managed transaction against the active persistence provider.'),
        ReadinessGate('intermediary_mode', _true('INTERMEDIARY_MODE_E2E_VERIFIED'), True, 'Broker/agent engagement, disclosed economics, legal-role assignments, title/funds controls and database release guard verified', 'Run intermediary E2E tests.'),
        ReadinessGate('business_operational_controls', _true('BUSINESS_OPERATIONAL_READINESS_E2E_VERIFIED'), True, 'Partners, agreements, counterparty due diligence, product dossiers, incident handling and reconciliation controls verified', 'Verify signed operating partners, approved agreement templates, KYB/sanctions dossiers, product classification dossiers and incident/claims workflow.'),
        ReadinessGate('cuba_private_business_eligibility', _true('CUBA_PRIVATE_BUSINESS_E2E_VERIFIED'), True, 'Cuban private-business ownership, employee-count, government-control, screening, banking and eligibility workflow verified', 'Prove ineligible or disallowed businesses cannot pass.'),
        ReadinessGate('cuba_authorized_trade_desk', _true('CUBA_AUTHORIZED_TRADE_E2E_VERIFIED'), True, 'Cuba employee authorization, verified authority, transaction gates, HOLD, owner release and audit E2E verified', 'Run a production-safe US->CU authorized-trade test.'),
        ReadinessGate('collaboration_isolation', _true('COLLABORATION_E2E_VERIFIED'), True, 'External sharing isolation verified', 'Run sharing isolation, expiration and revocation tests.'),
        ReadinessGate('accounting_ledger', _true('ACCOUNTING_LEDGER_VERIFIED') and _true('PAYMENT_RECONCILIATION_VERIFIED'), True, 'Double-entry ledger and reconciliation verified', 'Post balanced/reversal journals and reconcile test payments.'),
        ReadinessGate('beneficiary_maker_checker', _true('BENEFICIARY_MAKER_CHECKER_VERIFIED'), True, 'Bank-detail maker-checker verified', 'Verify independent beneficiary validation plus owner approval.'),
        ReadinessGate('audit_retention', _int('AUDIT_RETENTION_DAYS') >= 365, True, 'Audit retention >=365 days', 'Set audit retention >=365 days.'),
        ReadinessGate('backup_policy', _true('BACKUPS_ENABLED') and _true('BACKUP_RESTORE_TESTED'), True, 'Backups and restore drill verified', 'Run and document database/storage restore test.'),
        ReadinessGate('monitoring_alerts', _present('ALERT_WEBHOOK_URL') or _true('VERCEL_MONITORING_ENABLED'), True, 'Production alert path configured', 'Configure runtime alerting.'),
        ReadinessGate('first_live_trade_certified', _true('FIRST_LIVE_TRADE_CERTIFIED'), True, 'Real customer-to-supplier transaction delivered, paid, reconciled, SAHJONY fee collected and audit closed', 'Complete First Live Trade Certification in the Owner OS; do not set this flag from a dry run.'),
        ReadinessGate('e2e_trade_workflow', bool(e2e_ok), True, 'Verified end-to-end trade workflow', 'Run a production-safe supplier-to-profit E2E workflow.'),
    ]

    critical = [g for g in gates if g.critical]
    passed = sum(1 for g in critical if g.passed)
    blockers = [g.name for g in critical if not g.passed]
    return {
        'score': round(passed / len(critical) * 100),
        'passed_gates': passed,
        'total_gates': len(critical),
        'blocker_count': len(blockers),
        'production_ready': not blockers,
        'release_gate': 'READY' if not blockers else 'HOLD',
        'identity_provider': auth_provider,
        'gates': [asdict(g) for g in gates],
        'blockers': blockers,
    }
