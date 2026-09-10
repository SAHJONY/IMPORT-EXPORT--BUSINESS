from __future__ import annotations

from fastapi import FastAPI

from business_email_registry import DEPARTMENTS, CANONICAL_DOMAIN
from business_communications_director_api import app as communications_director_app
from google_calendar_transport_api import app as calendar_transport_app
from whatsapp_sales_channel_api import app as whatsapp_sales_app
from whatsapp_rfq_execution_api import app as whatsapp_rfq_execution_app
from whatsapp_relationship_memory_api import app as whatsapp_relationship_memory_app
from business_os_api import app as business_os_app
from business_os_executor_api import app as business_os_executor_app
from global_deal_decision_api import app as global_deal_decision_app

app = FastAPI(title="SAHJONY Global Trade Email Agent", version="2.6.0", docs_url=None, redoc_url=None)

AUTO_ACTIONS = [
    "triage and classify inbound business email",
    "reply autonomously to routine customer, supplier, sourcing, logistics, operations and support inquiries only when the CRM/Gmail commercial gate permits",
    "send non-binding status updates and information requests only through the gated commercial transport",
    "follow up on nonresponder business threads only after the full thread is read, CRM eligibility is confirmed, and 168 full hours have elapsed from the newest successful Gmail outbound",
    "preserve thread context and sender language when practical",
    "route messages to the appropriate SAHJONY business department",
    "coordinate routine meetings, calendar invitations, rescheduling and reminders",
    "carry conversation context across email, WhatsApp, voice and calendar",
    "maintain durable relationship memory for WhatsApp contacts and suppress repeated discovery questions",
    "use progressive discovery with no more than two missing questions per conversational turn",
    "create and route enterprise missions across business departments",
    "execute routine reversible business missions through a durable action queue",
    "verify execution evidence before marking missions complete",
    "create durable RFQ packages and open sourcing, logistics and compliance workstreams only when genuine evidence makes a trade opportunity RFQ-ready",
    "evaluate material global deals through GO HOLD BLOCK evidence gates before material execution",
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
        "version": "2.6.0",
        "canonical_domain": CANONICAL_DOMAIN,
        "departments": len(DEPARTMENTS),
        "mode": "24_7_agentic_business_communications",
        "receive_email": True,
        "routine_replies": "autonomous_when_gate_allows",
        "autonomous_follow_up": "gated_168h_nonresponder_only",
        "commercial_email_gate_version": "4.0",
        "commercial_send_transport_gate": True,
        "commercial_gate_approval_ttl_seconds": 600,
        "nonresponder_followup_min_hours": 168,
        "full_gmail_thread_required": True,
        "gmail_timestamp_authoritative": True,
        "crm_authoritative_for_commercial_eligibility": True,
        "post_send_gmail_evidence_required": True,
        "qualified_demand_requires_genuine_inbound_evidence": True,
        "calendar_management": True,
        "whatsapp_sales_brain": True,
        "whatsapp_relationship_memory_360": True,
        "whatsapp_progressive_discovery": True,
        "whatsapp_repeat_question_suppression": True,
        "whatsapp_relationship_memory_route": "/whatsapp/relationship-memory",
        "whatsapp_rfq_execution": True,
        "rfq_execution_route": "/whatsapp/sales/leads/{lead_id}/rfq/execute",
        "business_os_orchestrator": True,
        "business_os_executor": True,
        "business_os_route": "/email-agent/business-os",
        "business_os_executor_route": "/email-agent/business-os/executor",
        "global_deal_decision_engine": True,
        "global_deal_decision_route": "/business-os/deal-decision",
        "global_deal_decisions": ["GO", "HOLD", "BLOCK"],
        "durable_decision_audit": True,
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
        "commercial_email_gate": {
            "version": "4.0",
            "crm_first": True,
            "full_thread_required": True,
            "nonresponder_followup_min_hours": 168,
            "gmail_timestamp_required": True,
            "approval_ttl_seconds": 600,
            "post_send_reconciliation_required": True,
            "fail_closed": True,
        },
        "principle": "Autonomously execute routine reversible work through durable queues and evidence gates. Commercial email must pass the CRM/Gmail gate, nonresponder follow-up must wait 168 full hours from the newest successful Gmail outbound, and binding, financial, legal, compliance-release, destructive or irreversible commitments remain owner-gated.",
    }


# Mount advanced communication and enterprise-orchestration capabilities inside the
# already-deployed unified API so Vercel Hobby remains within its 12-function limit.
app.include_router(communications_director_app.router)
app.include_router(calendar_transport_app.router)
app.include_router(whatsapp_sales_app.router)
app.include_router(whatsapp_rfq_execution_app.router)
app.include_router(whatsapp_relationship_memory_app.router)
app.include_router(global_deal_decision_app.router)
app.include_router(business_os_app.router, prefix="/email-agent")
app.include_router(business_os_executor_app.router, prefix="/email-agent")
