from __future__ import annotations

import os
from fastapi import FastAPI

from auth import neon_auth_jwks_url, neon_auth_url
from energy_crm_seed import ensure_energy_crm_seed
from insforge_backend import persistent_backend_status
from payment_engine import CANONICAL_TRANSACTION_CURRENCY, USD_ONLY_TRANSACTIONS
from production_readiness import evaluate_production_readiness
from production_schema_bootstrap import ensure_production_schema
from production_schema_evidence import production_schema_evidence
from secure_storage import storage_configuration_status
from trade_connectors import trade_connectors

app = FastAPI(title="SAHJONY Production Activation Control", version="1.5.1", docs_url=None, redoc_url=None)


_DATABASE_ENV_ORDER = (
    "DATABASE_URL",
    "POSTGRES_URL",
    "NEON_DATABASE_URL",
    "NEON_POSTGRES_URL",
    "POSTGRES_PRISMA_URL",
)


def _present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _true(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _database_env_diagnostics() -> dict:
    present = [name for name in _DATABASE_ENV_ORDER if _present(name)]
    selected = present[0] if present else None
    return {
        "selected_variable": selected,
        "present_variables": present,
        "multiple_database_variables_present": len(present) > 1,
        "values_exposed": False,
        "canonical_policy": "Use the active Vercel production database; do not substitute databases from other applications.",
    }


def _provider_state(schema_evidence: dict | None = None) -> dict:
    persistence = persistent_backend_status()
    schema_verified = bool((schema_evidence or {}).get("verified"))
    storage = storage_configuration_status()
    return {
        "identity": {
            "provider": "neon_auth",
            "auth_url_configured": bool(neon_auth_url()),
            "jwks_url_configured": bool(neon_auth_jwks_url()),
            "legacy_local_auth_disabled": not _true("ALLOW_LEGACY_LOCAL_AUTH"),
        },
        "persistence": {
            **persistence,
            "canonical_database": "active_vercel_database_url",
            "database_env_diagnostics": _database_env_diagnostics(),
            "rls_verified": _true("PERSISTENCE_ISOLATION_VERIFIED") or _true("INSFORGE_RLS_VERIFIED"),
            "schemas_applied": schema_verified or _true("PERSISTENCE_SCHEMA_VERIFIED") or _true("INSFORGE_SCHEMAS_APPLIED"),
            "runtime_schema_evidence": schema_evidence,
        },
        "payments": {
            "canonical_transaction_currency": CANONICAL_TRANSACTION_CURRENCY,
            "usd_only_transactions": USD_ONLY_TRANSACTIONS,
            "fx_execution_required_for_customer_settlement": not USD_ONLY_TRANSACTIONS,
        },
        "ai": {
            "openai_configured": _present("OPENAI_API_KEY"),
            "anthropic_configured": _present("ANTHROPIC_API_KEY"),
            "e2e_verified": _true("AI_BRAIN_E2E_VERIFIED"),
            "release_authority": False,
        },
        "translation": {
            "provider": "azure-translator",
            "configured": _present("AZURE_TRANSLATOR_ENDPOINT") and _present("AZURE_TRANSLATOR_KEY"),
            "e2e_verified": _true("MULTILINGUAL_E2E_VERIFIED"),
        },
        "document_storage": {
            **storage,
            "signed_storage_verified": _true("SIGNED_DOCUMENT_STORAGE_VERIFIED"),
            "malware_scan_required": os.getenv("DOCUMENT_MALWARE_SCAN_REQUIRED", "true").strip().lower() == "true",
            "malware_scan_callback_configured": _present("MALWARE_SCAN_CALLBACK_SECRET"),
        },
        "monitoring": {
            "vercel_monitoring_enabled": _true("VERCEL_MONITORING_ENABLED"),
            "alert_webhook_configured": _present("ALERT_WEBHOOK_URL"),
        },
    }


def _external_requirements() -> list[dict]:
    requirements: list[dict] = []
    persistence = persistent_backend_status()
    storage = storage_configuration_status()
    if not persistence["configured"]:
        requirements.append({"area": "persistence", "action": "Attach the canonical production database to Vercel so DATABASE_URL/POSTGRES_URL exists."})
    if not storage["configured"]:
        requirements.append({"area": "document_storage", "action": "Configure one supported S3-compatible production storage profile (InsForge S3, Cloudflare R2, or generic S3-compatible) and verify signed upload/download plus malware quarantine."})
    if not _present("ANTHROPIC_API_KEY"):
        requirements.append({"area": "ai", "action": "Add ANTHROPIC_API_KEY in Vercel and run AI Brain E2E verification for governed dual-model high-stakes consensus."})
    if not (_present("AZURE_TRANSLATOR_ENDPOINT") and _present("AZURE_TRANSLATOR_KEY")):
        requirements.append({"area": "translation", "action": "Add Azure Translator endpoint/key/region and run multilingual E2E verification for server-side document/message translation."})
    if not _present("LOGISTICS_DATA_PROVIDER") and not _present("MAERSK_CLIENT_ID"):
        requirements.append({"area": "logistics", "action": "Connect an approved production carrier/freight tracking account and verify E2E milestones."})
    if not USD_ONLY_TRANSACTIONS and not (_present("FX_EXECUTION_PROVIDER") or _present("FX_DATA_PROVIDER")):
        requirements.append({"area": "settlement", "action": "Connect the production bank/settlement FX provider before enabling non-USD customer settlement."})
    if not _true("BACKUP_RESTORE_TESTED"):
        requirements.append({"area": "resilience", "action": "Complete and record a database/storage restore drill on the canonical Vercel production database."})
    if not _true("FIRST_LIVE_TRADE_CERTIFIED"):
        requirements.append({"area": "live_business", "action": "Complete one real customer-to-supplier transaction, delivery, reconciliation, fee collection and Owner certification."})
    return requirements


@app.get("/activation/health")
async def activation_health():
    bootstrap = None
    energy_crm_seed = None
    if os.getenv("VERCEL_ENV", "").strip().lower() == "production" and persistent_backend_status()["database_url_configured"]:
        try:
            bootstrap = await ensure_production_schema()
        except Exception as exc:
            bootstrap = {
                "completed": False,
                "canonical_database": "active_vercel_database_url",
                "reason": f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:240] if str(exc).strip() else 'unknown bootstrap error'}",
                "fail_closed": True,
            }
        try:
            energy_crm_seed = await ensure_energy_crm_seed()
        except Exception as exc:
            energy_crm_seed = {
                "status": "failed",
                "expected": 21,
                "inserted": 0,
                "already_present": 0,
                "failed": 21,
                "reason": f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:240] if str(exc).strip() else 'unknown CRM seed error'}",
                "automatic_deal_promotion": False,
                "automatic_outreach_authority": False,
            }

    connector_health = await trade_connectors.health()
    schema_evidence = await production_schema_evidence()
    readiness = evaluate_production_readiness(
        runtime_ok=True,
        connector_health=connector_health,
        persistence_schema_evidence=schema_evidence,
    )
    providers = _provider_state(schema_evidence)
    external = _external_requirements()
    persistence_ready = providers["persistence"]["configured"] and providers["persistence"]["schemas_applied"]
    return {
        "status": "ready" if readiness["production_ready"] else "activation_required",
        "service": "production-activation-control",
        "business": "SAHJONY Global Trade",
        "canonical_database": "active_vercel_database_url",
        "schema_bootstrap": bootstrap,
        "energy_crm_seed": energy_crm_seed,
        "readiness_score": readiness["score"],
        "passed_gates": readiness["passed_gates"],
        "total_gates": readiness["total_gates"],
        "blocker_count": readiness["blocker_count"],
        "release_gate": readiness["release_gate"],
        "production_ready": readiness["production_ready"],
        "safe_to_accept_persisted_trade_requests": persistence_ready,
        "safe_to_release_transactions": readiness["production_ready"],
        "providers": providers,
        "connectors": connector_health,
        "blockers": readiness["blockers"],
        "external_actions_required": external,
        "policy": {
            "fail_closed": True,
            "no_fake_100_percent": True,
            "first_live_trade_required": True,
            "canonical_transaction_currency": CANONICAL_TRANSACTION_CURRENCY,
            "usd_only_transactions": USD_ONLY_TRANSACTIONS,
            "ai_has_release_authority": False,
        },
    }