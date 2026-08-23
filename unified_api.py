import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Import each existing FastAPI application and aggregate its routes into one
# serverless entrypoint. This keeps the domain modules independent while
# avoiding Vercel Hobby's per-deployment Serverless Function count limit.
# Production routing is intentionally consolidated here.
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

app = FastAPI(
    title="SAHJONY Global Trade Unified API",
    version="3.3.1",
    docs_url=None,
    redoc_url=None,
)


@app.exception_handler(InsForgeConfigurationError)
async def insforge_configuration_error(_request: Request, exc: InsForgeConfigurationError):
    """Convert missing backend configuration into an explicit fail-closed API response."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Persistent trade backend is not configured for this deployment.",
            "code": "INSFORGE_NOT_CONFIGURED",
            "service": "insforge",
            "required": ["INSFORGE_BASE_URL", "INSFORGE_API_KEY"],
        },
    )


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


# Preserve every existing route path exactly as defined by the domain apps.
for subapp in (
    telegram_app,
    business_email_app,
    owner_auth_app,
    core_app,
    customer_crm_app,
    communications_app,
    documents_app,
    document_storage_app,
    shipments_app,
    compliance_app,
    commercial_app,
    language_app,
    collaboration_app,
    finance_app,
    countries_app,
    cuba_current_app,
    cuba_transition_app,
    cuba_trade_desk_app,
    cuba_private_business_app,
    cuba_private_sector_lead_app,
    managed_trade_app,
    intermediary_app,
    global_sourcing_app,
    business_readiness_app,
    us_import_app,
    ai_brain_app,
):
    app.include_router(subapp.router)
