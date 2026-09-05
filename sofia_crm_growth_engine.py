from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sofia_research_policy import research_next_action, research_policy
from sofia_fortune500_hardening_api import (
    FALLBACK_CHAIN,
    SLA_HOURS,
    action_authority_guard,
    stage_transition_guard,
)

BLOCKED_STATUSES = {"DO_NOT_CONTACT", "OPTED_OUT", "LOST"}
ACTIVE_STATUSES = {"NEW", "PROSPECT", "FOLLOW_UP_DUE", "REPLIED", "QUALIFIED_LEAD"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _consented(lead: dict[str, Any]) -> bool:
    consent = lead.get("consent_to_business_contact")
    if consent is True:
        return True
    return _text(lead.get("consent_status")).upper() in {"CONSENTED", "TRANSACTIONAL_ONLY"}


def _evidence(lead: dict[str, Any], *, has_intake: bool) -> dict[str, Any]:
    return {
        "source_evidence": lead.get("source_url") or lead.get("source") or lead.get("evidence"),
        "legitimate_contact_path": lead.get("email") or lead.get("phone") or lead.get("website"),
        "counterparty_reply_or_interaction": lead.get("last_reply_at") or lead.get("engagement_evidence"),
        "legal_or_business_identity": lead.get("legal_name") or lead.get("business_name") or lead.get("buyer_company"),
        "product": lead.get("product_need") or lead.get("product_description") or lead.get("product"),
        "quantity": lead.get("quantity") or lead.get("volume") or lead.get("container_count"),
        "destination": lead.get("destination") or lead.get("destination_port") or lead.get("country_code"),
        "timing": lead.get("required_date") or lead.get("timing") or lead.get("delivery_window"),
        "purchasing_authority_signal": lead.get("purchasing_authority_signal") or lead.get("authorized_contact") or has_intake,
        "qualified_demand": has_intake,
        "specification_or_grade": lead.get("specification") or lead.get("grade") or lead.get("presentation"),
        "delivery_destination": lead.get("destination") or lead.get("destination_port"),
        "required_date_or_window": lead.get("required_date") or lead.get("delivery_window") or lead.get("timing"),
        "supplier_identity": lead.get("supplier_identity"),
        "price": lead.get("firm_price"),
        "currency": lead.get("currency"),
        "incoterm": lead.get("incoterm"),
        "validity": lead.get("quote_validity"),
        "quantity_or_moq": lead.get("moq") or lead.get("quantity"),
        "payment_terms": lead.get("payment_terms"),
        "firm_quote": lead.get("firm_quote_evidence"),
        "active_counterparty_negotiation": lead.get("negotiation_evidence"),
        "executed_contract_or_po": lead.get("executed_contract") or lead.get("purchase_order"),
        "authorized_counterparties": lead.get("authorized_counterparties"),
        "contract_or_po": lead.get("executed_contract") or lead.get("purchase_order"),
        "invoice_document": lead.get("invoice_document"),
        "posted_payment_evidence": lead.get("posted_payment_evidence"),
        "shipment_booking_or_carrier_evidence": lead.get("shipment_booking") or lead.get("carrier_evidence"),
        "proof_of_delivery_or_acceptance": lead.get("proof_of_delivery") or lead.get("acceptance_evidence"),
        "reconciled_collected_revenue": lead.get("reconciled_collected_revenue"),
    }


def _recommended_stage(lead: dict[str, Any], *, has_intake: bool) -> str:
    explicit = _text(lead.get("commercial_stage") or lead.get("deal_stage")).upper()
    if explicit:
        return explicit
    status = _text(lead.get("sales_status") or lead.get("status") or "NEW").upper()
    if has_intake:
        return "QUALIFIED_DEMAND"
    if status in {"REPLIED", "QUALIFIED_LEAD"}:
        return "ENGAGED"
    if _text(lead.get("email") or lead.get("phone") or lead.get("website")):
        return "CONTACTABLE"
    return "RESEARCH"


def score_crm_lead(lead: dict[str, Any], *, has_intake: bool = False) -> dict[str, Any]:
    status = _text(lead.get("sales_status") or lead.get("status") or "NEW").upper()
    blocked = status in BLOCKED_STATUSES or _text(lead.get("consent_status")).upper() in {"REVOKED", "DO_NOT_CONTACT"}
    contactable = bool(_text(lead.get("email")) or _text(lead.get("phone")) or _text(lead.get("website")))
    consented = _consented(lead)
    evidence = _evidence(lead, has_intake=has_intake)
    recommended_stage = _recommended_stage(lead, has_intake=has_intake)
    try:
        stage_guard = stage_transition_guard("RESEARCH", recommended_stage, evidence)
    except ValueError:
        recommended_stage = "RESEARCH"
        stage_guard = stage_transition_guard("RESEARCH", "RESEARCH", evidence)

    verified_demand = bool(has_intake and stage_guard.get("allowed"))
    components = {
        "active_status": 15 if status in ACTIVE_STATUSES else 5,
        "contactability": 15 if contactable else 0,
        "business_identity": 15 if _text(lead.get("legal_name") or lead.get("business_name") or lead.get("buyer_company")) else 0,
        "commercial_need": 25 if verified_demand else (10 if _text(lead.get("product_need") or lead.get("product_description")) else 0),
        "engagement": 15 if status in {"REPLIED", "QUALIFIED_LEAD", "FOLLOW_UP_DUE"} else 0,
        "consent": 5 if consented else 0,
        "source_evidence": 10 if evidence.get("source_evidence") else 0,
    }
    score = 0 if blocked else min(100, sum(components.values()))

    if blocked:
        next_action = "Do not contact; preserve suppression state."
        sla_hours = None
    elif verified_demand:
        next_action = "Launch supplier matching, competition benchmark, KYB preparation and protected-economics work; keep all commitments non-binding."
        sla_hours = SLA_HOURS["QUALIFIED_DEMAND_NO_MATCH"]
    elif contactable and consented:
        next_action = "Send or queue one personalized, non-binding Sofia discovery follow-up and continue enrichment; request product, quantity, specification, destination and timing."
        sla_hours = SLA_HOURS["A_TIER_NEW_LEAD"] if score >= 70 else SLA_HOURS["RFQ_INCOMPLETE"]
    elif contactable:
        next_action = "Continue autonomous enrichment and identify a consent-compatible engagement path; do not transfer research responsibility to the owner."
        sla_hours = SLA_HOURS["RFQ_INCOMPLETE"]
    else:
        next_action = research_next_action(has_contact=False, has_verified_demand=False)
        sla_hours = SLA_HOURS["RFQ_INCOMPLETE"]

    research_authority = action_authority_guard("PUBLIC_RESEARCH")
    return {
        "score": score,
        "components": components,
        "status": status,
        "blocked": blocked,
        "contactable": contactable,
        "consented": consented,
        "recommended_stage": recommended_stage,
        "stage_guard": stage_guard,
        "verified_demand": verified_demand,
        "autonomous_outreach_allowed": bool(contactable and consented and not blocked),
        "autonomous_research_required": bool(not blocked),
        "autonomous_research_allowed": research_authority["autonomous_allowed"],
        "owner_research_dependency": False,
        "next_best_action": next_action,
        "next_action_sla_hours": sla_hours,
        "capital_at_risk_usd": 0,
        "binding_commitment_allowed": False,
    }


def build_growth_queue(accounts: list[dict[str, Any]], intakes: list[dict[str, Any]], external: list[dict[str, Any]], whatsapp: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    intake_ids = {str(row.get("customer_id")) for row in intakes if row.get("customer_id")}
    queue: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, rows in (("customer_crm", accounts), ("external_research", external), ("whatsapp_crm", whatsapp or [])):
        for lead in rows:
            if lead.get("owner_private") is True or _text(lead.get("actor_role")).lower() == "owner":
                continue
            identity = _text(lead.get("customer_id") or lead.get("id") or lead.get("lead_id") or lead.get("email") or lead.get("phone"))
            if not identity or identity in seen:
                continue
            seen.add(identity)
            assessment = score_crm_lead(lead, has_intake=identity in intake_ids)
            queue.append({
                "lead_ref": identity,
                "source": source,
                "company": _text(lead.get("legal_name") or lead.get("business_name") or lead.get("buyer_company") or lead.get("buyer_name")),
                "contact_name": _text(lead.get("contact_name") or lead.get("buyer_name")),
                "country": _text(lead.get("country_code") or lead.get("buyer_country") or lead.get("destination")),
                "assessment": assessment,
            })
    queue.sort(key=lambda row: (-int(row["assessment"]["score"]), row["lead_ref"]))
    return queue


def growth_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "sofia-crm-growth-engine",
        "version": "2.0.0-hardening",
        "canonical_truth": "supabase_crm",
        "primary_brain": "gpt-5.6-sol",
        "anthropic_role": "independent_review_for_high_risk_or_ambiguous_leads",
        "crm_sources": ["customer_accounts", "customer_trade_intakes", "external_trade_prospects", "whatsapp_leads"],
        "capabilities": ["deduplicate", "score", "prioritize", "research", "qualify", "prepare_outreach", "schedule_follow_up", "stage_evidence_guard", "sla_control", "alternate_source_fallback", "manual_source_queue"],
        "consent_enforced": True,
        "opt_out_enforced": True,
        "unsolicited_autonomous_outreach": False,
        "autonomous_nonbinding_research": True,
        "owner_research_dependency": False,
        "commercial_stage_fail_closed": True,
        "zero_capital_default": True,
        "binding_commitments_fail_closed": True,
        "fallback_chain": FALLBACK_CHAIN,
        "sla_hours": SLA_HOURS,
        "research_policy": research_policy(),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
