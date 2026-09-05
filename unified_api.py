import hashlib
import hmac
import os
import secrets

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from auth import decode_supabase_jwt, supabase_auth_jwks_url, supabase_auth_url, verify_employee_neon_token
from insforge_backend import PersistentBackendConfigurationError, get_backend, persistent_backend_status
from activation_api import app as activation_app, activation_health
from telegram_api import app as telegram_app
from business_email_registry import app as business_email_app
from email_agent_api import app as email_agent_app
from gmail_transport_api import app as gmail_transport_app
from google_contacts_api import app as google_contacts_app
from owner_auth_api import app as owner_auth_app
from higgsfield_cloud_api import app as higgsfield_cloud_app
from communication_api import app as communications_app
from communication_os_security_api import app as communication_os_security_app
from communication_os_api import app as communication_os_app
from communication_agentic_api import app as communication_agentic_app
from communication_platform_api import app as communication_platform_app
from direct_text_api import app as direct_text_app
from wifi_connectivity_api import app as wifi_connectivity_app
from cuba_communications_api import app as cuba_communications_app
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
from cloudflare_crawler_api import app as cloudflare_crawler_app
from worldwide_connect_api import app as worldwide_connect_app
from cuba_private_fuels_desk_api import app as cuba_private_fuels_app
from energy_crude_oil_api import app as energy_app
from energy_origination_api import app as energy_origination_app
from energy_market_intelligence_api import app as energy_intelligence_app
from energy_provider_hub_api import app as energy_provider_hub_app
from energy_provider_ingestion_api import app as energy_provider_ingestion_app
from energy_provider_catalog_api import app as energy_provider_catalog_app
from energy_ofac_screening_api import app as energy_ofac_screening_app
from energy_eia_api import app as energy_eia_app
from energy_deal_flow_api import app as energy_deal_flow_app
from energy_revenue_intelligence_api import app as energy_revenue_intelligence_app
from cuba_current_api import app as cuba_current_app
from cuba_transition_api import app as cuba_transition_app
from cuba_trade_desk_api import app as cuba_trade_desk_app
from cuba_private_business_api import app as cuba_private_business_app
from cuba_private_sector_lead_api import app as cuba_private_sector_lead_app
from cuba_mipymes_api import app as cuba_mipymes_app
from cuba_sofia_sales_bridge_api import app as cuba_sofia_sales_bridge_app
from competition_intelligence_api import app as competition_intelligence_app
from sofia_deal_match_api import app as sofia_deal_match_app
from world_clock_trade_api import app as world_clock_trade_app
from lead_scout_api import app as lead_scout_app
from managed_trade_gateway_api import app as managed_trade_app
from managed_trade_intermediary_api import app as intermediary_app
from global_supplier_sourcing_api import app as global_sourcing_app
from global_marketplace_api import app as global_marketplace_app
from business_readiness_api import app as business_readiness_app
from us_import_desk_api import app as us_import_app
from ai_brain_api import app as ai_brain_app
from ai_trade_agent_api import app as ai_trade_agent_app
from agentic_trade_engine_api import app as agentic_trade_engine_app
from trade_workflow_certification_api import app as trade_certification_app
from customer_crm_api import app as customer_crm_app
from crm_quality_10x_api import app as crm_quality_10x_app
from external_trade_prospects_api import app as external_trade_prospects_app
from profit_machine_api import app as profit_machine_app
from record_registry_api import app as record_registry_app
from latam_trade_research_api import app as latam_trade_research_app
from outreach_marketing_department_api import app as outreach_marketing_app
from social_media_management_api import app as social_media_management_app
from voice_inbound_api import app as voice_inbound_app
from voice_agent_api import app as voice_agent_app
from direct_voice_api import app as direct_voice_app
from voice_autonomy_api import app as voice_autonomy_app
from whatsapp_voice_orchestrator_api import app as whatsapp_voice_orchestrator_app
from fastapi_server import app as core_app

_RUNTIME_EMPLOYEE_BRIDGE_TOKEN = os.getenv("EMPLOYEE_TOKEN", "").strip() or secrets.token_urlsafe(48)
os.environ.setdefault("EMPLOYEE_TOKEN", _RUNTIME_EMPLOYEE_BRIDGE_TOKEN)

app = FastAPI(title="SAHJONY LLC Unified Trade API", version="7.5.0", docs_url=None, redoc_url=None)

@app.middleware("http")
async def supabase_identity_bridge(request: Request, call_next):
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
    response = await call_next(request)
    if request.url.path.startswith("/higgsfield-cloud"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response

@app.exception_handler(PersistentBackendConfigurationError)
async def persistent_backend_configuration_error(_request: Request, exc: PersistentBackendConfigurationError):
    status = persistent_backend_status()
    return JSONResponse(status_code=503, content={
        "detail":"Supabase trade persistence is not configured for this deployment.",
        "code":"SUPABASE_BACKEND_NOT_CONFIGURED",
        "service":"trade-persistence",
        "provider":status["provider"],
        "canonical_backend":"supabase",
        "required_any_of":[["SUPABASE_URL","SUPABASE_SERVICE_ROLE_KEY"],["SUPABASE_URL","SUPABASE_SECRET_KEY"]],
        "fail_closed":True,
    })

@app.get("/identity/health")
async def identity_health():
    configured = bool(supabase_auth_url()) and bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip() or os.getenv("SUPABASE_SECRET_KEY", "").strip() or os.getenv("SUPABASE_KEY", "").strip())
    return {
        "status":"ok" if configured else "configuration_required",
        "service":"sahjony-identity",
        "provider":"supabase_auth",
        "auth_url_configured":bool(supabase_auth_url()),
        "jwks_url_configured":bool(supabase_auth_jwks_url()),
        "membership_authorization":True,
        "customer_self_signup":True,
        "employee_requires_approved_membership":True,
        "owner_requires_approved_membership":True,
        "fail_closed":True,
    }

@app.get("/identity/session")
async def identity_session(x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization")):
    if x_role not in {"customer", "employee"}: raise HTTPException(400, "X-Role must be customer or employee")
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    claims = verify_employee_neon_token(token) if x_role == "employee" else decode_supabase_jwt(token)
    if not claims: raise HTTPException(403, "Supabase identity is invalid or this account is not approved for the requested role")
    return {"status":"authenticated","role":x_role,"user_id":claims.get("sub"),"email":claims.get("email"),"name":claims.get("name"),"identity_provider":"supabase_auth"}

@app.get("/backend/health")
async def backend_health():
    status = persistent_backend_status()
    if not status["configured"]: return {"status":"configuration_required","service":"trade-persistence",**status}
    try:
        metadata = await get_backend().metadata()
        return {"status":"ok","service":"trade-persistence",**status,"reachable":True,"metadata":metadata}
    except Exception as exc:
        return {"status":"degraded","service":"trade-persistence",**status,"reachable":False,"error":type(exc).__name__}

@app.get("/crm/health")
async def crm_runtime_health():
    status = persistent_backend_status()
    return {
        "status":"ok" if status["configured"] else "configuration_required",
        "service":"customer-crm","public_intake":True,"fail_closed_promotion":True,"country_segmentation":True,
        "crm_quality_10x":True,"crm_maturity_scoring":True,"crm_activation_queue":True,"crm_verified_trade_standard":True,
        "cuba_department_permanent":True,"cuba_sofia_sales_os_bridge":True,"sofia_deal_supplier_match":True,"competition_price_scanner":True,"global_world_clock":True,"follow_the_sun_24x7":True,"global_lead_search_control_plane":True,"energy_vertical_connected":True,
        "outreach_marketing_department":True,"autonomous_social_media_management":True,
        "external_trade_prospects":True,"external_trade_prospects_research_only":True,"profit_machine_control_plane":True,
        "zero_own_capital_gate":True,"fee_protection_gate":True,"cash_collected_primary_metric":True,
        "persistence":status["provider"],"canonical_backend":"supabase","backend_configured":status["configured"],
        "supabase_configured":status.get("supabase_configured",False),"operational":status["configured"],
    }

def _messenger_verify_token() -> str:
    return os.getenv("META_MESSENGER_VERIFY_TOKEN", "").strip()


def _messenger_app_secret() -> str:
    return os.getenv("META_MESSENGER_APP_SECRET", "").strip()


@app.get("/api/meta/messenger/health")
async def meta_messenger_health():
    return {
        "status": "ok" if _messenger_verify_token() else "configuration_required",
        "service": "meta-messenger-webhook",
        "verify_token_configured": bool(_messenger_verify_token()),
        "app_secret_configured": bool(_messenger_app_secret()),
        "canonical_agent_id": "sofia-smith",
        "canonical_agent_name": "Sofia Smith",
        "crm_event_capture": True,
        "binding_commitments": False,
        "bulk_unsolicited_outreach": False,
        "secrets_exposed": False,
    }


@app.get("/api/meta/messenger/webhook")
async def meta_messenger_verify(request: Request):
    mode = request.query_params.get("hub.mode", "")
    supplied = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")
    expected = _messenger_verify_token()
    if not expected:
        raise HTTPException(status_code=503, detail="Messenger verify token is not configured")
    if mode != "subscribe" or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Messenger webhook verification failed")
    return PlainTextResponse(challenge, status_code=200)


@app.post("/api/meta/messenger/webhook")
async def meta_messenger_receive(request: Request):
    secret = _messenger_app_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Messenger app secret is not configured")
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid Messenger webhook signature")
    payload = await request.json()
    if payload.get("object") != "page":
        return {"status": "ignored", "reason": "unsupported_object"}
    captured = 0
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = str((event.get("sender") or {}).get("id") or "unknown")[:200]
            message = event.get("message") or {}
            text = str(message.get("text") or "")[:4000]
            event_id = f"evt_{secrets.token_urlsafe(16)}"
            try:
                await get_backend().insert("business_events", {
                    "event_id": event_id,
                    "event_type": "meta_messenger_inbound",
                    "source_type": "meta_messenger",
                    "source_id": sender_id,
                    "trade_case_id": None,
                    "customer_id": None,
                    "lead_id": None,
                    "actor_role": "prospect",
                    "actor_id": sender_id,
                    "visibility": "business",
                    "title": (text or "Messenger event")[:240],
                    "summary": (text or "Inbound Messenger event")[:4000],
                    "action_required": True,
                    "action_label": "Sofia Smith Messenger triage",
                    "priority": "normal",
                    "event_status": "open",
                    "payload": {
                        "channel": "facebook_messenger",
                        "canonical_agent_id": "sofia-smith",
                        "canonical_agent_name": "Sofia Smith",
                        "page_id": str(entry.get("id") or "")[:200],
                        "sender_id": sender_id,
                        "message_mid": str(message.get("mid") or "")[:240],
                        "message_text": text,
                        "postback": event.get("postback"),
                        "referral": event.get("referral"),
                        "binding_commitments_allowed": False,
                        "capital_at_risk_usd": 0,
                    },
                })
                captured += 1
            except PersistentBackendConfigurationError:
                raise
            except Exception:
                pass
    return {"status": "received", "captured_events": captured}


@app.get("/health")
async def platform_health():
    activation = await activation_health()
    cloudflare_crawler_configured = bool(os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()) and bool(os.getenv("CLOUDFLARE_API_TOKEN", "").strip())
    return {"status":"ok","service":"sahjony-llc-global-trade-intelligence-os","version":"7.5.0","canonical_platform":"supabase","release_policy":"fail-closed","production_ready":activation["production_ready"],"readiness_score":activation["readiness_score"],"passed_gates":activation["passed_gates"],"total_gates":activation["total_gates"],"blocker_count":activation["blocker_count"],"release_gate":activation["release_gate"],"identity_provider":activation["providers"]["identity"]["provider"],"persistence_provider":activation["providers"]["persistence"]["provider"],"persistence_configured":activation["providers"]["persistence"]["configured"],"openai_configured":activation["providers"]["ai"]["openai_configured"],"anthropic_configured":activation["providers"]["ai"]["anthropic_configured"],"translation_configured":activation["providers"]["translation"]["configured"],"frontier_agentic_trade_engine":True,"dual_frontier_consensus":True,"autonomous_internal_research":True,"external_commitments_fail_closed":True,"global_industrial_marketplace":True,"marketplace_zero_own_inventory":True,"marketplace_rfq_first":True,"email_agent_control_plane":True,"native_gmail_transport_control_plane":True,"communication_os_control_plane":True,"communication_os_conversation_graph":True,"communication_os_private_human_webrtc":True,"communication_os_ai_consent_gate":True,"communication_os_contact_360":True,"communication_os_agentic_missions":True,"communication_os_agentic_mcp_tools":True,"communication_os_binding_tools_exposed":False,"communication_platform_industry_agnostic":True,"communication_platform_core_plus_industry_packs":True,"communication_platform_generic_context_graph":True,"communication_platform_workspace_policy_engine":True,"communication_platform_binding_tools_exposed":False,"communication_platform_regulated_tools_exposed":False,"communication_os_video_vision":True,"communication_os_screen_share":True,"communication_os_human_takeover":True,"communication_os_room_token_guard":True,"communication_os_direct_text":True,"communication_os_autonomous_notifications":True,"communication_os_free_wifi_control_plane":True,"communication_os_local_lan_mode":True,"communication_os_free_to_end_user_wifi_supported":True,"communication_os_internet_backhaul_fail_closed":True,"cuba_communications_department":True,"cuba_starlink_optional_gate":True,"cuba_free_wifi_program":True,"cuba_sofia_sales_os_bridge":True,"cuba_sofia_sales_autonomy":"AUTONOMOUS_NONBINDING_CONSENT_GATED","sofia_deal_supplier_match":True,"competition_price_scanner":True,"competition_supplier_source_discovery":True,"competition_customer_segment_discovery":True,"global_world_clock":True,"timezone_aware_trade_routing":True,"follow_the_sun_24x7":True,"voice_agent_control_plane":True,"voice_provider":"openai_realtime","voice_direct_webrtc":True,"voice_autonomous_24x7":True,"voice_whatsapp_unified":True,"voice_legacy_bland_ai_runtime":False,"tmobile_byon_control_plane":True,"trade_agent_control_plane":True,"trade_workflow_certification_monitor":True,"country_segmented_crm":True,"cuba_crm_department":True,"cuba_mipymes_crm":True,"crm_quality_10x":True,"crm_verified_trade_standard":True,"global_lead_search_control_plane":True,"external_trade_prospects":True,"external_trade_prospects_research_only":True,"profit_machine_control_plane":True,"outreach_marketing_department":True,"autonomous_social_media_management":True,"zero_own_capital_gate":True,"fee_protection_gate":True,"cash_collected_primary_metric":True,"cloudflare_research_crawler":True,"cloudflare_research_crawler_configured":cloudflare_crawler_configured,"energy_crude_oil_os":True,"energy_autonomous_origination":True,"energy_origination_markets":21,"energy_market_intelligence":True,"energy_autonomous_matching":True,"energy_provider_hub":True,"energy_provider_normalization":True,"energy_authoritative_provider_catalog":True,"energy_ofac_authoritative_screening":True,"energy_ofac_complete_legacy_series":True,"energy_eia_native_adapter":True,"energy_eia_profile_driven":True,"energy_buyer_requirement_ingestion":True,"energy_seller_offer_ingestion":True,"energy_autonomous_matching_v2":True,"energy_deal_room_agent":True,"energy_revenue_intelligence":True,"energy_probability_weighted_pipeline":True,"energy_portfolio_prioritization":True,"energy_next_action_engine":True,"energy_fail_closed_release":True,"blockers":activation["blockers"]}

def _whatsapp_shadow_verify_token() -> str:
    return (
        os.getenv("META_WHATSAPP_VERIFY_TOKEN", "").strip()
        or os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "").strip()
        or os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
    )


def _whatsapp_shadow_app_secret() -> str:
    return os.getenv("META_WHATSAPP_APP_SECRET", "").strip()


@app.get("/api/meta/whatsapp/health")
async def meta_whatsapp_shadow_health():
    return {
        "status": "ok" if _whatsapp_shadow_verify_token() else "configuration_required",
        "service": "meta-whatsapp-shadow-webhook",
        "mode": "shadow_non_authoritative",
        "verify_token_configured": bool(_whatsapp_shadow_verify_token()),
        "app_secret_configured": bool(_whatsapp_shadow_app_secret()),
        "production_authority": False,
        "auto_reply": False,
        "binding_commitments": False,
        "secrets_exposed": False,
    }


@app.get("/api/meta/whatsapp/webhook")
async def meta_whatsapp_shadow_verify(request: Request):
    mode = request.query_params.get("hub.mode", "")
    supplied = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")
    expected = _whatsapp_shadow_verify_token()
    if not expected:
        raise HTTPException(status_code=503, detail="WhatsApp shadow verify token is not configured")
    if mode != "subscribe" or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="WhatsApp shadow webhook verification failed")
    return PlainTextResponse(challenge, status_code=200)


@app.post("/api/meta/whatsapp/webhook")
async def meta_whatsapp_shadow_receive(request: Request):
    secret = _whatsapp_shadow_app_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="WhatsApp shadow app secret is not configured")
    raw = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp shadow webhook signature")
    payload = await request.json()
    if payload.get("object") != "whatsapp_business_account":
        return {"status": "ignored", "reason": "unsupported_object", "auto_reply": False}
    captured = 0
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            for message in value.get("messages", []):
                sender_id = str(message.get("from") or "unknown")[:200]
                message_id = str(message.get("id") or secrets.token_urlsafe(16))[:512]
                msg_type = str(message.get("type") or "message")[:80]
                text = str(((message.get("text") or {}).get("body") or f"[{msg_type} received]"))[:4000]
                try:
                    await get_backend().insert("business_events", {
                        "event_id": f"meta_wa_shadow_{hashlib.sha256(message_id.encode()).hexdigest()[:32]}",
                        "event_type": "meta_whatsapp_shadow_inbound",
                        "source_type": "meta_whatsapp_shadow",
                        "source_id": sender_id,
                        "trade_case_id": None,
                        "customer_id": None,
                        "lead_id": None,
                        "actor_role": "prospect",
                        "actor_id": sender_id,
                        "visibility": "business",
                        "title": (text or "WhatsApp shadow event")[:240],
                        "summary": (text or "Inbound WhatsApp shadow event")[:4000],
                        "action_required": False,
                        "action_label": "Shadow capture only — OpenClaw remains authority",
                        "priority": "normal",
                    })
                    captured += 1
                except Exception:
                    pass
    return {
        "status": "accepted",
        "mode": "shadow_non_authoritative",
        "events_captured": captured,
        "auto_reply": False,
        "production_authority": False,
    }


for subapp in (
    google_contacts_app,
    activation_app, telegram_app, business_email_app, email_agent_app, gmail_transport_app, owner_auth_app, higgsfield_cloud_app, core_app, customer_crm_app, crm_quality_10x_app, external_trade_prospects_app, profit_machine_app, record_registry_app, latam_trade_research_app, outreach_marketing_app, social_media_management_app, country_crm_app, global_lead_search_app, cloudflare_crawler_app, worldwide_connect_app, cuba_private_fuels_app, cuba_mipymes_app, cuba_sofia_sales_bridge_app, competition_intelligence_app, sofia_deal_match_app, world_clock_trade_app,
    energy_app, energy_origination_app, energy_intelligence_app, energy_provider_hub_app, energy_provider_ingestion_app, energy_provider_catalog_app, energy_ofac_screening_app, energy_eia_app, energy_deal_flow_app, energy_revenue_intelligence_app,
    communications_app, communication_os_security_app, communication_os_app, communication_agentic_app, communication_platform_app, direct_text_app, wifi_connectivity_app, cuba_communications_app, voice_inbound_app, voice_agent_app, direct_voice_app, voice_autonomy_app, whatsapp_voice_orchestrator_app, documents_app, document_storage_app, shipments_app, compliance_app, commercial_app, language_app, collaboration_app, finance_app,
    countries_app, cuba_current_app, cuba_transition_app, cuba_trade_desk_app, cuba_private_business_app, cuba_private_sector_lead_app, lead_scout_app, managed_trade_app, intermediary_app, global_sourcing_app, global_marketplace_app, business_readiness_app, us_import_app,
    ai_brain_app, ai_trade_agent_app, agentic_trade_engine_app, trade_certification_app,
):
    app.include_router(subapp.router)
