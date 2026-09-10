"""SAHJONY RFQ Contact Recovery Engine.

Purpose:
- classify RFQ delivery failures and temporary delays
- rank alternate contact channels without inventing addresses
- normalize logistics pricing to USD/kg when enough data exists
- separate upstream logistics cost from SAHJONY customer sell price
- apply a conservative Cuba/U.S.-person sanctions gate before a provider is usable
- produce a fail-closed resend recommendation

This module intentionally does NOT send email, scrape private data, or make legal
conclusions. It consumes verified evidence gathered by Gmail/web/CRM connectors.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Iterable, Optional

LB_PER_KG = Decimal("2.2046226218")


class DeliveryState(str, Enum):
    DELIVERED = "delivered"
    TEMPORARY_DELAY = "temporary_delay"
    PERMANENT_FAILURE = "permanent_failure"
    UNKNOWN = "unknown"


class RouteLeg(str, Enum):
    PICKUP = "pickup"
    INLAND = "inland"
    FEEDER = "feeder"
    OCEAN = "ocean"
    PORT_DESTINATION = "port_destination"
    CUSTOMS = "customs"
    WAREHOUSE_DECONSOLIDATION = "warehouse_deconsolidation"
    DRAYAGE = "drayage"
    FINAL_MILE = "final_mile"


BLOCKED_OR_HIGH_RISK_CUBA_NAMES = {
    "gemar",
    "gecomex",
    "gaesa",
    "grupo caudal",
    "transcargo",
    "ausa",
    "almacenes universales",
    "cubacontrol",
}


@dataclass(frozen=True)
class Evidence:
    source: str
    value: str
    verified: bool = False
    timestamp: Optional[str] = None


@dataclass
class ContactCandidate:
    value: str
    channel: str  # email, phone, whatsapp, web_form, named_contact
    source: str
    verified: bool
    same_legal_entity: Optional[bool] = None
    role_match: bool = False
    notes: str = ""

    @property
    def score(self) -> int:
        score = 0
        if self.verified:
            score += 50
        if self.same_legal_entity is True:
            score += 25
        if self.role_match:
            score += 15
        if self.channel in {"email", "named_contact"}:
            score += 5
        return score


@dataclass
class ProviderGate:
    provider_name: str
    legal_entity_verified: bool = False
    ownership_verified: bool = False
    sanctions_screened: bool = False
    blocked_or_high_risk_match: bool = False
    cuba_customs_authority_verified: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def commercially_usable(self) -> bool:
        return (
            self.legal_entity_verified
            and self.ownership_verified
            and self.sanctions_screened
            and not self.blocked_or_high_risk_match
        )


def classify_delivery_notice(text: str) -> DeliveryState:
    t = (text or "").lower()
    permanent_markers = (
        "delivery status notification (failure)",
        "address not found",
        "does not exist",
        "domain not found",
        "couldn't be found",
        "550 ",
        "5.1.1",
        "permanent error",
    )
    delay_markers = (
        "delivery status notification (delay)",
        "temporary failure",
        "will retry",
        "delayed",
        "4.4.",
        "421 ",
        "451 ",
    )
    if any(x in t for x in permanent_markers):
        return DeliveryState.PERMANENT_FAILURE
    if any(x in t for x in delay_markers):
        return DeliveryState.TEMPORARY_DELAY
    if "delivered" in t and "not delivered" not in t:
        return DeliveryState.DELIVERED
    return DeliveryState.UNKNOWN


def rank_contact_candidates(candidates: Iterable[ContactCandidate]) -> list[ContactCandidate]:
    """Verified, same-entity, role-relevant channels sort first.

    No synthetic email pattern generation is performed. A candidate must come from
    supplied evidence such as an official website, official directory, carrier page,
    signed email footer, or validated CRM record.
    """
    return sorted(candidates, key=lambda c: (c.score, c.value), reverse=True)


def _d(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid numeric value: {value!r}") from exc


def normalize_to_usd_per_kg(*, amount_usd: object, quantity: object, unit: str) -> Decimal:
    """Normalize an upstream logistics quote to USD/kg.

    Supported units: kg, lb, metric_ton/mt, shipment. For shipment, quantity must be
    the total shipment weight in kg.
    """
    amount = _d(amount_usd)
    qty = _d(quantity)
    if qty <= 0:
        raise ValueError("quantity must be > 0")
    u = unit.strip().lower()
    if u in {"kg", "kilogram", "kilograms"}:
        kg = qty
    elif u in {"lb", "lbs", "pound", "pounds"}:
        kg = qty / LB_PER_KG
    elif u in {"mt", "metric_ton", "metric_tons", "tonne", "tonnes"}:
        kg = qty * Decimal("1000")
    elif u in {"shipment", "container", "pallet"}:
        # Caller must pass the corresponding total weight in kg as quantity.
        kg = qty
    else:
        raise ValueError(f"Unsupported unit: {unit}")
    return (amount / kg).quantize(Decimal("0.0001"))


def split_route_costs(legs: dict[str, object]) -> dict[str, Decimal]:
    """Return normalized upstream route costs without inventing missing legs."""
    out: dict[str, Decimal] = {}
    for raw_leg, raw_amount in legs.items():
        key = raw_leg.strip().lower()
        if key not in {x.value for x in RouteLeg}:
            raise ValueError(f"Unknown route leg: {raw_leg}")
        out[key] = _d(raw_amount)
    out["upstream_total_usd"] = sum(out.values(), Decimal("0"))
    return out


def sanctions_gate(provider_name: str, ownership_names: Iterable[str] = ()) -> ProviderGate:
    """Conservative name-screen pre-gate; not a substitute for OFAC/legal review."""
    names = [provider_name, *ownership_names]
    normalized = " | ".join(n.lower() for n in names if n)
    matched = any(name in normalized for name in BLOCKED_OR_HIGH_RISK_CUBA_NAMES)
    gate = ProviderGate(provider_name=provider_name, blocked_or_high_risk_match=matched)
    if matched:
        gate.notes.append(
            "Potential restricted/high-risk ownership or affiliation match. Fail closed pending transaction-specific sanctions review."
        )
    return gate


def resend_decision(
    *,
    delivery_state: DeliveryState,
    alternate_candidates: Iterable[ContactCandidate] = (),
    duplicate_risk: bool = False,
) -> dict[str, object]:
    ranked = rank_contact_candidates(alternate_candidates)
    if duplicate_risk:
        return {"action": "hold", "reason": "duplicate_risk", "candidate": None}
    if delivery_state == DeliveryState.TEMPORARY_DELAY:
        return {"action": "wait_for_provider_retry", "reason": "temporary_delay", "candidate": None}
    if delivery_state == DeliveryState.PERMANENT_FAILURE:
        if ranked and ranked[0].verified:
            return {
                "action": "prepare_resend",
                "reason": "verified_alternate_available",
                "candidate": asdict(ranked[0]),
            }
        return {"action": "research_alternate", "reason": "no_verified_alternate", "candidate": None}
    return {"action": "hold", "reason": "insufficient_evidence", "candidate": None}


def recovery_report(
    *,
    provider: str,
    delivery_notice: str,
    candidates: Iterable[ContactCandidate] = (),
    ownership_names: Iterable[str] = (),
) -> dict[str, object]:
    state = classify_delivery_notice(delivery_notice)
    gate = sanctions_gate(provider, ownership_names)
    decision = resend_decision(delivery_state=state, alternate_candidates=candidates)
    return {
        "provider": provider,
        "delivery_state": state.value,
        "contact_recovery": decision,
        "provider_gate": asdict(gate),
        "guardrails": {
            "auto_send": False,
            "invent_contact": False,
            "legal_conclusion": False,
            "separate_upstream_cost_from_customer_sell_price": True,
        },
    }
