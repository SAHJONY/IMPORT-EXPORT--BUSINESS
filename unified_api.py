import os
import secrets

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import decode_neon_jwt, neon_auth_jwks_url, neon_auth_url, verify_employee_neon_token
from insforge_backend import InsForgeConfigurationError
from telegram_api import app as telegram_app
from business_email_registry import app as business_email_app
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
from cuba_current_api import app as cuba_current_app
from cuba_transition_api import app as cuba_transition_app
from cuba_trade_desk_api import app as cuba_trade_desk_app
from cuba_private_business_api import app as cuba_private_business_app
from cuba_private_sector_lead_api import app as cuba_private_sector_lead_app
from managed_trade_gateway_api import app as managed_trade_app
from managed_trade_intermediary_api import app as intermediary_app
from global_supplier_sourcing_api import app as global_sourcing_app
from business_readiness_api import app as business_readiness_app
from us_import_desk_api import app as us_import_app
from ai_brain_api import app as ai_brain_app
from customer_crm_api import app as customer_crm_app
from fastapi_server import app as core_app

# Existing domain APIs historically validate an EMPLOYEE_TOKEN.  A private,
# process-local bridge credential lets Neon-authenticated employees enter those
# modules without exposing or weakening their existing authorization contracts.
_RUNTIME_EMPLOYEE_BRIDGE_TOKEN = os.getenv("EMPLOYEE_TOKEN", "").strip() or secrets.token_urlsafe(48)
os.environ.setdefault("EMPLOYEE_TOKEN", _RUNTIME_EMPLOYEE_BRIDGE_TOKEN)

app = FastAPI(title="SAHJONY Global Trade Unified API", version="3.4.0", docs_url=None, redoc_url=None)


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


@app.exception_handler(InsForgeConfigurationError)
async def insforge_configuration_error(_request: Request, exc: InsForgeConfigurationError):
    return JSONResponse(status_code=503, content={
        "detail": "Persistent trade backend is not configured for this deployment.",
        "code": "INSFORGE_NOT_CONFIGURED",
        "service": "insforge",
        "required": ["INSFORGE_BASE_URL", "INSFORGE_API_KEY"],
    })


@app.get("/identity/health")
async def identity_health():
    return {
        "status": "ok",
        "service": "sahjony-identity",
        "provider": "neon_auth",
        "auth_url_configured": bool(neon_auth_url()),
        "jwks_url_configured": bool(neon_auth_jwks_url()),
        "customer_self_signup": True,
        "employee_requires_approved_role": True,
        "owner_uses_separate_restricted_gate": True,
        "fail_closed": True,
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
    return {
        "status": "authenticated",
        "role": x_role,
        "user_id": claims.get("sub"),
        "email": claims.get("email"),
        "name": claims.get("name"),
        "identity_provider": "neon_auth",
    }


@app.get("/crm/health")
async def crm_runtime_health():
    base_url = bool(os.getenv("INSFORGE_BASE_URL", "").strip())
    api_key = bool(os.getenv("INSFORGE_API_KEY", "").strip())
    configured = base_url and api_key
    return {
        "status": "ok" if configured else "configuration_required",
        "service": "customer-crm",
        "public_intake": True,
        "fail_closed_promotion": True,
        "persistence": "insforge",
        "backend_configured": configured,
        "insforge_base_url_configured": base_url,
        "insforge_api_key_configured": api_key,
        "operational": configured,
    }


for subapp in (
    telegram_app, business_email_app, owner_auth_app, core_app, customer_crm_app,
    communications_app, documents_app, document_storage_app, shipments_app,
    compliance_app, commercial_app, language_app, collaboration_app, finance_app,
    countries_app, cuba_current_app, cuba_transition_app, cuba_trade_desk_app,
    cuba_private_business_app, cuba_private_sector_lead_app, managed_trade_app,
    intermediary_app, global_sourcing_app, business_readiness_app, us_import_app,
    ai_brain_app,
):
    app.include_router(subapp.router)
