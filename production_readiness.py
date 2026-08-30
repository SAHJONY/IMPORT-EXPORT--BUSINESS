from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from governance_policy import AUDIT_RETENTION_DAYS
from insforge_backend import persistent_backend_status
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


def _safe_evidence(module_name: str, function_name: str, *args) -> dict[str, Any]:
    try:
        module = __import__(module_name, fromlist=[function_name])
        return getattr(module, function_name)(*args) or {}
    except Exception as exc:
        return {"verified": False, "reason": f"{type(exc).__name__}: {str(exc)[:180]}"}


def evaluate_production_readiness(
    *,
    runtime_ok: bool = True,
    e2e_ok: bool | None = None,
    connector_health: dict[str, Any] | None = None,
    persistence_schema_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    auth_provider = os.getenv("AUTH_PROVIDER", "supabase_auth").strip().lower() or "supabase_auth"
    e2e_ok = _true("E2E_TRADE_WORKFLOW_VERIFIED") if e2e_ok is None else e2e_ok

    persistence = persistent_backend_status()
    supabase_backend_ok = bool(persistence.get("supabase_configured")) and persistence.get("provider") == "supabase"
    identity_ok = (
        auth_provider in {"supabase", "supabase_auth"}
        and _present("SUPABASE_URL")
        and (_present("SUPABASE_SERVICE_ROLE_KEY") or _present("SUPABASE_SECRET_KEY") or _present("SUPABASE_KEY"))
        and not _true("ALLOW_LEGACY_LOCAL_AUTH")
    )

    schema = persistence_schema_evidence or {}
    schema_ok = bool(schema.get("verified"))
    rls_ok = bool(schema.get("rls_verified"))
    storage = storage_configuration_status()
    storage_configured = bool(storage.get("configured")) and storage.get("provider") == "supabase_storage"

    screening_ok = _connector_pass(connector_health, "ofac_sanctions_data") if connector_health else (_present("TRADE_GOV_API_KEY") or _true("OFAC_DIRECT_SCREENING"))
    tariff_ok = _connector_pass(connector_health, "tariff_classification") if connector_health else _present("TARIFF_DATA_PROVIDER")
    logistics_connector_ok = _connector_pass(connector_health, "logistics_tracking") if connector_health else (_present("LOGISTICS_DATA_PROVIDER") or _present("MAERSK_CLIENT_ID"))

    if USD_ONLY_TRANSACTIONS and CANONICAL_TRANSACTION_CURRENCY == "USD":
        settlement_ok = True
        settlement_evidence = "USD-only customer settlement policy is enforced; executable FX is not required."
    else:
        settlement_ok = _connector_pass(connector_health, "fx_execution") if connector_health else (_present("FX_EXECUTION_PROVIDER") or _present("FX_DATA_PROVIDER"))
        settlement_evidence = "Executable FX provider required for non-USD settlement."

    translation_ok = os.getenv("TRANSLATION_PROVIDER", "").strip().lower() == "azure" and _present("AZURE_TRANSLATOR_ENDPOINT") and _present("AZURE_TRANSLATOR_KEY") and _true("MULTILINGUAL_E2E_VERIFIED")
    owner_mfa_ok = _true("OWNER_MFA_REQUIRED") and _present("OWNER_TOTP_SECRET")
    ai_ok = _present("OPENAI_API_KEY") and _present("ANTHROPIC_API_KEY") and _true("AI_BRAIN_E2E_VERIFIED")

    country_evidence = _safe_evidence("country_governance_evidence", "country_governance_evidence")
    sourcing_evidence = _safe_evidence("supplier_sourcing_evidence", "supplier_sourcing_evidence", country_evidence)
    managed_evidence = _safe_evidence("managed_trade_gateway_evidence", "managed_trade_gateway_evidence")

    gates = [
        ReadinessGate("production_runtime", runtime_ok, True, "HTTP runtime health", "Deploy a healthy production revision."),
        ReadinessGate("persistent_backend", supabase_backend_ok, True, f"Canonical provider={persistence.get('provider')}; Supabase configured={persistence.get('supabase_configured')}", "Configure SUPABASE_URL plus SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SECRET_KEY."),
        ReadinessGate("production_identity", identity_ok, True, "Supabase Auth selected with legacy local auth disabled", "Set AUTH_PROVIDER=supabase_auth and configure Supabase server credentials."),
        ReadinessGate("persistence_isolation_verified", rls_ok, True, f"Supabase RLS evidence: {schema.get('rls_enabled_table_count', 0)}/{schema.get('rls_required_table_count', schema.get('present_table_count', 0))} public tables", "Enable RLS on every public application table and verify through sahjony_platform_evidence()."),
        ReadinessGate("persistence_schema_verified", schema_ok, True, f"Supabase platform evidence verified={schema_ok}; public tables={schema.get('present_table_count', 0)}", "Apply the canonical Supabase schema and verify the platform evidence RPC."),
        ReadinessGate("owner_mfa", owner_mfa_ok, True, "Owner Supabase identity is additionally protected by application TOTP MFA", "Set OWNER_MFA_REQUIRED=true and configure OWNER_TOTP_SECRET in production secrets."),
        ReadinessGate("ai_brain_providers", ai_ok, True, "OpenAI + Anthropic + AI Brain E2E", "Configure both AI providers and run governed E2E verification."),
        ReadinessGate("restricted_party_screening", screening_ok, True, "Authoritative sanctions screening connector", "Configure/restore authoritative screening connectivity."),
        ReadinessGate("tariff_classification", tariff_ok, True, "Authoritative tariff/classification connector", "Configure a corridor-appropriate tariff/classification provider."),
        ReadinessGate("logistics_provider", logistics_connector_ok and _true("CARRIER_E2E_VERIFIED"), True, "Production logistics provider plus carrier E2E", "Connect and verify a production logistics provider."),
        ReadinessGate("fx_execution_provider", settlement_ok, True, settlement_evidence, "Keep USD-only settlement or configure an executable FX provider before allowing non-USD settlement."),
        ReadinessGate("secure_document_storage", storage_configured and _true("SIGNED_DOCUMENT_STORAGE_VERIFIED"), True, f"Canonical storage provider={storage.get('provider')}; bucket={storage.get('bucket')}; signed verification={_true('SIGNED_DOCUMENT_STORAGE_VERIFIED')}", "Verify Supabase Storage signed upload/download, malware gate, retention and legal-hold workflow."),
        ReadinessGate("global_translation", translation_ok, True, "Azure translation plus multilingual E2E", "Configure Azure Translator and complete multilingual E2E."),
        ReadinessGate("country_activation_governance", bool(country_evidence.get("verified")), True, str(country_evidence.get("reason") or "Country/corridor governance verified"), "Maintain current evidence and owner approval for every live corridor."),
        ReadinessGate("global_supplier_sourcing", bool(sourcing_evidence.get("verified")), True, str(sourcing_evidence.get("reason") or "Supplier sourcing evidence verified"), "Complete a supplier workflow with current quote and all sourcing controls."),
        ReadinessGate("managed_trade_gateway", bool(managed_evidence.get("verified")), True, str(managed_evidence.get("reason") or "Managed-trade state machine verified"), "Complete a fully governed managed-trade lifecycle."),
        ReadinessGate("intermediary_mode", _true("INTERMEDIARY_MODE_E2E_VERIFIED"), True, "Intermediary mode E2E", "Run intermediary E2E tests."),
        ReadinessGate("business_operational_controls", _true("BUSINESS_OPERATIONAL_READINESS_E2E_VERIFIED"), True, "Business operational controls E2E", "Verify partners, agreements, KYB, product dossiers and incidents."),
        ReadinessGate("cuba_private_business_eligibility", _true("CUBA_PRIVATE_BUSINESS_E2E_VERIFIED"), True, "Cuba private-business eligibility E2E", "Prove ineligible businesses cannot pass."),
        ReadinessGate("cuba_authorized_trade_desk", _true("CUBA_AUTHORIZED_TRADE_E2E_VERIFIED"), True, "Cuba authorized-trade E2E", "Run a production-safe authorized-trade test."),
        ReadinessGate("collaboration_isolation", _true("COLLABORATION_E2E_VERIFIED"), True, "External sharing isolation E2E", "Run sharing isolation, expiry and revocation tests."),
        ReadinessGate("accounting_ledger", _true("ACCOUNTING_LEDGER_VERIFIED") and _true("PAYMENT_RECONCILIATION_VERIFIED"), True, "Double-entry ledger and reconciliation E2E", "Post balanced/reversal journals and reconcile payments."),
        ReadinessGate("beneficiary_maker_checker", _true("BENEFICIARY_MAKER_CHECKER_VERIFIED"), True, "Beneficiary maker-checker E2E", "Verify independent beneficiary validation plus owner approval."),
        ReadinessGate("audit_retention", max(_int("AUDIT_RETENTION_DAYS"), AUDIT_RETENTION_DAYS) >= 365, True, f"Audit retention={max(_int('AUDIT_RETENTION_DAYS'), AUDIT_RETENTION_DAYS)} days", "Keep audit retention at 365 days or longer."),
        ReadinessGate("backup_policy", _true("BACKUPS_ENABLED") and _true("BACKUP_RESTORE_TESTED"), True, "Supabase database/storage backup and restore drill", "Run and document a Supabase restore drill."),
        ReadinessGate("monitoring_alerts", _present("ALERT_WEBHOOK_URL") or _true("VERCEL_MONITORING_ENABLED"), True, "Production alert path", "Configure runtime monitoring/alerts."),
        ReadinessGate("first_live_trade_certified", _true("FIRST_LIVE_TRADE_CERTIFIED"), True, "Real trade certification", "Complete and owner-certify the first real delivered/reconciled trade."),
        ReadinessGate("e2e_trade_workflow", bool(e2e_ok), True, "End-to-end trade workflow", "Run a production-safe supplier-to-profit E2E workflow."),
    ]

    passed = sum(1 for gate in gates if gate.passed)
    blockers = [gate.name for gate in gates if not gate.passed]
    return {
        "score": round(passed / len(gates) * 100),
        "passed_gates": passed,
        "total_gates": len(gates),
        "blocker_count": len(blockers),
        "production_ready": not blockers,
        "release_gate": "READY" if not blockers else "HOLD",
        "identity_provider": "supabase_auth",
        "canonical_backend": "supabase",
        "canonical_storage": "supabase_storage",
        "canonical_transaction_currency": CANONICAL_TRANSACTION_CURRENCY,
        "usd_only_transactions": USD_ONLY_TRANSACTIONS,
        "persistence_schema_evidence": schema,
        "country_governance_evidence": country_evidence,
        "supplier_sourcing_evidence": sourcing_evidence,
        "managed_trade_gateway_evidence": managed_evidence,
        "gates": [asdict(gate) for gate in gates],
        "blockers": blockers,
    }
