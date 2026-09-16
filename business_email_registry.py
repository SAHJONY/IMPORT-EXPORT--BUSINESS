import os
from typing import Dict, List

from fastapi import FastAPI


app = FastAPI(title="SAHJONY Business Email Registry", version="2.0.0", docs_url=None, redoc_url=None)

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


# Verified department inboxes, confirmed configured by the owner (2026-09-16).
# These match the addresses published on the public site. Any department can be
# given a real inbox with an EMAIL_<KEY> env var (e.g. EMAIL_SOURCING); an
# explicit env value marks that department verified. Departments with an
# assigned address but unconfirmed mailbox hosting carry the address with
# verified=false and must not be used as From senders until confirmed.
VERIFIED_DEPARTMENT_EMAILS = {
    "sales": "ventas@sahjony.com",
    "cuba": "cuba@sahjony.com",
}

# Owner-approved standard inboxes for the worldwide business (2026-09-16).
# Addresses assigned; mailbox hosting pending owner confirmation.
PENDING_DEPARTMENT_EMAILS = {
    "sourcing": "sourcing@sahjony.com",
    "operations": "operations@sahjony.com",
    "compliance": "compliance@sahjony.com",
    "finance": "finance@sahjony.com",
    "logistics": "logistics@sahjony.com",
    "customer_success": "customersuccess@sahjony.com",
    "partnerships": "partnerships@sahjony.com",
    "marketing": "marketing@sahjony.com",
    "energy": "energy@sahjony.com",
    "executive": "executive@sahjony.com",
}

_DEPARTMENT_DEFS = [
    ("sales", "SAHJONY Global Trade — Sales", "New customers, quotes, commercial opportunities"),
    ("sourcing", "SAHJONY Global Trade — Sourcing", "Supplier discovery, RFQs, procurement"),
    ("operations", "SAHJONY Global Trade — Operations", "Trade execution, case coordination, milestones"),
    ("compliance", "SAHJONY Global Trade — Compliance", "Sanctions, export/import controls, release gates"),
    ("finance", "SAHJONY Global Trade — Finance", "Invoices, payments, reconciliation"),
    ("logistics", "SAHJONY Global Trade — Logistics", "Freight, carriers, shipment coordination"),
    ("customer_success", "SAHJONY Global Trade — Customer Success", "Customer onboarding, service questions, retention, post-sale follow-up"),
    ("partnerships", "SAHJONY Global Trade — Partnerships", "Partners, referrals, strategic alliances and channel relationships"),
    ("marketing", "SAHJONY Global Trade — Marketing", "Campaigns, media, content, brand and demand generation"),
    ("energy", "SAHJONY Global Trade — Energy", "Crude, fuels, energy products, origination and energy deal coordination"),
    ("cuba", "SAHJONY Global Trade — Cuba Trade Desk", "Cuba private-sector, MIPYME, consumer, fuels and corridor communications"),
    ("executive", "SAHJONY LLC — Executive Office", "Executive escalations, administration, cross-department coordination"),
]


def _department_entry(key: str, name: str, function: str) -> Dict:
    env_value = os.getenv(f"EMAIL_{key.upper()}", "").strip().lower()
    if env_value:
        return {"key": key, "name": name, "email": env_value, "verified": True, "inbox": OPERATIONAL_MAILBOX, "function": function}
    if key in VERIFIED_DEPARTMENT_EMAILS:
        return {"key": key, "name": name, "email": VERIFIED_DEPARTMENT_EMAILS[key], "verified": True, "inbox": OPERATIONAL_MAILBOX, "function": function}
    if key in PENDING_DEPARTMENT_EMAILS:
        return {"key": key, "name": name, "email": PENDING_DEPARTMENT_EMAILS[key], "verified": False, "inbox": OPERATIONAL_MAILBOX, "function": function}
    return {"key": key, "name": name, "email": "", "verified": False, "inbox": OPERATIONAL_MAILBOX, "function": function}


DEPARTMENTS: List[Dict] = [_department_entry(key, name, function) for key, name, function in _DEPARTMENT_DEFS]


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
        "version": "2.0.0",
        "canonical_domain": CANONICAL_DOMAIN,
        "canonical_website": CANONICAL_WEBSITE,
        "trade_os_url": TRADE_OS_URL,
        "operational_mailbox": _mailbox_state(),
        "departments": len(DEPARTMENTS),
        "active_departments": [d["key"] for d in DEPARTMENTS],
        "verified_departments": [d["key"] for d in DEPARTMENTS if d.get("verified")],
        "routing_mode": "enterprise department-aware canonical routing with authenticated transport",
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
    verified = [d for d in DEPARTMENTS if d.get("verified")]
    pending = [d for d in DEPARTMENTS if not d.get("verified")]
    return {
        "canonical_domain": CANONICAL_DOMAIN,
        "canonical_website": CANONICAL_WEBSITE,
        "trade_os_url": TRADE_OS_URL,
        "operational_mailbox": _mailbox_state(),
        "departments": DEPARTMENTS,
        "verified_count": len(verified),
        "verified_departments": [d["key"] for d in verified],
        "pending_departments": [d["key"] for d in pending],
        "note": (
            "Verified departments carry their owner-confirmed inbox. Departments without a verified "
            "inbox carry no address and route inbound to the authenticated operational mailbox. "
            "Until domain mail hosting is verified, external delivery remains on the operational mailbox "
            "with SAHJONY Global Trade as the customer-facing display identity; never spoof an unverified @sahjony.com From address."
        ),
    }
