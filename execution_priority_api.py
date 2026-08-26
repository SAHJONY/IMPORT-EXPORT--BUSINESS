from fastapi import FastAPI

app = FastAPI(title="SAHJONY Revenue Execution Priority", version="1.0.0", docs_url=None, redoc_url=None)

PRIORITIES = [
    {"rank": 1, "key": "sourcing", "name": "Managed Sourcing & Import/Export", "allocation_pct": 50, "objective": "Convert verified buyer demand into supplier quotes, protected economics, executable terms, and collected fees.", "primary_metric": "cash_collected", "links": ["/owner/profit-machine", "/owner-deal-command.html", "/owner/lead-search", "/owner/email"]},
    {"rank": 2, "key": "government_contracting", "name": "Government Contracting Services", "allocation_pct": 25, "objective": "Acquire paying small-business clients and move them from contractor readiness to qualified bid opportunities and post-award sourcing support.", "primary_metric": "paid_service_engagements", "links": ["/government-contracting", "/owner/crm-countries", "/owner/email"]},
    {"rank": 3, "key": "strategic_trade", "name": "Strategic Commodities & Energy", "allocation_pct": 15, "objective": "Advance only independently verifiable high-value transactions with enhanced diligence, documentary payment controls, and fee protection.", "primary_metric": "verified_quote_stage_opportunities", "links": ["/owner/energy", "/owner/energy/deal-flow", "/owner/energy/revenue"]},
    {"rank": 4, "key": "marketplace", "name": "Industrial Marketplace & Conversion", "allocation_pct": 10, "objective": "Use the marketplace as a demand-generation and RFQ layer without taking inventory risk.", "primary_metric": "qualified_rfq_conversion", "links": ["/marketplace", "/global-sourcing", "/owner/lead-search"]},
]

STAGE_GATES = [
    "Verified demand or paid service mandate",
    "Counterparty identity and authority evidence",
    "Technical/commercial requirement completeness",
    "Supplier capability or service delivery capacity",
    "SAHJONY compensation protected before controlled introduction where practical",
    "Payment/banking structure independently validated for elevated-risk transactions",
    "Compliance and sanctions controls passed where applicable",
    "Human approval for binding price, contract, payment, credit, KYC/KYB, sanctions or exclusivity decisions",
    "Execution evidence captured",
    "Revenue recognized only when actually collected",
]

KPI_7_DAY = {
    "qualified_buyer_requirements": 5,
    "complete_supplier_quotes": 3,
    "government_contract_client_profiles": 1,
    "fee_protection_or_paid_engagements": 1,
    "duplicate_followups": 0,
    "unsupported_status_promotions": 0,
}

KPI_30_DAY = {
    "qualified_buyer_requirements": 20,
    "capable_suppliers": 20,
    "serious_quote_stage_opportunities": 5,
    "government_contracting_clients": 3,
    "signed_or_paid_engagements": "1-3",
    "external_email_on_canonical_domain_target_pct": 100,
}

@app.get("/owner/execution-priority/health")
def execution_priority_health():
    return {
        "status": "ok",
        "service": "execution-priority-control-plane",
        "version": "1.0.0",
        "operating_mode": "revenue_first_zero_or_low_capital",
        "primary_metric": "cash_collected",
        "priorities": len(PRIORITIES),
        "binding_actions_fail_closed": True,
    }

@app.get("/owner/execution-priority/plan")
def execution_priority_plan():
    return {
        "status": "active",
        "business": "SAHJONY Global Trade",
        "doctrine": "Find demand -> qualify -> source -> protect economics -> negotiate -> document -> close -> collect -> repeat",
        "priorities": PRIORITIES,
        "stage_gates": STAGE_GATES,
        "kpi_7_day": KPI_7_DAY,
        "kpi_30_day": KPI_30_DAY,
        "development_gate": "Build or change product functionality only when it materially improves acquisition, qualification, closing, servicing, retention, compliance, or cash collection.",
        "inventory_policy": "No speculative inventory. Marketplace remains RFQ-first and supplier-fulfilled unless explicitly approved.",
        "status_policy": "Never mark QUALIFIED, APPROVED, CONTRACTED, PROVIDER_READY, E2E_VERIFIED, or REVENUE without documentary evidence.",
    }
