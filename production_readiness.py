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
    """Return a fail-closed production readiness assessment.

    With live connector health, external-data gates require configured+reachable.
    Without live health (for startup/tests), configuration-only fallback is preserved;
    production endpoints should pass connector_health whenever they need an operational
    release assessment.
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

    gates = [
        ReadinessGate("production_runtime", runtime_ok, True, "HTTP runtime health", "Deploy a healthy production revision."),
        ReadinessGate("insforge_backend", _present("INSFORGE_BASE_URL") and _present("INSFORGE_API_KEY"), True, "InsForge server credentials present", "Configure InsForge production project credentials."),
        ReadinessGate("insforge_auth", auth_provider == "insforge" and _present("INSFORGE_ANON_KEY"), True, "AUTH_PROVIDER=insforge and public key present", "Enable InsForge Auth/JWT + RLS for user-facing access."),
        ReadinessGate("owner_mfa", _true("OWNER_MFA_REQUIRED"), True, "Owner MFA policy enabled", "Require MFA for owner/admin access."),
        ReadinessGate("restricted_party_screening", screening_ok, True, screening_evidence, "Restore/configure authoritative sanctions screening connectivity."),
        ReadinessGate("tariff_classification", tariff_ok, True, tariff_evidence, "Configure authoritative tariff/HTS data provider; ITA FTA Tariff API is supported with an API key."),
        ReadinessGate("logistics_provider", logistics_ok, True, logistics_evidence, "Configure live freight/tracking provider."),
        ReadinessGate("fx_execution_provider", fx_ok, True, fx_evidence, "Configure bank/settlement FX provider. ECB/Fed reference feeds are planning inputs only."),
        ReadinessGate("durable_documents", _true("INSFORGE_STORAGE_ENABLED"), True, "InsForge Storage enabled", "Enable production document storage and retention policies."),
        ReadinessGate("audit_retention", _int("AUDIT_RETENTION_DAYS") >= 365, True, "Audit retention >=365 days", "Set auditable retention to at least 365 days."),
        ReadinessGate("backup_policy", _true("BACKUPS_ENABLED"), True, "Backups enabled", "Enable scheduled database/storage backups and restore testing."),
        ReadinessGate("monitoring_alerts", _present("ALERT_WEBHOOK_URL") or _true("VERCEL_MONITORING_ENABLED"), True, "Production alert path configured", "Configure runtime alerting and incident notifications."),
        ReadinessGate("e2e_trade_workflow", bool(e2e_ok), True, "Verified end-to-end trade workflow", "Run and record a production-safe E2E workflow before accepting live business."),
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
