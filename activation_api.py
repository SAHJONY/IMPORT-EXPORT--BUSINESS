from __future__ import annotations

import os
from fastapi import FastAPI

from auth import neon_auth_jwks_url, neon_auth_url
from insforge_backend import persistent_backend_status
from payment_engine import CANONICAL_TRANSACTION_CURRENCY, USD_ONLY_TRANSACTIONS
from production_readiness import evaluate_production_readiness
from trade_connectors import trade_connectors

app = FastAPI(title="SAHJONY Production Activation Control", version="1.2.0", docs_url=None, redoc_url=None)


def _present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _true(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _provider_state() -> dict:
    persistence = persistent_backend_status()
    return {
        "identity": {
            "provider": "neon_auth",
            "auth_url_configured": bool(neon_auth_url()),
            "jwks_url_configured": bool(neon_auth_jwks_url()),
            "legacy_local_auth_disabled": not _true("ALLOW_LEGACY_LOCAL_AUTH"),
        },
        "persistence": {
            **persistence,
            "rls_verified": _true("PERSISTENCE_ISOLATION_VERIFIED") or _true("INSFORGE_RLS_VERIFIED"),
            "schemas_applied": _true("PERSISTENCE_SCHEMA_VERIFIED") or _true("INSFORGE_SCHEMAS_APPLIED"),
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
            "provider": "insforge-s3-or-compatible",
            "configured": all(_present(k) for k in (
                "INSFORGE_S3_ENDPOINT", "INSFORGE_S3_ACCESS_KEY_ID", "INSFORGE_S3_SECRET_ACCESS_KEY", "INSFORGE_STORAGE_BUCKET",
            )),
            "signed_storage_verified": _true("SIGNED_DOCUMENT_STORAGE_VERIFIED"),
        },
        "monitoring": {
            "vercel_monitoring_enabled": _true("VERCEL_MONITORING_ENABLED"),
            "alert_webhook_configured": _present("ALERT_WEBHOOK_URL"),
        },
    }


def _external_requirements() -> list[dict]:
    requirements: list[dict] = []
    persistence = persistent_backend_status()
    if not persistence["configured"]:
        requirements.append({"area": "persistence", "action": "Attach Neon/Postgres to Vercel so DATABASE_URL/POSTGRES_URL exists, or configure InsForge server credentials."})
    if not _present("ANTHROPIC_API_KEY"):
        requirements.append({"area": "ai", "action": "Add ANTHROPIC_API_KEY in Vercel and run AI Brain E2E verification for governed dual-model high-stakes consensus."})
    if not (_present("AZURE_TRANSLATOR_ENDPOINT") and _present("AZURE_TRANSLATOR_KEY")):
        requirements.append({"area": "translation", "action": "Add Azure Translator endpoint/key/region and run multilingual E2E verification for server-side document/message translation."})
    # USITC tariff research is built in and health-checked dynamically; no duplicate
    # environment variable is required merely to declare the provider.
    if not _present("LOGISTICS_DATA_PROVIDER") and not _present("MAERSK_CLIENT_ID"):
        requirements.append({"area": "logistics", "action": "Connect an approved production carrier/freight tracking account and verify E2E milestones."})
    # Customer settlement is USD-only. Do not require an FX execution account unless
    # product policy is deliberately changed to allow non-USD settlement.
    if not USD_ONLY_TRANSACTIONS and not (_present("FX_EXECUTION_PROVIDER") or _present("FX_DATA_PROVIDER")):
        requirements.append({"area": "settlement", "action": "Connect the production bank/settlement FX provider before enabling non-USD customer settlement."})
    if not _true("BACKUP_RESTORE_TESTED"):
        requirements.append({"area": "resilience", "action": "Complete and record a database/storage restore drill."})
    if not _true("FIRST_LIVE_TRADE_CERTIFIED"):
        requirements.append({"area": "live_business", "action": "Complete one real customer-to-supplier transaction, delivery, reconciliation, fee collection and Owner certification."})
    return requirements


@app.get("/activation/health")
async def activation_health():
    connector_health = await trade_connectors.health()
    readiness = evaluate_production_readiness(runtime_ok=True, connector_health=connector_health)
    providers = _provider_state()
    external = _external_requirements()
    persistence_ready = providers["persistence"]["configured"]
    return {
        "status": "ready" if readiness["production_ready"] else "activation_required",
        "service": "production-activation-control",
        "business": "SAHJONY Global Trade",
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
