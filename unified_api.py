import os
import secrets

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import decode_neon_jwt, neon_auth_jwks_url, neon_auth_url, verify_employee_neon_token
from insforge_backend import PersistentBackendConfigurationError, get_backend, persistent_backend_status
from activation_api import app as activation_app, activation_health
from telegram_api import app as telegram_app
from business_email_registry import app as business_email_app
from email_agent_api import app as email_agent_app
from owner_auth_api import app as owner_auth_app
from communication_api import app as communications_app
from document_api import app as documents_app
from document_storage_api import app as document_storage_app
from shipment_api import app as shipments_app
from compliance_api import app as compliance_app
from commercial_api import app as commercial_app
from translation_api import app as language_app
from collaboration_api import app as collaboration_app
from finance_api import app as finance_app
from country_activation_api import app as countries_app
from country_crm_api import app as country_crm_app
from global_lead_search_api import app as global_lead_search_app
from energy_crude_oil_api import app as energy_app
from energy_origination_api import app as energy_origination_app
from energy_market_intelligence_api import app as energy_intelligence_app
from energy_provider_hub_api import app as energy_provider_hub_app
from energy_provider_ingestion_api import app as energy_provider_ingestion_app
from energy_provider_catalog_api import app as energy_provider_catalog_app
from energy_ofac_screening_api import app as energy_ofac_screening_app
from cuba_current_api import app as cuba_current_app
from cuba_transition_api import app as cuba_transition_app
from cuba_trade_desk_api import app as cuba_trade_desk_app
from cuba_private_business_api import app as cuba_private_business_app
from cuba_private_sector_lead_api import app as cuba_private_sector_lead_app
from lead_scout_api import app as lead_scout_app
from managed_trade_gateway_api import app as managed_trade_app
from managed_trade_intermediary_api import app as intermediary_app
from global_supplier_sourcing_api import app as global_sourcing_app
from business_readiness_api import app as business_readiness_app
from us_import_desk_api import app as us_import_app
from ai_brain_api import app as ai_brain_app
from ai_trade_agent_api import app as ai_trade_agent_app
from trade_workflow_certification_api import app as trade_certification_app
from customer_crm_api import app as customer_crm_app
from fastapi_server import app as core_app

_RUNTIME_EMPLOYEE_BRIDGE_TOKEN = os.getenv("EMPLOYEE_TOKEN", "").strip() or secrets.token_urlsafe(48)
os.environ.setdefault("EMPLOYEE_TOKEN", _RUNTIME_EMPLOYEE_BRIDGE_TOKEN)

app = FastAPI(title="SAHJONY Global Trade Unified API", version="5.5.0", docs_url=None, redoc_url=None)


@app.middleware("http")
async def neon_identity_bridge(request: Request, call_next):
    role = request.headers.get("X-Role", "").strip().lower()
    authorization = request.headers.get("Authorization", "")
    if role == "employee" and authorization.startswith("Bearer "):
        supplied = authorization.removeprefix("Bearer ").strip()
        claims = verify_employee_neon_token(supplied)
        if claims:
            headers = [(k, v) for k, v in request.scope.get("headers", []) if k.lower() not in {b"authorization", b"x-employee-id"}]
            headers.append((b"authorization", f"Bearer {_RUNTIME_EMPLOYEE_BRIDGE_TOKEN}".encode()))
            employee_id = str(claims.get("sub") or claims.get("email") or "staff")[:160]
            headers.append((b"x-employee-id", employee_id.encode()))
            request.scope["headers"] = headers
    return await call_next(request)


@app.exception_handler(PersistentBackendConfigurationError)
async def persistent_backend_configuration_error(_request: Request, exc: PersistentBackendConfigurationError):
    status = persistent_backend_status()
    return JSONResponse(status_code=503, content={
        "detail": "Durable trade persistence is not configured for this deployment.",
        "code": "PERSISTENT_BACKEND_NOT_CONFIGURED",
        "service": "trade-persistence",
        "provider": status["provider"],
        "accepted_backends": ["neon_postgres", "insforge"],
        "required_any_of": [["DATABASE_URL"], ["POSTGRES_URL"], ["NEON_DATABASE_URL"], ["INSFORGE_BASE_URL", "INSFORGE_API_KEY"]],
        "fail_closed": True,
    })


@app.get("/identity/health")
async def identity_health():
    return {
        "status": "ok", "service": "sahjony-identity", "provider": "neon_auth",
        "auth_url_configured": bool(neon_auth_url()), "jwks_url_configured": bool(neon_auth_jwks_url()),
        "customer_self_signup": True, "employee_requires_approved_role": True,
        "owner_uses_separate_restricted_gate": True, "fail_closed": True,
    }


@app.get("/identity/session")
async def identity_session(x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization")):
    if x_role not in {"customer", "employee"}:
        raise HTTPException(400, "X-Role must be customer or employee")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    claims = verify_employee_neon_token(token) if x_role == "employee" else decode_neon_jwt(token)
    if not claims:
        raise HTTPException(403, "Neon identity is invalid or this account is not approved for the requested role")
    return {"status": "authenticated", "role": x_role, "user_id": claims.get("sub"), "email": claims.get("email"), "name": claims.get("name"), "identity_provider": "neon_auth"}


@app.get("/backend/health")
async def backend_health():
    status = persistent_backend_status()
    if not status["configured"]:
        return {"status": "configuration_required", "service": "trade-persistence", **status}
    try:
        metadata = await get_backend().metadata()
        return {"status": "ok", "service": "trade-persistence", **status, "reachable": True, "metadata": metadata}
    except Exception as exc:
        return {"status": "degraded", "service": "trade-persistence", **status, "reachable": False, "error": type(exc).__name__}


@app.get("/crm/health")
async def crm_runtime_health():
    status = persistent_backend_status()
    return {
        "status": "ok" if status["configured"] else "configuration_required",
        "service": "customer-crm", "public_intake": True, "fail_closed_promotion": True,
        "country_segmentation": True, "cuba_department_permanent": True,
        "global_lead_search_control_plane": True, "energy_vertical_connected": True,
        "persistence": status["provider"], "backend_configured": status["configured"], "operational": status["configured"],
        "database_url_configured": status["database_url_configured"], "insforge_configured": status["insforge_configured"],
    }


@app.get("/health")
async def platform_health():
    activation = await activation_health()
    return {
        "status": "ok", "service": "global-trade-intelligence-os", "version": "5.5.0",
        "release_policy": "fail-closed", "production_ready": activation["production_ready"],
        "readiness_score": activation["readiness_score"], "passed_gates": activation["passed_gates"],
        "total_gates": activation["total_gates"], "blocker_count": activation["blocker_count"],
        "release_gate": activation["release_gate"], "identity_provider": activation["providers"]["identity"]["provider"],
        "persistence_provider": activation["providers"]["persistence"]["provider"], "persistence_configured": activation["providers"]["persistence"]["configured"],
        "openai_configured": activation["providers"]["ai"]["openai_configured"], "anthropic_configured": activation["providers"]["ai"]["anthropic_configured"],
        "translation_configured": activation["providers"]["translation"]["configured"], "email_agent_control_plane": True,
        "trade_agent_control_plane": True, "trade_workflow_certification_monitor": True,
        "country_segmented_crm": True, "cuba_crm_department": True, "global_lead_search_control_plane": True,
        "energy_crude_oil_os": True, "energy_autonomous_origination": True, "energy_origination_markets": 21,
        "energy_market_intelligence": True, "energy_autonomous_matching": True, "energy_provider_hub": True,
        "energy_provider_normalization": True, "energy_authoritative_provider_catalog": True,
        "energy_ofac_authoritative_screening": True, "energy_ofac_complete_legacy_series": True,
        "energy_fail_closed_release": True, "blockers": activation["blockers"],
    }


for subapp in (
    activation_app, telegram_app, business_email_app, email_agent_app, owner_auth_app, core_app, customer_crm_app, country_crm_app, global_lead_search_app,
    energy_app, energy_origination_app, energy_intelligence_app, energy_provider_hub_app, energy_provider_ingestion_app, energy_provider_catalog_app, energy_ofac_screening_app,
    communications_app, documents_app, document_storage_app, shipments_app, compliance_app, commercial_app, language_app, collaboration_app, finance_app,
    countries_app, cuba_current_app, cuba_transition_app, cuba_trade_desk_app, cuba_private_business_app, cuba_private_sector_lead_app,
    lead_scout_app, managed_trade_app, intermediary_app, global_sourcing_app, business_readiness_app, us_import_app,
    ai_brain_app, ai_trade_agent_app, trade_certification_app,
):
    app.include_router(subapp.router)
