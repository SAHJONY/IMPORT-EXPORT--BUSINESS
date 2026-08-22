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


def evaluate_production_readiness(*, runtime_ok: bool = True, e2e_ok: bool | None = None) -> dict[str, Any]:
    """Return a fail-closed production readiness assessment.

    Production readiness is never inferred from code presence alone. Every critical
    external dependency must be explicitly configured and, where possible, verified.
    """
    auth_provider = os.getenv("AUTH_PROVIDER", "").strip().lower()
    if e2e_ok is None:
        e2e_ok = _true("E2E_TRADE_WORKFLOW_VERIFIED")

    gates = [
        ReadinessGate("production_runtime", runtime_ok, True, "HTTP runtime health", "Deploy a healthy production revision."),
        ReadinessGate("insforge_backend", _present("INSFORGE_BASE_URL") and _present("INSFORGE_API_KEY"), True, "InsForge server credentials present", "Configure InsForge production project credentials."),
        ReadinessGate("insforge_auth", auth_provider == "insforge" and _present("INSFORGE_ANON_KEY"), True, "AUTH_PROVIDER=insforge and public key present", "Enable InsForge Auth/JWT + RLS for user-facing access."),
        ReadinessGate("owner_mfa", _true("OWNER_MFA_REQUIRED"), True, "Owner MFA policy enabled", "Require MFA for owner/admin access."),
        ReadinessGate("restricted_party_screening", _present("TRADE_GOV_API_KEY") or _true("OFAC_DIRECT_SCREENING"), True, "Government screening connector configured", "Configure Trade.gov CSL API or verified OFAC direct screening."),
        ReadinessGate("tariff_classification", _present("TARIFF_DATA_PROVIDER"), True, "Tariff/classification provider configured", "Configure authoritative tariff/HTS data provider."),
        ReadinessGate("logistics_provider", _present("LOGISTICS_DATA_PROVIDER"), True, "Logistics provider configured", "Configure live freight/tracking provider."),
        ReadinessGate("fx_provider", _present("FX_DATA_PROVIDER"), True, "FX provider configured", "Configure authoritative FX provider."),
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
