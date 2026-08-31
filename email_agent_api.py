from __future__ import annotations

from fastapi import FastAPI

from business_email_registry import DEPARTMENTS, CANONICAL_DOMAIN
from business_communications_director_api import app as communications_director_app
from google_calendar_transport_api import app as calendar_transport_app
from whatsapp_sales_channel_api import app as whatsapp_sales_app
from business_os_api import app as business_os_app

app = FastAPI(title="SAHJONY Global Trade Email Agent", version="2.1.1", docs_url=None, redoc_url=None)

AUTO_ACTIONS = [
    "triage and classify inbound business email",
    "reply autonomously to routine customer, supplier, sourcing, logistics, operations and support inquiries",
    "send non-binding status updates and information requests",
    "follow up autonomously on unresolved business threads",
    "preserve thread context and sender language when practical",
    "route messages to the appropriate SAHJONY business department",
    "coordinate routine meetings, calendar invitations, rescheduling and reminders",
    "carry conversation context across email, WhatsApp, voice and calendar",
    "create and route enterprise missions across business departments",
    "manage routine reversible business and application operations until resolution or a governance gate",
]

OWNER_APPROVAL_REQUIRED = [
    "contract acceptance, amendment, termination or waiver",
    "payment, refund, wire, bank-detail or beneficiary authorization",
    "binding pricing, credit, financing or commercial commitment without verified evidence",
    "supplier selection or commitment that creates legal or financial obligation",
    "country, compliance, sanctions, import/export or shipment release",
    "legal determinations or admissions",
    "critical production deletion or security-control bypass",
    "credentials, API keys, passwords or other secrets",
]


@app.get("/email-agent/health")
def email_agent_health():
    return {
        "status": "ok",
        "service": "sahjony-global-trade-email-agent",
        "version": "2.1.1",
        "canonical_domain": CANONICAL_DOMAIN,
        "departments": len(DEPARTMENTS),
        "mode": "24_7_agentic_business_communications",
        "receive_email": True,
        "routine_replies": "autonomous",
        "autonomous_follow_up": True,
        "calendar_management": True,
        "whatsapp_sales_brain": True,
        "business_os_orchestrator": True,
        "business_os_route": "/email-agent/business-os",
        "cross_channel_context": True,
        "department_routing": True,
        "high_risk_actions": "owner_approval_required",
        "fail_closed": True,
        "duplicate_reply_protection_required": True,
        "thread_context_required": True,
    }


@app.get("/email-agent/policy")
def email_agent_policy():
    return {
        "auto_actions": AUTO_ACTIONS,
        "owner_approval_required": OWNER_APPROVAL_REQUIRED,
        "department_routing": [
            {"key": d["key"], "name": d["name"], "email": d["email"], "function": d["function"]}
            for d in DEPARTMENTS
        ],
        "channels": ["email", "whatsapp", "voice", "calendar", "web", "internal"],
        "principle": "Autonomously manage routine business communications, scheduling and reversible operations; fail closed before financial, contractual, legal, compliance-release, destructive or other binding commitments.",
    }


# Mount advanced communication and enterprise-orchestration capabilities inside the
# already-deployed unified API so Vercel Hobby remains within its 12-function limit.
app.include_router(communications_director_app.router)
app.include_router(calendar_transport_app.router)
app.include_router(whatsapp_sales_app.router)
app.include_router(business_os_app.router, prefix="/email-agent")
