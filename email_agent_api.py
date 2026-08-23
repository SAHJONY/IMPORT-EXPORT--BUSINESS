from __future__ import annotations

from fastapi import FastAPI

from business_email_registry import DEPARTMENTS, CANONICAL_DOMAIN

app = FastAPI(title="SAHJONY Global Trade Email Agent", version="1.0.0", docs_url=None, redoc_url=None)

AUTO_ACTIONS = [
    "triage and classify inbound business email",
    "reply to routine customer, supplier, sourcing, logistics and support inquiries",
    "send non-binding status updates and information requests",
    "follow up on unresolved business threads",
    "preserve thread context and sender language when practical",
    "route messages to the appropriate SAHJONY business department",
]

OWNER_APPROVAL_REQUIRED = [
    "contract acceptance, amendment, termination or waiver",
    "payment, refund, wire, bank-detail or beneficiary authorization",
    "binding pricing, credit, financing or commercial commitment",
    "supplier selection or commitment",
    "country, compliance, sanctions, import/export or shipment release",
    "legal determinations or admissions",
    "credentials, API keys, passwords or other secrets",
]

@app.get("/email-agent/health")
def email_agent_health():
    return {
        "status": "ok",
        "service": "sahjony-global-trade-email-agent",
        "canonical_domain": CANONICAL_DOMAIN,
        "departments": len(DEPARTMENTS),
        "mode": "24_7_agentic_business_email",
        "routine_replies": "autonomous",
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
        "principle": "Automate communication, not legal authority or movement of funds.",
    }
