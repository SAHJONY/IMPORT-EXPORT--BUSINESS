from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Literal

from global_enterprise_intelligence import MATERIAL_DECISION_GATES

Decision = Literal["GO", "HOLD", "BLOCK"]
EvidenceState = Literal["verified", "missing", "stale", "failed", "not_applicable"]


@dataclass
class EvidenceItem:
    key: str
    state: EvidenceState = "missing"
    source: str | None = None
    effective_at: str | None = None
    expires_at: str | None = None
    note: str | None = None


@dataclass
class DealDecisionContext:
    decision_type: str
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
    expected_revenue: float | None = None
    expected_cost: float | None = None
    expected_margin: float | None = None
    as_of: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_evidence(items: list[EvidenceItem | dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items or []:
        if isinstance(item, EvidenceItem):
            row = asdict(item)
        elif isinstance(item, dict):
            row = dict(item)
        else:
            continue
        key = str(row.get("key") or "").strip()
        if key:
            result[key] = row
    return result


def evaluate_deal(
    ctx: DealDecisionContext,
    evidence: list[EvidenceItem | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    decision_type = (ctx.decision_type or "").strip().lower()
    required = list(MATERIAL_DECISION_GATES.get(decision_type, []))
    supplied = _normalize_evidence(evidence)

    core_required = ["origin_country", "destination_country", "product", "buyer", "seller", "payment_terms", "incoterm"]
    ctx_data = asdict(ctx)
    missing_context = [key for key in core_required if not ctx_data.get(key)]

    failed = []
    stale = []
    missing = []
    verified = []

    for key in required:
        item = supplied.get(key)
        state = str((item or {}).get("state") or "missing").lower()
        if state == "verified":
            verified.append(key)
        elif state == "failed":
            failed.append(key)
        elif state == "stale":
            stale.append(key)
        elif state == "not_applicable":
            verified.append(key)
        else:
            missing.append(key)

    # A failed material control is an explicit BLOCK. Missing/stale evidence is HOLD.
    if failed:
        decision: Decision = "BLOCK"
        reason = "One or more required material controls failed."
    elif missing_context or missing or stale:
        decision = "HOLD"
        reason = "Required context or current evidence is incomplete."
    else:
        decision = "GO"
        reason = "Required evidence gates are verified for this decision type."

    # Margin is an additional commercial gate when a binding quote is evaluated.
    if decision_type == "binding_quote" and ctx.expected_margin is not None and ctx.expected_margin < 0:
        decision = "BLOCK"
        failed = list(dict.fromkeys([*failed, "negative_margin"]))
        reason = "The proposed quote has negative expected margin."

    return {
        "status": "evaluated",
        "decision": decision,
        "reason": reason,
        "decision_type": decision_type,
        "context": ctx_data,
        "required_evidence": required,
        "verified_evidence": verified,
        "missing_evidence": missing,
        "stale_evidence": stale,
        "failed_evidence": failed,
        "missing_context": missing_context,
        "binding_action_allowed_by_evidence": decision == "GO",
        "governance_still_applies": True,
        "source_currentness_required": True,
        "evaluated_at": _now(),
        "next_action": (
            "Stop the transaction path and remediate failed controls before reconsideration."
            if decision == "BLOCK"
            else "Collect or refresh missing evidence, then re-run the decision engine."
            if decision == "HOLD"
            else "Proceed only within configured authority; retain all evidence and governance controls."
        ),
    }


def decision_engine_profile() -> dict[str, Any]:
    return {
        "status": "configured",
        "service": "global-deal-decision-engine",
        "version": "1.0.0",
        "decisions": ["GO", "HOLD", "BLOCK"],
        "material_decision_types": sorted(MATERIAL_DECISION_GATES.keys()),
        "principles": [
            "GO requires verified evidence for every required material gate.",
            "HOLD is used for missing, stale, contradictory or incomplete evidence.",
            "BLOCK is used for explicit failed controls or clearly non-viable commercial conditions.",
            "A GO evidence decision never bypasses owner, legal, financial or compliance authority controls.",
            "All decisions require durable evidence and source-currentness for material execution.",
        ],
        "updated_at": _now(),
    }
