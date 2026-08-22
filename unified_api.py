from fastapi import FastAPI

# Import each existing FastAPI application and aggregate its routes into one
# serverless entrypoint. This keeps the domain modules independent while
# avoiding Vercel Hobby's per-deployment Serverless Function count limit.
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
from managed_trade_gateway_api import app as managed_trade_app
from managed_trade_intermediary_api import app as intermediary_app
from global_supplier_sourcing_api import app as global_sourcing_app
from business_readiness_api import app as business_readiness_app
from fastapi_server import app as core_app

app = FastAPI(
    title="SAHJONY Global Trade Unified API",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)

# Preserve every existing route path exactly as defined by the domain apps.
for subapp in (
    core_app,
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
    managed_trade_app,
    intermediary_app,
    global_sourcing_app,
    business_readiness_app,
):
    app.include_router(subapp.router)
