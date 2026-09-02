"""Governed agentic sales operating system for Sofia Reyes.

The model proposes; this module decides what may happen next.  It turns CRM,
conversation, relationship-memory and sales-brain signals into an explainable
mission plan without granting autonomous authority for binding commitments.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal


Authority = Literal["autonomous", "owner_approval", "prohibited"]

STAGE_ORDER = (
    "NEW", "ENGAGED", "QUALIFYING", "QUALIFIED", "RFQ_READY", "SOURCING",
    "QUOTED", "NEGOTIATING", "WON", "LOST", "OPTED_OUT",
)

BINDING_ACTIONS = {
    "release_quote", "accept_price", "grant_credit", "sign_contract",
    "change_beneficiary", "release_payment", "release_shipment",
    "clear_compliance", "mark_won",
}

PROHIBITED_ACTIONS = {
    "fabricate_evidence", "bypass_consent", "bypass_compliance",
    "bulk_unsolicited_outreach", "impersonate_human",
}

REQUIRED_TRADE_FIELDS = (
    "product", "specification", "quantity", "origin", "destination",
    "delivery_timeline", "target_budget",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _unique(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _clean(value)
        if text and text not in result:
            result.append(text)
    return result


def _known(memory: dict[str, Any], *names: str) -> str | None:
    known = memory.get("known") or {}
    for name in names:
        value = known.get(name)
        if isinstance(value, dict):
            value = value.get("value")
        if _clean(value):
            return _clean(value)
    return None


@dataclass(frozen=True)
class SalesAction:
    action: str
    authority: Authority
    reason: str
    success_signal: str
    tool: str | None = None
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class DealScore:
    total: int
    fit: int
    intent: int
    completeness: int
    momentum: int
    risk_penalty: int
    explanation: tuple[str, ...]


def action_authority(action: str) -> Authority:
    normalized = action.strip().lower()
    if normalized in PROHIBITED_ACTIONS:
        return "prohibited"
    if normalized in BINDING_ACTIONS:
        return "owner_approval"
    return "autonomous"


def score_opportunity(
    *,
    stage: str,
    known_fields: dict[str, Any],
    model_score: int | float | None,
    risk_flags: list[str],
    opted_out: bool,
) -> DealScore:
    if opted_out:
        return DealScore(0, 0, 0, 0, 0, 100, ("Contact opted out; selling stops.",))
    filled = sum(1 for field in REQUIRED_TRADE_FIELDS if _clean(known_fields.get(field)))
    completeness = round(30 * filled / len(REQUIRED_TRADE_FIELDS))
    stage_name = stage if stage in STAGE_ORDER else "NEW"
    stage_index = STAGE_ORDER.index(stage_name)
    intent = min(25, max(5, stage_index * 4))
    fit = min(25, max(0, round(float(model_score or 0) * 0.25)))
    momentum = 20 if stage_name in {"RFQ_READY", "SOURCING", "QUOTED", "NEGOTIATING"} else 10
    penalty = min(35, len(risk_flags) * 7)
    total = max(0, min(100, fit + intent + completeness + momentum - penalty))
    explanation = (
        f"{filled}/{len(REQUIRED_TRADE_FIELDS)} core trade fields known",
        f"pipeline stage {stage_name}",
        f"{len(risk_flags)} unresolved risk flags",
        "binding authority remains owner-governed",
    )
    return DealScore(total, fit, intent, completeness, momentum, penalty, explanation)


def _field_map(memory: dict[str, Any]) -> dict[str, str | None]:
    return {
        "product": _known(memory, "product", "product_need", "commodity"),
        "specification": _known(memory, "specification", "specifications", "grade"),
        "quantity": _known(memory, "quantity", "volume"),
        "origin": _known(memory, "origin", "source_country"),
        "destination": _known(memory, "destination", "destination_country", "delivery_location"),
        "delivery_timeline": _known(memory, "delivery_timeline", "timeline", "required_date"),
        "target_budget": _known(memory, "target_budget", "budget", "target_price"),
    }


def _next_actions(
    *, stage: str, missing: list[str], risks: list[str], opted_out: bool,
) -> list[SalesAction]:
    if opted_out:
        return [SalesAction(
            "record_opt_out", "autonomous", "Consent withdrawal overrides sales goals.",
            "contact is suppressed from automated follow-up", "crm",
        )]
    actions: list[SalesAction] = []
    if risks:
        actions.append(SalesAction(
            "resolve_risk", "autonomous", "Unresolved risk blocks commercial progression.",
            "risk is resolved or escalated with evidence", "compliance_research",
            tuple(risks[:5]),
        ))
    if missing:
        actions.append(SalesAction(
            "progressive_discovery", "autonomous", "Only missing decision-critical facts should be requested.",
            "one or two missing fields are captured", "whatsapp", tuple(missing[:2]),
        ))
    if stage in {"QUALIFIED", "RFQ_READY"} and not missing:
        actions.append(SalesAction(
            "prepare_rfq", "autonomous", "The requirement is complete enough for non-binding sourcing.",
            "structured RFQ draft and evidence checklist exist", "rfq_workspace",
        ))
    if stage in {"RFQ_READY", "SOURCING"}:
        actions.append(SalesAction(
            "compare_verified_offers", "autonomous", "A recommendation requires comparable supplier evidence.",
            "supplier, freight, compliance and landed-cost evidence are normalized", "supplier_workspace",
        ))
    if stage in {"QUOTED", "NEGOTIATING"}:
        actions.append(SalesAction(
            "advance_negotiation", "autonomous", "Non-binding objection handling can continue safely.",
            "buyer objection and next decision are recorded", "conversation",
        ))
        actions.append(SalesAction(
            "accept_price", "owner_approval", "Price acceptance creates a consequential commitment.",
            "owner approves verified terms", "owner_approval",
        ))
    if not actions:
        actions.append(SalesAction(
            "answer_and_qualify", "autonomous", "The relationship needs a useful response and one clear next step.",
            "customer receives a direct answer and momentum is preserved", "whatsapp",
        ))
    return actions[:4]


def orchestrate_sales_turn(
    *,
    lead_id: str | None,
    customer_text: str,
    stage: str,
    memory: dict[str, Any] | None,
    sales_intelligence: dict[str, Any] | None,
    crm_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory = memory or {}
    sales = sales_intelligence or {}
    crm = crm_context or {}
    normalized_stage = str(sales.get("recommended_stage") or stage or "NEW").upper()
    if normalized_stage not in STAGE_ORDER:
        normalized_stage = "QUALIFYING"
    opted_out = normalized_stage == "OPTED_OUT" or bool(memory.get("opted_out"))
    fields = _field_map(memory)
    model_missing = _unique(list(sales.get("missing_fields") or []))
    inferred_missing = [key for key, value in fields.items() if not value]
    missing = _unique(model_missing + inferred_missing)
    risks = _unique(list(sales.get("risk_flags") or []))
    score = score_opportunity(
        stage=normalized_stage,
        known_fields=fields,
        model_score=sales.get("opportunity_score"),
        risk_flags=risks,
        opted_out=opted_out,
    )
    actions = _next_actions(stage=normalized_stage, missing=missing, risks=risks, opted_out=opted_out)
    autonomous = [asdict(item) for item in actions if item.authority == "autonomous"]
    approvals = [asdict(item) for item in actions if item.authority == "owner_approval"]
    prohibited = [asdict(item) for item in actions if item.authority == "prohibited"]
    primary = actions[0]
    return {
        "os_version": "2.0.0",
        "plan_id": f"sofia:{lead_id or 'anonymous'}:{int(datetime.now(timezone.utc).timestamp())}",
        "created_at": _now(),
        "mission": "advance a legitimate opportunity to the next evidence-backed decision",
        "lead_id": lead_id,
        "stage": normalized_stage,
        "customer_message": customer_text[:1000],
        "deal_score": asdict(score),
        "known_trade_fields": fields,
        "missing_fields": missing[:7],
        "risk_flags": risks[:8],
        "next_best_action": asdict(primary),
        "autonomous_actions": autonomous,
        "approval_queue": approvals,
        "prohibited_actions": prohibited,
        "consent": {"opted_out": opted_out, "outbound_allowed": not opted_out},
        "evidence": {
            "crm_connected": bool(crm.get("crm_connected")),
            "supplier_offer_verified": False,
            "landed_cost_verified": False,
            "compliance_cleared": False,
        },
        "stop_rules": [
            "stop automated outreach immediately on opt-out",
            "never claim an external action without a confirmed tool result",
            "never release price, credit, contract, payment, compliance or shipment authority",
            "ask at most two new questions per customer turn",
        ],
        "success_criteria": [
            primary.success_signal,
            "CRM and relationship memory reflect the latest verified facts",
            "the customer has one clear next step",
        ],
        "binding_commitment_allowed": False,
    }


def sales_os_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "sofia-agentic-sales-os",
        "version": "2.0.0",
        "model_roles": {
            "strategic": "gpt-5.6-sol",
            "conversational": "gpt-5.6-sol",
            "high_volume": "gpt-5.6-sol",
        },
        "explainable_scoring": True,
        "progressive_discovery": True,
        "next_best_action": True,
        "authority_lanes": ["autonomous", "owner_approval", "prohibited"],
        "consent_fail_closed": True,
        "evidence_gated_progression": True,
        "binding_commitments": False,
        "codex_model_used": False,
    }
