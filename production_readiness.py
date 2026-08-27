from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from country_governance_evidence import country_governance_evidence
from payment_engine import CANONICAL_TRANSACTION_CURRENCY, USD_ONLY_TRANSACTIONS
from secure_storage import storage_configuration_status


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


def evaluate_production_readiness(
    *,
    runtime_ok: bool = True,
    e2e_ok: bool | None = None,
    connector_health: dict[str, Any] | None = None,
    persistence_schema_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    auth_provider = os.getenv('AUTH_PROVIDER', 'neon_auth').strip().lower() or 'neon_auth'
    if e2e_ok is None:
        e2e_ok = _true('E2E_TRADE_WORKFLOW_VERIFIED')

    if connector_health:
        screening_ok = _connector_pass(connector_health, 'ofac_sanctions_data')
        tariff_ok = _connector_pass(connector_health, 'tariff_classification')
        logistics_ok = _connector_pass(connector_health, 'logistics_tracking')
        external_fx_ok = _connector_pass(connector_health, 'fx_execution')
        screening_evidence = 'Live authoritative OFAC SLS connector reachable'
        tariff_evidence = 'Authoritative tariff/classification provider reachable'
        logistics_evidence = 'Live logistics provider reachable'
    else:
        screening_ok = _present('TRADE_GOV_API_KEY') or _true('OFAC_DIRECT_SCREENING')
        tariff_ok = _present('TARIFF_DATA_PROVIDER')
        logistics_ok = _present('LOGISTICS_DATA_PROVIDER')
        external_fx_ok = _present('FX_EXECUTION_PROVIDER') or _present('FX_DATA_PROVIDER')
        screening_evidence = 'Government screening connector configured'
        tariff_evidence = 'Tariff/classification provider configured'
        logistics_evidence = 'Logistics provider configured'

    if USD_ONLY_TRANSACTIONS and CANONICAL_TRANSACTION_CURRENCY == 'USD':
        settlement_ok = True
        settlement_evidence = 'Canonical customer transaction currency is USD-only; executable FX is not required for customer settlement. External FX remains optional for internal supplier-cost conversion/planning.'
        settlement_remediation = 'No executable FX provider is required while the hard USD-only settlement policy remains enforced. If non-USD settlement is introduced, configure and verify an approved execution provider first.'
    else:
        settlement_ok = external_fx_ok
        settlement_evidence = 'Executable/settlement FX provider reachable'
        settlement_remediation = 'Configure bank/settlement FX provider.'

    translation_provider_ok = os.getenv('TRANSLATION_PROVIDER', '').strip().lower() == 'azure' and _present('AZURE_TRANSLATOR_ENDPOINT') and _present('AZURE_TRANSLATOR_KEY')
    storage_status = storage_configuration_status()
    secure_storage_configured = bool(storage_status.get('configured'))
    storage_provider = storage_status.get('provider') or 'none'
    production_identity, identity_evidence, identity_remediation = _production_identity_status(auth_provider)
    persistent_backend_ok, persistent_backend_evidence = _persistent_backend_status()

    live_rls_verified = bool((persistence_schema_evidence or {}).get('rls_verified'))
    persistence_isolation_ok = live_rls_verified or _true('PERSISTENCE_ISOLATION_VERIFIED') or _true('INSFORGE_RLS_VERIFIED')
    if live_rls_verified:
        isolation_evidence = 'Active production Postgres RLS tables, identity functions and required policies verified directly from pg_class/pg_policies/pg_proc'
    elif persistence_schema_evidence:
        isolation_evidence = f"Live RLS evidence incomplete: {(persistence_schema_evidence or {}).get('rls_reason') or 'required RLS tables, functions or policies are incomplete'}"
    else:
        isolation_evidence = 'Tenant/role persistence isolation requires recorded live verification'

    schema_runtime_verified = bool((persistence_schema_evidence or {}).get('verified'))
    persistence_schema_ok = schema_runtime_verified or _true('PERSISTENCE_SCHEMA_VERIFIED') or _true('INSFORGE_SCHEMAS_APPLIED')
    if schema_runtime_verified:
        schema_evidence = 'Active production database schema verified directly through information_schema/pg_indexes'
    elif persistence_schema_evidence:
        schema_evidence = f"Production schema evidence failed: {(persistence_schema_evidence or {}).get('reason') or 'required tables/columns/indexes are incomplete'}"
    else:
        schema_evidence = 'Production persistence schema/bootstrap verification recorded'

    owner_mfa_ok = _true('OWNER_MFA_REQUIRED') and _present('OWNER_TOTP_SECRET')
    ai_provider_configured = _present('OPENAI_API_KEY') and _present('ANTHROPIC_API_KEY')

    country_evidence = country_governance_evidence()
    country_governance_ok = bool(country_evidence.get('verified'))
    if country_governance_ok:
        country_evidence_text = (
            f"Live PostgreSQL country/corridor governance verified: "
            f"{country_evidence.get('ready_live_country_count', 0)} READY live countries and "
            f"{country_evidence.get('ready_live_corridor_count', 0)} fully governed LIVE/READY corridors"
        )
    else:
        country_evidence_text = (
            'Live country/corridor governance incomplete: '
            + str(country_evidence.get('reason') or 'no fully evidenced owner-approved LIVE/READY corridor')
        )

    gates = [
        ReadinessGate('production_runtime', runtime_ok, True, 'HTTP runtime health', 'Deploy a healthy production revision.'),
        ReadinessGate('persistent_backend', persistent_backend_ok, True, persistent_backend_evidence, 'Attach Neon/Postgres to Vercel (DATABASE_URL/POSTGRES_URL) or configure InsForge server credentials.'),
        ReadinessGate('production_identity', production_identity, True, identity_evidence, identity_remediation),
        ReadinessGate('persistence_isolation_verified', persistence_isolation_ok, True, isolation_evidence, 'Apply and verify the identity/RLS foundation on participant-facing tables, then prove owner/staff/customer isolation. Do not set a manual verification flag without evidence.'),
        ReadinessGate('persistence_schema_verified', persistence_schema_ok, True, schema_evidence, 'Verify the active durable backend schema against required physical tables, columns and indexes.'),
        ReadinessGate('owner_mfa', owner_mfa_ok, True, 'Owner TOTP MFA policy enabled and a server-side TOTP secret is configured', 'Set OWNER_MFA_REQUIRED=true and configure OWNER_TOTP_SECRET through the production secret manager; never commit the secret to Git.'),
        ReadinessGate('ai_brain_providers', ai_provider_configured and _true('AI_BRAIN_E2E_VERIFIED'), True, 'OpenAI + Anthropic credentials and AI Brain E2E verification; model routing uses application defaults or explicit overrides', 'Configure ANTHROPIC_API_KEY, verify GPT/Claude routing and consensus, and prove ADVISORY_ONLY cannot cross transaction authority boundaries.'),
        ReadinessGate('restricted_party_screening', screening_ok, True, screening_evidence, 'Restore/configure authoritative sanctions screening connectivity.'),
        ReadinessGate('tariff_classification', tariff_ok, True, tariff_evidence, 'Restore the authoritative USITC HTS source or another approved corridor-specific tariff provider.'),
        ReadinessGate('logistics_provider', logistics_ok and _true('CARRIER_E2E_VERIFIED'), True, logistics_evidence + '; carrier E2E verified', 'Verify real milestone normalization/ETA/exception flow.'),
        ReadinessGate('fx_execution_provider', settlement_ok, True, settlement_evidence, settlement_remediation),
        ReadinessGate('secure_document_storage', secure_storage_configured and _true('SIGNED_DOCUMENT_STORAGE_VERIFIED'), True, f'Provider-neutral private signed document storage configured via {storage_provider}; signed storage verification={_true("SIGNED_DOCUMENT_STORAGE_VERIFIED")}', 'Configure one supported S3-compatible storage profile (InsForge S3, Cloudflare R2, or generic S3-compatible), then verify signed upload/download, malware gate, retention and legal hold.'),
        ReadinessGate('global_translation', translation_provider_ok and _true('MULTILINGUAL_E2E_VERIFIED'), True, 'Translation provider plus multilingual E2E verified', 'Verify language persistence, RTL and source preservation.'),
        ReadinessGate('country_activation_governance', country_governance_ok, True, country_evidence_text, 'Apply the country-governance schema, maintain all 16 mandatory controls with current evidence, owner-approve each live jurisdiction, and verify at least one fully governed LIVE/READY corridor. Hypothetical jurisdictions must remain simulation-only.'),
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
        'canonical_transaction_currency': CANONICAL_TRANSACTION_CURRENCY,
        'usd_only_transactions': USD_ONLY_TRANSACTIONS,
        'persistence_schema_evidence': persistence_schema_evidence,
        'country_governance_evidence': country_evidence,
        'gates': [asdict(g) for g in gates],
        'blockers': blockers,
    }
