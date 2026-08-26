import os
from typing import Dict, List

from fastapi import FastAPI


app = FastAPI(title="SAHJONY Business Email Registry", version="1.3.0", docs_url=None, redoc_url=None)

CANONICAL_DOMAIN = os.getenv("BUSINESS_CANONICAL_DOMAIN", "sahjony.com").strip().lower()
CANONICAL_WEBSITE = os.getenv("BUSINESS_CANONICAL_WEBSITE", "https://www.sahjony.com").strip()
TRADE_OS_URL = os.getenv("TRADE_OS_URL", "https://trade.sahjony.com").strip()
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "sahjonycapitalllc@outlook.com").strip().lower()
OPERATIONAL_MAILBOX = os.getenv("OPERATIONAL_MAILBOX", "sahjonyllc@gmail.com").strip().lower()
MAILBOX_PROVIDER = os.getenv("MAILBOX_PROVIDER", "gmail").strip().lower()
MAILBOX_AGENT_MANAGED = os.getenv("MAILBOX_AGENT_MANAGED", "true").strip().lower() == "true"
CANONICAL_ALIASES_HOSTED_VERIFIED = os.getenv("CANONICAL_ALIASES_HOSTED_VERIFIED", "false").strip().lower() == "true"
DIRECT_MAIL_DELIVERY_CONFIGURED = bool(
    os.getenv("SMTP_HOST", "").strip()
    or os.getenv("GMAIL_CLIENT_ID", "").strip()
    or os.getenv("MICROSOFT_GRAPH_CLIENT_ID", "").strip()
    or os.getenv("RESEND_API_KEY", "").strip()
)


def _canonical(local_part: str) -> str:
    return f"{local_part}@{CANONICAL_DOMAIN}"


def _addr(env_name: str, local_part: str) -> str:
    return os.getenv(env_name, _canonical(local_part)).strip().lower()


DEPARTMENTS: List[Dict[str, str]] = [
    {"key": "sales", "name": "SAHJONY Global Trade — Sales", "email": _addr("EMAIL_SALES", "sales"), "function": "New customers, quotes, commercial opportunities"},
    {"key": "sourcing", "name": "SAHJONY Global Trade — Sourcing", "email": _addr("EMAIL_SOURCING", "sourcing"), "function": "Supplier discovery, RFQs, procurement"},
    {"key": "operations", "name": "SAHJONY Global Trade — Operations", "email": _addr("EMAIL_OPERATIONS", "operations"), "function": "Trade execution, case coordination, milestones"},
    {"key": "compliance", "name": "SAHJONY Global Trade — Compliance", "email": _addr("EMAIL_COMPLIANCE", "compliance"), "function": "Sanctions, export/import controls, release gates"},
    {"key": "finance", "name": "SAHJONY Global Trade — Finance", "email": _addr("EMAIL_FINANCE", "finance"), "function": "Invoices, payments, reconciliation"},
    {"key": "logistics", "name": "SAHJONY Global Trade — Logistics", "email": _addr("EMAIL_LOGISTICS", "logistics"), "function": "Freight, carriers, shipment coordination"},
]


def _mailbox_state() -> dict:
    return {
        "operational_mailbox": OPERATIONAL_MAILBOX,
        "provider": MAILBOX_PROVIDER,
        "agent_managed": MAILBOX_AGENT_MANAGED,
        "direct_platform_delivery_configured": DIRECT_MAIL_DELIVERY_CONFIGURED,
        "canonical_aliases_hosted_verified": CANONICAL_ALIASES_HOSTED_VERIFIED,
        "customer_visible_sender_mode": "canonical_department" if CANONICAL_ALIASES_HOSTED_VERIFIED else "SAHJONY Global Trade display name over authenticated operational mailbox",
        "policy": (
            "Use authenticated canonical @sahjony.com department senders only after hosted aliases/mailboxes are verified."
            if CANONICAL_ALIASES_HOSTED_VERIFIED
            else "Use the authenticated operational mailbox for delivery while assigning every conversation to its canonical SAHJONY Global Trade department. Never spoof an unverified @sahjony.com From address."
        ),
    }


@app.get("/business-email/health")
def email_registry_health():
    return {
        "status": "ok",
        "service": "business-email-registry",
        "version": "1.3.0",
        "canonical_domain": CANONICAL_DOMAIN,
        "canonical_website": CANONICAL_WEBSITE,
        "trade_os_url": TRADE_OS_URL,
        "operational_mailbox": _mailbox_state(),
        "departments": len(DEPARTMENTS),
        "active_departments": [d["key"] for d in DEPARTMENTS],
        "routing_mode": "department-aware canonical routing with authenticated transport",
    }


@app.get("/business-email/configuration")
def email_configuration():
    return {
        "status": "configured",
        "canonical_domain": CANONICAL_DOMAIN,
        "canonical_website": CANONICAL_WEBSITE,
        "owner_identity_email": OWNER_EMAIL,
        "mailbox": _mailbox_state(),
        "department_count": len(DEPARTMENTS),
        "departments": DEPARTMENTS,
        "safety": {
            "secrets_exposed": False,
            "unverified_from_spoofing": False,
            "sensitive_kyc_over_email": False,
            "binding_commitments_require_owner": True,
        },
    }


@app.get("/business-email/departments")
def email_departments():
    return {
        "canonical_domain": CANONICAL_DOMAIN,
        "canonical_website": CANONICAL_WEBSITE,
        "trade_os_url": TRADE_OS_URL,
        "operational_mailbox": _mailbox_state(),
        "departments": DEPARTMENTS,
        "note": "Six canonical business departments are active for routing now. Until domain mail hosting is verified, external delivery remains on the authenticated operational mailbox with SAHJONY Global Trade as the customer-facing display identity.",
    }
