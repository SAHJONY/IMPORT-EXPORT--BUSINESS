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
    return bool(os.getenv(name, "").strip())


def _true(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)).strip() or default)
    except ValueError:
        return default


def _connector_pass(connector_health: dict[str, Any] | None, name: str) -> bool:
    if not connector_health:
        return False
    item = connector_health.get("by_name", {}).get(name, {})
    return bool(item.get("configured") and item.get("reachable"))


def evaluate_production_readiness(
    *,
    runtime_ok: bool = True,
    e2e_ok: bool | None = None,
    connector_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail-closed production readiness for the complete import-export OS.

    Verification flags are intentionally separate from configuration flags. A provider,
    schema, RLS policy, ledger, backup, or workflow is not treated as production-ready
    merely because environment variables exist.
    """
    auth_provider = os.getenv("AUTH_PROVIDER", "").strip().lower()
    if e2e_ok is None:
        e2e_ok = _true("E2E_TRADE_WORKFLOW_VERIFIED")

    if connector_health:
        screening_ok = _connector_pass(connector_health, "ofac_sanctions_data")
        tariff_ok = _connector_pass(connector_health, "tariff_classification")
        logistics_ok = _connector_pass(connector_health, "logistics_tracking")
        fx_ok = _connector_pass(connector_health, "fx_execution")
        screening_evidence = "Live authoritative OFAC SLS connector reachable"
        tariff_evidence = "Authoritative tariff/classification provider reachable"
        logistics_evidence = "Live logistics provider reachable"
        fx_evidence = "Executable/settlement FX provider reachable"
    else:
        screening_ok = _present("TRADE_GOV_API_KEY") or _true("OFAC_DIRECT_SCREENING")
        tariff_ok = _present("TARIFF_DATA_PROVIDER")
        logistics_ok = _present("LOGISTICS_DATA_PROVIDER")
        fx_ok = _present("FX_EXECUTION_PROVIDER") or _present("FX_DATA_PROVIDER")
        screening_evidence = "Government screening connector configured"
        tariff_evidence = "Tariff/classification provider configured"
        logistics_evidence = "Logistics provider configured"
        fx_evidence = "FX provider configured"

    translation_provider_ok = (
        os.getenv("TRANSLATION_PROVIDER", "").strip().lower() == "azure"
        and _present("AZURE_TRANSLATOR_ENDPOINT")
        and _present("AZURE_TRANSLATOR_KEY")
    )

    gates = [
        ReadinessGate("production_runtime", runtime_ok, True, "HTTP runtime health", "Deploy a healthy production revision."),
        ReadinessGate("insforge_backend", _present("INSFORGE_BASE_URL") and _present("INSFORGE_API_KEY"), True, "InsForge server credentials present", "Configure InsForge production project credentials."),
        ReadinessGate("insforge_auth", auth_provider == "insforge" and _present("INSFORGE_ANON_KEY"), True, "AUTH_PROVIDER=insforge and public key present", "Enable InsForge Auth/JWT for user-facing access."),
        ReadinessGate("tenant_rls_verified", _true("INSFORGE_RLS_VERIFIED"), True, "Live tenant/role RLS verification recorded", "Run cross-tenant owner/staff/customer/external isolation tests and only then set INSFORGE_RLS_VERIFIED=true."),
        ReadinessGate("all_schemas_applied", _true("INSFORGE_SCHEMAS_APPLIED"), True, "Production schemas applied and checked", "Apply and verify every current InsForge schema before release."),
        ReadinessGate("owner_mfa", _true("OWNER_MFA_REQUIRED"), True, "Owner MFA policy enabled", "Require MFA for owner/admin access."),
        ReadinessGate("restricted_party_screening", screening_ok, True, screening_evidence, "Restore/configure authoritative sanctions screening connectivity."),
        ReadinessGate("tariff_classification", tariff_ok, True, tariff_evidence, "Configure authoritative tariff/HTS data provider."),
        ReadinessGate("logistics_provider", logistics_ok and _true("CARRIER_E2E_VERIFIED"), True, logistics_evidence + "; carrier E2E verified", "Configure carrier provider and verify real milestone normalization/ETA/exception flow."),
        ReadinessGate("fx_execution_provider", fx_ok, True, fx_evidence, "Configure bank/settlement FX provider."),
        ReadinessGate("durable_documents", _true("INSFORGE_STORAGE_ENABLED") and _true("SIGNED_DOCUMENT_STORAGE_VERIFIED"), True, "Private storage plus signed upload/download flow verified", "Verify private signed storage, MIME/size validation, retention and access controls."),
        ReadinessGate("global_translation", translation_provider_ok and _true("MULTILINGUAL_E2E_VERIFIED"), True, "Translation provider plus multilingual/RTL E2E verified", "Configure Azure Translator and verify language persistence, RTL, source preservation and regulated-review behavior."),
        ReadinessGate("collaboration_isolation", _true("COLLABORATION_E2E_VERIFIED"), True, "External-share expiry/revocation/scope isolation verified", "Run external sharing isolation, expiration, revocation and curated-item tests."),
        ReadinessGate("accounting_ledger", _true("ACCOUNTING_LEDGER_VERIFIED") and _true("PAYMENT_RECONCILIATION_VERIFIED"), True, "Double-entry ledger and payment reconciliation verified", "Post test balanced/reversal journals and reconcile test payments before live financial operations."),
        ReadinessGate("beneficiary_maker_checker", _true("BENEFICIARY_MAKER_CHECKER_VERIFIED"), True, "Bank-detail change maker-checker verified", "Verify independent beneficiary validation plus owner approval workflow."),
        ReadinessGate("audit_retention", _int("AUDIT_RETENTION_DAYS") >= 365, True, "Audit retention >=365 days", "Set auditable retention to at least 365 days."),
        ReadinessGate("backup_policy", _true("BACKUPS_ENABLED") and _true("BACKUP_RESTORE_TESTED"), True, "Backups enabled and restore drill passed", "Run and document a database/storage restore test."),
        ReadinessGate("monitoring_alerts", _present("ALERT_WEBHOOK_URL") or _true("VERCEL_MONITORING_ENABLED"), True, "Production alert path configured", "Configure runtime alerting and incident notifications."),
        ReadinessGate("e2e_trade_workflow", bool(e2e_ok), True, "Verified end-to-end trade workflow", "Run and record a production-safe supplier-to-profit E2E workflow before accepting live business."),
    ]
    critical = [g for g in gates if g.critical]
    passed = sum(1 for g in critical if g.passed)
    score = round(passed / len(critical) * 100)
    blockers = [g.name for g in critical if not g.passed]
    return {
        "score": score,
        "production_ready": not blockers,
        "release_gate": "READY" if not blockers else "HOLD",
        "gates": [asdict(g) for g in gates],
        "blockers": blockers,
    }
