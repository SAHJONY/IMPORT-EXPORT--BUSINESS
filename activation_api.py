from __future__ import annotations

import hashlib
import os

from fastapi import FastAPI, Header, HTTPException, Request

from energy_crm_seed import ENERGY_CRM_LEADS, ensure_energy_crm_seed
from global_energy_crm_seed import GLOBAL_ENERGY_CRM_LEADS, ensure_global_energy_crm_seed
from worldwide_trade_counterparty_seed import WORLDWIDE_TRADE_COUNTERPARTIES, ensure_worldwide_trade_counterparty_seed
from midmarket_oil_dependent_crm_seed import MIDMARKET_OIL_DEPENDENT_LEADS, ensure_midmarket_oil_dependent_seed
from cuba_mipyme_expansion_seed import CUBA_MIPYME_EXPANSION_LEADS, ensure_cuba_mipyme_expansion_seed
from insforge_backend import persistent_backend_status
from payment_engine import CANONICAL_TRANSACTION_CURRENCY, USD_ONLY_TRANSACTIONS
from production_readiness import evaluate_production_readiness
from production_schema_evidence import production_schema_evidence
from secure_storage import storage_configuration_status
from trade_connectors import trade_connectors

app = FastAPI(title="SAHJONY Supabase Production Activation Control", version="2.0.0", docs_url=None, redoc_url=None)


def _present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _true(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _supabase_configured() -> bool:
    return _present("SUPABASE_URL") and (_present("SUPABASE_SERVICE_ROLE_KEY") or _present("SUPABASE_SECRET_KEY") or _present("SUPABASE_KEY"))


def _provider_state(schema_evidence: dict | None = None) -> dict:
    persistence = persistent_backend_status()
    schema = schema_evidence or {}
    storage = storage_configuration_status()
    return {
        "identity": {
            "provider": "supabase_auth",
            "configured": _supabase_configured(),
            "legacy_local_auth_disabled": not _true("ALLOW_LEGACY_LOCAL_AUTH"),
            "membership_authorization": True,
            "owner_mfa_required": _true("OWNER_MFA_REQUIRED"),
        },
        "persistence": {
            **persistence,
            "canonical_database": "supabase",
            "rls_verified": bool(schema.get("rls_verified")),
            "schemas_applied": bool(schema.get("verified")),
            "runtime_schema_evidence": schema,
        },
        "document_storage": {
            **storage,
            "canonical_storage": "supabase_storage",
            "signed_storage_verified": _true("SIGNED_DOCUMENT_STORAGE_VERIFIED"),
            "malware_scan_required": os.getenv("DOCUMENT_MALWARE_SCAN_REQUIRED", "true").strip().lower() == "true",
            "malware_scan_callback_configured": _present("MALWARE_SCAN_CALLBACK_SECRET"),
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
        "monitoring": {
            "vercel_monitoring_enabled": _true("VERCEL_MONITORING_ENABLED"),
            "alert_webhook_configured": _present("ALERT_WEBHOOK_URL"),
        },
    }


def _external_requirements(schema_evidence: dict | None = None) -> list[dict]:
    requirements: list[dict] = []
    persistence = persistent_backend_status()
    storage = storage_configuration_status()
    schema = schema_evidence or {}
    if not persistence.get("supabase_configured"):
        requirements.append({"area": "supabase", "action": "Configure SUPABASE_URL plus a server-side Supabase secret/service-role key."})
    if not schema.get("verified"):
        requirements.append({"area": "supabase_schema", "action": "Apply and verify the canonical Supabase schema/RLS/storage foundation."})
    if not storage.get("configured"):
        requirements.append({"area": "document_storage", "action": "Configure Supabase Storage and the private trade-documents bucket."})
    if int(schema.get("auth_user_count") or 0) == 0:
        requirements.append({"area": "identity", "action": "Create the first real Supabase Auth user, then explicitly promote authorized owner/employee memberships."})
    if not _present("ANTHROPIC_API_KEY"):
        requirements.append({"area": "ai", "action": "Configure Anthropic and run governed AI Brain E2E verification."})
    if not (_present("AZURE_TRANSLATOR_ENDPOINT") and _present("AZURE_TRANSLATOR_KEY")):
        requirements.append({"area": "translation", "action": "Configure Azure Translator and run multilingual E2E verification."})
    if not _present("LOGISTICS_DATA_PROVIDER") and not _present("MAERSK_CLIENT_ID"):
        requirements.append({"area": "logistics", "action": "Connect and verify a production logistics provider."})
    if not _true("BACKUP_RESTORE_TESTED"):
        requirements.append({"area": "resilience", "action": "Complete and document a Supabase database/storage restore drill."})
    if not _true("FIRST_LIVE_TRADE_CERTIFIED"):
        requirements.append({"area": "live_business", "action": "Complete one real delivered, reconciled and owner-certified trade before release status becomes READY."})
    return requirements


def _seed_failure(expected: int, exc: Exception) -> dict:
    reason = str(exc).strip().splitlines()[0][:240] if str(exc).strip() else "unknown CRM seed error"
    return {"status": "failed", "expected": expected, "inserted": 0, "already_present": 0, "failed": expected, "reason": f"{type(exc).__name__}: {reason}", "automatic_deal_promotion": False, "automatic_outreach_authority": False}


def _prepared_crm_prospects() -> list[dict]:
    books = (
        ("energy_core", ENERGY_CRM_LEADS),
        ("global_energy", GLOBAL_ENERGY_CRM_LEADS),
        ("worldwide_trade", WORLDWIDE_TRADE_COUNTERPARTIES),
        ("midmarket_oil_dependent", MIDMARKET_OIL_DEPENDENT_LEADS),
        ("cuba_mipyme_expansion", CUBA_MIPYME_EXPANSION_LEADS),
    )
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for book_name, leads in books:
        for lead in leads:
            business = str(lead.get("business_name") or lead.get("legal_name") or "Unnamed prospect").strip()
            country = str(lead.get("country") or lead.get("country_code") or "UN").strip().upper()[:3]
            dedupe = (business.lower(), country)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            digest = hashlib.sha256(f"{business}|{country}|{book_name}".encode()).hexdigest()[:18]
            rows.append({
                "intake_id": f"prepared:{digest}",
                "customer_id": f"prepared:{digest}",
                "legal_name": business,
                "trade_name": business,
                "contact_name": lead.get("contact_name"),
                "email": lead.get("email"),
                "phone": lead.get("phone"),
                "country_code": country,
                "website": lead.get("website") or lead.get("source_url"),
                "product_need": lead.get("product_need_or_offer") or lead.get("product") or "Commercial prospect — qualification required",
                "destination_country": country,
                "status": "RESEARCH_PROSPECT",
                "qualification_status": "PENDING",
                "source": book_name,
                "source_description": lead.get("source_description") or lead.get("evidence_summary"),
                "source_url": lead.get("source_url") or lead.get("source_reference"),
                "deal_side": lead.get("deal_side") or lead.get("lead_type"),
                "notes": lead.get("notes"),
                "prospect_only": True,
                "prepared_record": True,
                "persisted": False,
                "read_only": True,
            })
    return rows


@app.get("/crm/intakes")
async def resilient_crm_intakes(x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    try:
        from customer_crm_api import list_intakes as live_list_intakes
        return await live_list_intakes(x_role=x_role, authorization=authorization, x_employee_id=x_employee_id)
    except HTTPException:
        raise
    except Exception as exc:
        rows = _prepared_crm_prospects()
        return {"intakes": rows[:250], "real_intake_count": 0, "prospect_count": len(rows), "status": "DEGRADED_READ_ONLY", "persisted_records_available": False, "prepared_records_visible": True, "database_write_enabled": False, "database_issue": "SUPABASE_TEMPORARILY_UNAVAILABLE", "error_type": type(exc).__name__, "message": "Prepared CRM prospects remain visible read-only while Supabase persistence is unavailable."}


@app.post("/crm/intake")
async def resilient_public_crm_intake(request: Request):
    try:
        from customer_crm_api import IntakeIn, public_intake
        return await public_intake(IntakeIn.model_validate(await request.json()))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "SUPABASE_TEMPORARILY_UNAVAILABLE", "message": "New CRM intake writes are temporarily unavailable until Supabase persistence recovers.", "fail_closed": True, "error_type": type(exc).__name__})


@app.get("/activation/health")
async def activation_health():
    schema_evidence = await production_schema_evidence()
    crm_seeds: dict[str, dict] = {}
    # Seeding is safe only when Supabase is configured. Individual seed modules may
    # still use SQL-specific paths; failures are evidence, never fabricated success.
    if persistent_backend_status().get("supabase_configured"):
        for name, expected, runner in (
            ("energy_core", len(ENERGY_CRM_LEADS), ensure_energy_crm_seed),
            ("global_energy", len(GLOBAL_ENERGY_CRM_LEADS), ensure_global_energy_crm_seed),
            ("worldwide_trade", len(WORLDWIDE_TRADE_COUNTERPARTIES), ensure_worldwide_trade_counterparty_seed),
            ("midmarket_oil_dependent", len(MIDMARKET_OIL_DEPENDENT_LEADS), ensure_midmarket_oil_dependent_seed),
            ("cuba_mipyme_expansion", len(CUBA_MIPYME_EXPANSION_LEADS), ensure_cuba_mipyme_expansion_seed),
        ):
            try:
                crm_seeds[name] = await runner()
            except Exception as exc:
                crm_seeds[name] = _seed_failure(expected, exc)

    connector_health = await trade_connectors.health()
    readiness = evaluate_production_readiness(runtime_ok=True, connector_health=connector_health, persistence_schema_evidence=schema_evidence)
    providers = _provider_state(schema_evidence)
    external = _external_requirements(schema_evidence)
    persistence_ready = bool(providers["persistence"].get("supabase_configured") and providers["persistence"].get("schemas_applied") and providers["persistence"].get("rls_verified"))
    seed_expected = sum(int(v.get("expected") or 0) for v in crm_seeds.values())
    seed_inserted = sum(int(v.get("inserted") or 0) for v in crm_seeds.values())
    seed_present = sum(int(v.get("already_present") or 0) for v in crm_seeds.values())
    seed_failed = sum(int(v.get("failed") or 0) for v in crm_seeds.values())

    return {
        "status": "ready" if readiness["production_ready"] else "activation_required",
        "service": "production-activation-control",
        "business": "SAHJONY Global Trade",
        "canonical_platform": "supabase",
        "canonical_database": "supabase",
        "canonical_identity": "supabase_auth",
        "canonical_storage": "supabase_storage",
        "schema_evidence": schema_evidence,
        "crm_seeds": {"books": crm_seeds, "expected": seed_expected, "inserted_this_run": seed_inserted, "already_present": seed_present, "failed": seed_failed, "buyer_seller_worldwide": True, "automatic_deal_promotion": False},
        "readiness_score": readiness["score"],
        "passed_gates": readiness["passed_gates"],
        "total_gates": readiness["total_gates"],
        "blocker_count": readiness["blocker_count"],
        "release_gate": readiness["release_gate"],
        "production_ready": readiness["production_ready"],
        "application_data_plane_ready": persistence_ready,
        "safe_to_accept_persisted_trade_requests": persistence_ready,
        "safe_to_release_transactions": readiness["production_ready"],
        "providers": providers,
        "connectors": connector_health,
        "blockers": readiness["blockers"],
        "external_actions_required": external,
        "policy": {"fail_closed": True, "no_fake_100_percent": True, "first_live_trade_required": True, "canonical_transaction_currency": CANONICAL_TRANSACTION_CURRENCY, "usd_only_transactions": USD_ONLY_TRANSACTIONS, "ai_has_release_authority": False},
    }
