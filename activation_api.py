from __future__ import annotations

import hashlib
import os
from fastapi import FastAPI, Header, HTTPException, Request
from postgres_runtime import install_neon_ipv4_preference

install_neon_ipv4_preference()

from auth import neon_auth_jwks_url, neon_auth_url
from energy_crm_seed import ENERGY_CRM_LEADS, ensure_energy_crm_seed
from global_energy_crm_seed import GLOBAL_ENERGY_CRM_LEADS, ensure_global_energy_crm_seed
from worldwide_trade_counterparty_seed import WORLDWIDE_TRADE_COUNTERPARTIES, ensure_worldwide_trade_counterparty_seed
from midmarket_oil_dependent_crm_seed import MIDMARKET_OIL_DEPENDENT_LEADS, ensure_midmarket_oil_dependent_seed
from cuba_mipyme_expansion_seed import CUBA_MIPYME_EXPANSION_LEADS, ensure_cuba_mipyme_expansion_seed
from insforge_backend import persistent_backend_status
from payment_engine import CANONICAL_TRANSACTION_CURRENCY, USD_ONLY_TRANSACTIONS
from production_readiness import evaluate_production_readiness
from production_schema_bootstrap import ensure_production_schema
from production_schema_evidence import production_schema_evidence
from secure_storage import storage_configuration_status
from trade_connectors import trade_connectors

app = FastAPI(title="SAHJONY Production Activation Control", version="1.8.0", docs_url=None, redoc_url=None)

_DATABASE_ENV_ORDER=("DATABASE_URL","POSTGRES_URL","NEON_DATABASE_URL","NEON_POSTGRES_URL","POSTGRES_PRISMA_URL")

def _present(name:str)->bool: return bool(os.getenv(name,"").strip())
def _true(name:str)->bool: return os.getenv(name,"false").strip().lower()=="true"

def _database_env_diagnostics()->dict:
    present=[name for name in _DATABASE_ENV_ORDER if _present(name)]; selected=present[0] if present else None
    return {"selected_variable":selected,"present_variables":present,"multiple_database_variables_present":len(present)>1,"values_exposed":False,"canonical_policy":"Use the active Vercel production database; do not substitute databases from other applications."}

def _provider_state(schema_evidence:dict|None=None)->dict:
    persistence=persistent_backend_status(); schema_verified=bool((schema_evidence or {}).get("verified")); storage=storage_configuration_status()
    return {
        "identity":{"provider":"neon_auth","auth_url_configured":bool(neon_auth_url()),"jwks_url_configured":bool(neon_auth_jwks_url()),"legacy_local_auth_disabled":not _true("ALLOW_LEGACY_LOCAL_AUTH")},
        "persistence":{**persistence,"canonical_database":"active_vercel_database_url","database_env_diagnostics":_database_env_diagnostics(),"rls_verified":_true("PERSISTENCE_ISOLATION_VERIFIED") or _true("INSFORGE_RLS_VERIFIED"),"schemas_applied":schema_verified or _true("PERSISTENCE_SCHEMA_VERIFIED") or _true("INSFORGE_SCHEMAS_APPLIED"),"runtime_schema_evidence":schema_evidence},
        "payments":{"canonical_transaction_currency":CANONICAL_TRANSACTION_CURRENCY,"usd_only_transactions":USD_ONLY_TRANSACTIONS,"fx_execution_required_for_customer_settlement":not USD_ONLY_TRANSACTIONS},
        "ai":{"openai_configured":_present("OPENAI_API_KEY"),"anthropic_configured":_present("ANTHROPIC_API_KEY"),"e2e_verified":_true("AI_BRAIN_E2E_VERIFIED"),"release_authority":False},
        "translation":{"provider":"azure-translator","configured":_present("AZURE_TRANSLATOR_ENDPOINT") and _present("AZURE_TRANSLATOR_KEY"),"e2e_verified":_true("MULTILINGUAL_E2E_VERIFIED")},
        "document_storage":{**storage,"signed_storage_verified":_true("SIGNED_DOCUMENT_STORAGE_VERIFIED"),"malware_scan_required":os.getenv("DOCUMENT_MALWARE_SCAN_REQUIRED","true").strip().lower()=="true","malware_scan_callback_configured":_present("MALWARE_SCAN_CALLBACK_SECRET")},
        "monitoring":{"vercel_monitoring_enabled":_true("VERCEL_MONITORING_ENABLED"),"alert_webhook_configured":_present("ALERT_WEBHOOK_URL")},
    }

def _external_requirements()->list[dict]:
    requirements=[]; persistence=persistent_backend_status(); storage=storage_configuration_status()
    if not persistence["configured"]: requirements.append({"area":"persistence","action":"Attach the canonical production database to Vercel so DATABASE_URL/POSTGRES_URL exists."})
    if not storage["configured"]: requirements.append({"area":"document_storage","action":"Configure one supported S3-compatible production storage profile and verify signed upload/download plus malware quarantine."})
    if not _present("ANTHROPIC_API_KEY"): requirements.append({"area":"ai","action":"Add ANTHROPIC_API_KEY in Vercel and run governed AI Brain E2E verification."})
    if not (_present("AZURE_TRANSLATOR_ENDPOINT") and _present("AZURE_TRANSLATOR_KEY")): requirements.append({"area":"translation","action":"Configure Azure Translator and run multilingual E2E verification."})
    if not _present("LOGISTICS_DATA_PROVIDER") and not _present("MAERSK_CLIENT_ID"): requirements.append({"area":"logistics","action":"Connect an approved production carrier/freight tracking account and verify E2E milestones."})
    if not _true("BACKUP_RESTORE_TESTED"): requirements.append({"area":"resilience","action":"Complete and record a database/storage restore drill on the canonical Vercel production database."})
    if not _true("FIRST_LIVE_TRADE_CERTIFIED"): requirements.append({"area":"live_business","action":"Complete one real customer-to-supplier transaction, delivery, reconciliation, fee collection and Owner certification."})
    return requirements

def _seed_failure(expected:int, exc:Exception)->dict:
    reason=str(exc).strip().splitlines()[0][:240] if str(exc).strip() else "unknown CRM seed error"
    return {"status":"failed","expected":expected,"inserted":0,"already_present":0,"failed":expected,"reason":f"{type(exc).__name__}: {reason}","automatic_deal_promotion":False,"automatic_outreach_authority":False}


def _prepared_crm_prospects()->list[dict]:
    books=(
        ("energy_core", ENERGY_CRM_LEADS),
        ("global_energy", GLOBAL_ENERGY_CRM_LEADS),
        ("worldwide_trade", WORLDWIDE_TRADE_COUNTERPARTIES),
        ("midmarket_oil_dependent", MIDMARKET_OIL_DEPENDENT_LEADS),
        ("cuba_mipyme_expansion", CUBA_MIPYME_EXPANSION_LEADS),
    )
    rows=[]; seen=set()
    for book_name, leads in books:
        for lead in leads:
            business=str(lead.get("business_name") or lead.get("legal_name") or "Unnamed prospect").strip()
            country=str(lead.get("country") or lead.get("country_code") or "UN").strip().upper()[:3]
            dedupe=(business.lower(), country)
            if dedupe in seen: continue
            seen.add(dedupe)
            digest=hashlib.sha256(f"{business}|{country}|{book_name}".encode()).hexdigest()[:18]
            rows.append({
                "intake_id":f"prepared:{digest}",
                "customer_id":f"prepared:{digest}",
                "legal_name":business,
                "trade_name":business,
                "contact_name":lead.get("contact_name"),
                "email":lead.get("email"),
                "phone":lead.get("phone"),
                "country_code":country,
                "website":lead.get("website") or lead.get("source_url"),
                "product_need":lead.get("product_need_or_offer") or lead.get("product") or "Commercial prospect — qualification required",
                "destination_country":country,
                "status":"RESEARCH_PROSPECT",
                "qualification_status":"PENDING",
                "source":book_name,
                "source_description":lead.get("source_description") or lead.get("evidence_summary"),
                "source_url":lead.get("source_url") or lead.get("source_reference"),
                "deal_side":lead.get("deal_side") or lead.get("lead_type"),
                "notes":lead.get("notes"),
                "prospect_only":True,
                "prepared_record":True,
                "persisted":False,
                "read_only":True,
            })
    return rows


@app.get("/crm/intakes")
async def resilient_crm_intakes(
    x_role:str|None=Header(None,alias="X-Role"),
    authorization:str|None=Header(None,alias="Authorization"),
    x_employee_id:str|None=Header(None,alias="X-Employee-Id"),
):
    try:
        from customer_crm_api import list_intakes as live_list_intakes
        return await live_list_intakes(x_role=x_role, authorization=authorization, x_employee_id=x_employee_id)
    except HTTPException:
        raise
    except Exception as exc:
        rows=_prepared_crm_prospects()
        return {
            "intakes":rows[:250],
            "real_intake_count":0,
            "prospect_count":len(rows),
            "status":"DEGRADED_READ_ONLY",
            "persisted_records_available":False,
            "prepared_records_visible":True,
            "database_write_enabled":False,
            "database_issue":"CANONICAL_DATABASE_AUTHENTICATION_REQUIRED",
            "error_type":type(exc).__name__,
            "message":"Prepared CRM prospects are visible read-only while the canonical production database credential is repaired.",
        }


@app.post("/crm/intake")
async def resilient_public_crm_intake(request:Request):
    try:
        from customer_crm_api import IntakeIn, public_intake
        payload=IntakeIn.model_validate(await request.json())
        return await public_intake(payload)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail={
            "code":"CANONICAL_DATABASE_AUTHENTICATION_REQUIRED",
            "message":"New CRM intake writes are temporarily unavailable until the canonical production database credential is repaired.",
            "fail_closed":True,
            "error_type":type(exc).__name__,
        })


@app.get("/activation/health")
async def activation_health():
    bootstrap=None; crm_seeds={}
    if os.getenv("VERCEL_ENV","").strip().lower()=="production" and persistent_backend_status()["database_url_configured"]:
        try: bootstrap=await ensure_production_schema()
        except Exception as exc: bootstrap={"completed":False,"canonical_database":"active_vercel_database_url","reason":f"{type(exc).__name__}: {str(exc).strip().splitlines()[0][:240] if str(exc).strip() else 'unknown bootstrap error'}","fail_closed":True}
        for name, expected, runner in (
            ("energy_core",len(ENERGY_CRM_LEADS),ensure_energy_crm_seed),
            ("global_energy",len(GLOBAL_ENERGY_CRM_LEADS),ensure_global_energy_crm_seed),
            ("worldwide_trade",len(WORLDWIDE_TRADE_COUNTERPARTIES),ensure_worldwide_trade_counterparty_seed),
            ("midmarket_oil_dependent",len(MIDMARKET_OIL_DEPENDENT_LEADS),ensure_midmarket_oil_dependent_seed),
            ("cuba_mipyme_expansion",len(CUBA_MIPYME_EXPANSION_LEADS),ensure_cuba_mipyme_expansion_seed),
        ):
            try: crm_seeds[name]=await runner()
            except Exception as exc: crm_seeds[name]=_seed_failure(expected,exc)

    connector_health=await trade_connectors.health(); schema_evidence=await production_schema_evidence(); readiness=evaluate_production_readiness(runtime_ok=True,connector_health=connector_health,persistence_schema_evidence=schema_evidence); providers=_provider_state(schema_evidence); external=_external_requirements(); persistence_ready=providers["persistence"]["configured"] and providers["persistence"]["schemas_applied"]
    seed_expected=sum(int(v.get("expected") or 0) for v in crm_seeds.values()); seed_inserted=sum(int(v.get("inserted") or 0) for v in crm_seeds.values()); seed_present=sum(int(v.get("already_present") or 0) for v in crm_seeds.values()); seed_failed=sum(int(v.get("failed") or 0) for v in crm_seeds.values())
    return {
        "status":"ready" if readiness["production_ready"] else "activation_required","service":"production-activation-control","business":"SAHJONY Global Trade","canonical_database":"active_vercel_database_url","schema_bootstrap":bootstrap,
        "crm_seeds":{"books":crm_seeds,"expected":seed_expected,"inserted_this_run":seed_inserted,"already_present":seed_present,"failed":seed_failed,"buyer_seller_worldwide":True,"automatic_deal_promotion":False},
        "readiness_score":readiness["score"],"passed_gates":readiness["passed_gates"],"total_gates":readiness["total_gates"],"blocker_count":readiness["blocker_count"],"release_gate":readiness["release_gate"],"production_ready":readiness["production_ready"],"safe_to_accept_persisted_trade_requests":persistence_ready,"safe_to_release_transactions":readiness["production_ready"],"providers":providers,"connectors":connector_health,"blockers":readiness["blockers"],"external_actions_required":external,
        "policy":{"fail_closed":True,"no_fake_100_percent":True,"first_live_trade_required":True,"canonical_transaction_currency":CANONICAL_TRANSACTION_CURRENCY,"usd_only_transactions":USD_ONLY_TRANSACTIONS,"ai_has_release_authority":False},
    }
