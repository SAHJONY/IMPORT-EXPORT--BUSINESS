import os
from typing import Dict, List

from fastapi import FastAPI


app = FastAPI(title="SAHJONY Business Email Registry", version="1.1.0", docs_url=None, redoc_url=None)

CANONICAL_DOMAIN = os.getenv("BUSINESS_CANONICAL_DOMAIN", "sahjony.com").strip().lower()
CANONICAL_WEBSITE = os.getenv("BUSINESS_CANONICAL_WEBSITE", "https://www.sahjony.com").strip()
TRADE_OS_URL = os.getenv("TRADE_OS_URL", "https://trade.sahjony.com").strip()
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "sahjonycapitalllc@outlook.com").strip().lower()


def _canonical(local_part: str) -> str:
    return f"{local_part}@{CANONICAL_DOMAIN}"


def _addr(env_name: str, local_part: str) -> str:
    return os.getenv(env_name, _canonical(local_part)).strip().lower()


DEPARTMENTS: List[Dict[str, str]] = [
    {"key": "executive", "name": "Executive Office", "email": _addr("EMAIL_EXECUTIVE", "executive"), "function": "Owner, executive decisions, escalations"},
    {"key": "general", "name": "General Inquiries", "email": _addr("EMAIL_GENERAL", "info"), "function": "General business inquiries and routing"},
    {"key": "sales", "name": "Sales & Commercial", "email": _addr("EMAIL_SALES", "sales"), "function": "New customers, quotes, commercial opportunities"},
    {"key": "sourcing", "name": "Global Sourcing & Procurement", "email": _addr("EMAIL_SOURCING", "sourcing"), "function": "Supplier discovery, RFQs, procurement"},
    {"key": "operations", "name": "Managed Trade Operations", "email": _addr("EMAIL_OPERATIONS", "operations"), "function": "Trade execution, case coordination, milestones"},
    {"key": "compliance", "name": "Trade Compliance", "email": _addr("EMAIL_COMPLIANCE", "compliance"), "function": "Sanctions, export/import controls, release gates"},
    {"key": "documents", "name": "Trade Documents", "email": _addr("EMAIL_DOCUMENTS", "documents"), "function": "Commercial documents, certificates, records"},
    {"key": "logistics", "name": "Logistics & Shipping", "email": _addr("EMAIL_LOGISTICS", "logistics"), "function": "Freight, carriers, shipment coordination"},
    {"key": "finance", "name": "Finance & Reconciliation", "email": _addr("EMAIL_FINANCE", "finance"), "function": "Invoices, payments, reconciliation"},
    {"key": "accounts", "name": "Accounts Payable / Receivable", "email": _addr("EMAIL_ACCOUNTS", "accounts"), "function": "Bills, vendor/customer account statements"},
    {"key": "customer_success", "name": "Customer Success", "email": _addr("EMAIL_CUSTOMER_SUCCESS", "customers"), "function": "Customer updates, service coordination"},
    {"key": "support", "name": "Platform Support", "email": _addr("EMAIL_SUPPORT", "support"), "function": "Application access and technical support"},
    {"key": "partnerships", "name": "Partners & Intermediaries", "email": _addr("EMAIL_PARTNERSHIPS", "partners"), "function": "Broker, forwarder, insurer, bank and channel partners"},
    {"key": "us_import", "name": "U.S. Import Desk", "email": _addr("EMAIL_US_IMPORT", "imports"), "function": "U.S. import operations, customs coordination"},
    {"key": "cuba", "name": "Cuba Private Sector Desk", "email": _addr("EMAIL_CUBA", "cuba"), "function": "Eligible Cuba private-sector commercial inquiries"},
    {"key": "legal", "name": "Legal & Contracts", "email": _addr("EMAIL_LEGAL", "legal"), "function": "Contracts, terms, legal notices"},
    {"key": "technology", "name": "AI & Technology", "email": _addr("EMAIL_TECHNOLOGY", "technology"), "function": "AI systems, integrations, platform engineering"},
    {"key": "security", "name": "Security", "email": _addr("EMAIL_SECURITY", "security"), "function": "Security incidents, access-control escalation"},
    {"key": "people", "name": "People & Administration", "email": _addr("EMAIL_PEOPLE", "hr"), "function": "Hiring, staff administration, internal operations"},
]


@app.get("/business-email/health")
def email_registry_health():
    return {
        "status": "ok",
        "service": "business-email-registry",
        "canonical_domain": CANONICAL_DOMAIN,
        "canonical_website": CANONICAL_WEBSITE,
        "trade_os_url": TRADE_OS_URL,
        "owner_identity_email": OWNER_EMAIL,
        "departments": len(DEPARTMENTS),
        "routing_mode": "canonical sahjony.com departmental identities with environment overrides",
        "mailboxes_require_provider_configuration": True,
    }


@app.get("/business-email/departments")
def email_departments():
    return {
        "canonical_domain": CANONICAL_DOMAIN,
        "canonical_website": CANONICAL_WEBSITE,
        "trade_os_url": TRADE_OS_URL,
        "owner_identity_email": OWNER_EMAIL,
        "departments": DEPARTMENTS,
        "note": "Department identities default to @sahjony.com. Create matching aliases/shared mailboxes with the domain mail provider, or override individual EMAIL_* variables. The Owner login identity remains separate unless intentionally changed.",
    }
