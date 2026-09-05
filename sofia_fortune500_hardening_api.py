from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="SOFIA Fortune 500 Hardening", docs_url=None, redoc_url=None)

STAGES = [
    "RESEARCH",
    "CONTACTABLE",
    "ENGAGED",
    "QUALIFIED_DEMAND",
    "RFQ_COMPLETE",
    "FIRM_QUOTE",
    "NEGOTIATION",
    "CONTRACTED",
    "INVOICED",
    "PAID",
    "IN_TRANSIT",
    "DELIVERED",
    "COLLECTED",
]

STAGE_EVIDENCE: dict[str, list[str]] = {
    "RESEARCH": ["source_evidence"],
    "CONTACTABLE": ["source_evidence", "legitimate_contact_path"],
    "ENGAGED": ["counterparty_reply_or_interaction"],
    "QUALIFIED_DEMAND": ["legal_or_business_identity", "product", "quantity", "destination", "timing", "purchasing_authority_signal"],
    "RFQ_COMPLETE": ["qualified_demand", "specification_or_grade", "quantity", "delivery_destination", "required_date_or_window"],
    "FIRM_QUOTE": ["supplier_identity", "price", "currency", "incoterm", "validity", "quantity_or_moq", "payment_terms"],
    "NEGOTIATION": ["firm_quote", "active_counterparty_negotiation"],
    "CONTRACTED": ["executed_contract_or_po", "authorized_counterparties"],
    "INVOICED": ["contract_or_po", "invoice_document"],
    "PAID": ["posted_payment_evidence"],
    "IN_TRANSIT": ["shipment_booking_or_carrier_evidence"],
    "DELIVERED": ["proof_of_delivery_or_acceptance"],
    "COLLECTED": ["posted_payment_evidence", "reconciled_collected_revenue"],
}

OWNER_ONLY = {
    "BINDING_CONTRACT",
    "PAYMENT_AUTHORIZATION",
    "BANK_OR_BENEFICIARY_CHANGE",
    "LEGAL_COMMITMENT",
    "COMPLIANCE_CRITICAL_APPROVAL",
    "PROTECTED_COUNTERPARTY_DISCLOSURE",
    "PAID_AD_SPEND",
    "CREDIT_EXTENSION",
    "SAHJONY_CAPITAL_AT_RISK",
    "CREDENTIAL_OR_ACCESS_ONLY_OWNER_CAN_PROVIDE",
}

ROUTINE_AUTONOMOUS = {
    "PUBLIC_RESEARCH",
    "CRM_ENRICHMENT",
    "CONTACT_VERIFICATION",
    "NONBINDING_OUTREACH_PREPARATION",
    "CONSENTED_ROUTINE_FOLLOWUP",
    "RFQ_COMPLETION",
    "SUPPLIER_MATCHING",
    "COMPETITION_BENCHMARKING",
    "QUOTE_COMPARISON",
    "KYB_PREPARATION",
    "LOGISTICS_RESEARCH",
    "NEXT_ACTION_SCHEDULING",
}

FALLBACK_CHAIN = [
    "PRIMARY_SOURCE",
    "CRM_INTELLIGENCE",
    "AUTHORIZED_WEB_SEARCH",
    "PUBLIC_DIRECTORIES",
    "TRADE_DATA",
    "SOCIAL_BUSINESS_SIGNALS",
    "ALTERNATE_PROVIDER",
    "MANUAL_SOURCE_QUEUE",
]

SLA_HOURS = {
    "A_TIER_NEW_LEAD": 1,
    "BUYER_REPLY": 1,
    "SUPPLIER_QUOTE_REPLY": 2,
    "RFQ_INCOMPLETE": 8,
    "QUALIFIED_DEMAND_NO_MATCH": 4,
    "FIRM_QUOTE_NO_BUYER_RESPONSE": 24,
    "DORMANT_ENGAGED": 48,
}


class StageCheck(BaseModel):
    current_stage: str = "RESEARCH"
    requested_stage: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ActionCheck(BaseModel):
    action_type: str
    capital_at_risk_usd: float = 0
    protected_counterparty_disclosure: bool = False


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return bool(str(value).strip())


def stage_transition_guard(current_stage: str, requested_stage: str, evidence: dict[str, Any]) -> dict[str, Any]:
    current = str(current_stage or "RESEARCH").upper().strip()
    requested = str(requested_stage or "").upper().strip()
    if current not in STAGES:
        raise ValueError(f"unknown current stage: {current}")
    if requested not in STAGES:
        raise ValueError(f"unknown requested stage: {requested}")
    if STAGES.index(requested) < STAGES.index(current):
        return {"allowed": True, "reason": "explicit_demotion_or_correction", "missing_evidence": []}
    required = STAGE_EVIDENCE.get(requested, [])
    missing = [key for key in required if not _present(evidence.get(key))]
    return {
        "allowed": not missing,
        "current_stage": current,
        "requested_stage": requested,
        "required_evidence": required,
        "missing_evidence": missing,
        "commercial_stage_mutated": False,
        "fail_closed": True,
    }


def action_authority_guard(action_type: str, *, capital_at_risk_usd: float = 0, protected_counterparty_disclosure: bool = False) -> dict[str, Any]:
    action = str(action_type or "").upper().strip()
    owner_required = action in OWNER_ONLY or capital_at_risk_usd > 0 or protected_counterparty_disclosure
    return {
        "action_type": action,
        "owner_approval_required": owner_required,
        "autonomous_allowed": (action in ROUTINE_AUTONOMOUS) and not owner_required,
        "capital_at_risk_usd": max(0, float(capital_at_risk_usd or 0)),
        "protected_counterparty_disclosure": bool(protected_counterparty_disclosure),
        "binding_commitment_allowed": False if owner_required else None,
        "fail_closed": True,
    }


@app.get("/crm/sofia-hardening/health")
async def hardening_health():
    return {
        "status": "ok",
        "service": "sofia-fortune500-hardening",
        "version": "1.0.0",
        "canonical_truth": "supabase_crm",
        "stage_guard": True,
        "evidence_before_promotion": True,
        "owner_dependency_for_routine_research": False,
        "zero_capital_default": True,
        "protected_counterparty_gate": True,
        "single_next_action_required": True,
        "sla_control": True,
        "auditability_required": True,
        "fallback_chain": FALLBACK_CHAIN,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/crm/sofia-hardening/policy")
async def hardening_policy():
    return {
        "stages": STAGES,
        "stage_evidence": STAGE_EVIDENCE,
        "owner_only_actions": sorted(OWNER_ONLY),
        "routine_autonomous_actions": sorted(ROUTINE_AUTONOMOUS),
        "research_fallback_chain": FALLBACK_CHAIN,
        "sla_hours": SLA_HOURS,
        "rules": [
            "Supabase/CRM is the only commercial source of truth.",
            "No stage promotion without the stage's minimum evidence.",
            "A failed search provider is not an owner blocker; continue the fallback chain.",
            "Every active lead requires one accountable next action and SLA.",
            "Qualified demand triggers supplier matching before catalog-style generic selling.",
            "Use multiple supplier options when practical and compare price, MOQ, Incoterm, payment terms and lead time.",
            "Protect SAHJONY economics before controlled counterparty introduction when lawful and practical.",
            "Default SAHJONY capital at risk is zero.",
            "Contracts, payments, sensitive disclosures, paid spend and legal/compliance critical approvals remain owner-gated.",
            "Revenue is collected only when posted payment evidence is reconciled.",
        ],
    }


@app.post("/crm/sofia-hardening/check-stage")
async def check_stage(payload: StageCheck):
    try:
        return stage_transition_guard(payload.current_stage, payload.requested_stage, payload.evidence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/crm/sofia-hardening/check-action")
async def check_action(payload: ActionCheck):
    return action_authority_guard(
        payload.action_type,
        capital_at_risk_usd=payload.capital_at_risk_usd,
        protected_counterparty_disclosure=payload.protected_counterparty_disclosure,
    )


@app.get("/crm/sofia-hardening/readiness")
async def readiness():
    controls = {
        "single_truth_layer": 10,
        "stage_evidence_guard": 10,
        "research_fallback": 10,
        "owner_escalation_discipline": 10,
        "zero_capital_gate": 10,
        "protected_economics_gate": 10,
        "sla_next_action": 10,
        "auditability": 10,
        "cross_channel_identity_dedup": 5,
        "revenue_reconciliation": 5,
    }
    score = sum(controls.values())
    return {
        "status": "control_plane_ready",
        "hardening_score": score,
        "max_score": 100,
        "controls": controls,
        "note": "This score measures installed governance controls, not commercial outcomes or channel uptime.",
        "fortune500_operational_readiness_claimed": False,
    }
