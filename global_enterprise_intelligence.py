from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

ENTERPRISE_DOMAINS = [
    "corporate_strategy",
    "market_intelligence",
    "sales_and_account_management",
    "sourcing_and_procurement",
    "supplier_risk",
    "trade_compliance",
    "sanctions_and_restricted_parties",
    "customs_and_tariff_classification",
    "import_export_licensing",
    "country_regulation",
    "banking_and_payment_routes",
    "treasury_and_fx",
    "credit_and_counterparty_risk",
    "tax_vat_gst_withholding",
    "contracts_and_incoterms",
    "insurance_and_trade_credit",
    "ocean_air_ground_logistics",
    "ports_terminals_and_warehousing",
    "food_pharma_sps_quality",
    "product_certification_and_labeling",
    "quality_assurance_and_claims",
    "finance_accounting_and_margin",
    "working_capital_and_cash_conversion",
    "pricing_and_revenue_management",
    "data_governance_and_privacy",
    "cybersecurity_and_access_control",
    "application_reliability_and_incident_response",
    "business_continuity_and_disaster_recovery",
    "legal_entity_and_corporate_governance",
    "hr_vendor_and_contractor_governance",
    "anti_bribery_aml_kyc_and_ethics",
    "government_affairs_and_geopolitical_risk",
    "esg_environmental_and_supply_chain_due_diligence",
    "customer_success_and_service_recovery",
    "communications_reputation_and_crisis_management",
    "executive_reporting_and_board_intelligence",
]

MATERIAL_DECISION_GATES = {
    "binding_quote": ["verified_supplier_cost", "verified_freight", "verified_payment_route", "regulatory_clearance", "margin_check"],
    "supplier_commitment": ["supplier_due_diligence", "sanctions_screening", "commercial_terms_verified"],
    "customer_credit": ["credit_risk_review", "payment_terms_authorized", "exposure_limit"],
    "shipment_release": ["export_authority", "import_authority", "documents_complete", "restricted_party_screening"],
    "funds_movement": ["bank_details_verified", "beneficiary_verified", "dual_control", "fraud_check"],
    "contract_acceptance": ["legal_review", "commercial_review", "authority_verified"],
    "country_entry": ["country_risk_review", "tax_and_entity_review", "regulatory_map", "banking_route"],
    "production_change": ["change_plan", "rollback_plan", "security_review", "health_check"],
}

SOURCE_CLASSES = {
    "tier_1": [
        "official_gazette",
        "customs_authority",
        "ministry_or_regulator",
        "central_bank_or_financial_regulator",
        "sanctions_authority",
        "export_control_authority",
        "tax_authority",
        "food_or_health_authority",
        "port_or_transport_authority",
    ],
    "tier_2": ["multilateral_body", "recognized_standard_setter", "official_trade_portal"],
    "tier_3": ["major_law_firm", "major_accounting_firm", "major_bank_guidance", "reputable_trade_association"],
}

@dataclass
class EnterpriseDecisionContext:
    origin_country: str | None = None
    transit_countries: list[str] | None = None
    destination_country: str | None = None
    product: str | None = None
    hs_code: str | None = None
    seller: str | None = None
    buyer: str | None = None
    banks: list[str] | None = None
    payment_terms: str | None = None
    incoterm: str | None = None
    currency: str | None = None
    shipment_mode: str | None = None
    decision_type: str | None = None
    as_of: str | None = None


def enterprise_intelligence_profile() -> dict[str, Any]:
    return {
        "status": "configured",
        "service": "global-enterprise-intelligence",
        "standard": "elite_global_company_operating_discipline",
        "domains": ENTERPRISE_DOMAINS,
        "domain_count": len(ENTERPRISE_DOMAINS),
        "source_classes": SOURCE_CLASSES,
        "material_decision_gates": MATERIAL_DECISION_GATES,
        "rules": [
            "Do not treat model memory as regulatory evidence.",
            "Use current authoritative sources for material country, legal, customs, banking, tax, sanctions and compliance decisions.",
            "Separate verified facts, counterparty claims, assumptions and unknowns.",
            "Every material decision must have an effective date and source-currentness status.",
            "Fail closed when required evidence is missing, stale, contradictory or jurisdictionally unclear.",
            "No binding quote without verified supplier cost, freight, regulatory path, payment route and margin.",
            "No shipment release without export/import authority, documentation and restricted-party screening.",
            "No funds movement or bank-detail change without independent verification and dual control.",
            "No silent completion: durable evidence is required before an operation is marked complete.",
        ],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def decision_checklist(ctx: EnterpriseDecisionContext) -> dict[str, Any]:
    data = asdict(ctx)
    required = [
        "origin_country",
        "destination_country",
        "product",
        "buyer",
        "seller",
        "payment_terms",
        "incoterm",
        "decision_type",
    ]
    missing = [k for k in required if not data.get(k)]
    gates = MATERIAL_DECISION_GATES.get((ctx.decision_type or "").strip().lower(), [])
    return {
        "context": data,
        "missing_core_fields": missing,
        "required_evidence_gates": gates,
        "regulatory_research_required": True,
        "country_currentness_required": True,
        "binding_action_allowed": False if missing or gates else False,
        "next_action": "Collect missing context and verify authoritative evidence before material execution.",
    }
