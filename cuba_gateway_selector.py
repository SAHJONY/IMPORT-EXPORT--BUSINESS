from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

GatewayMode = Literal['AIRPORT','SEAPORT']
CargoType = Literal['PARCEL','BOXES','PALLET','LCL','FCL','VEHICLE','MOTORCYCLE','OVERSIZED','SPECIAL']


def money(v: float | int | str | Decimal) -> Decimal:
    return Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class GatewayCandidate:
    gateway_id: str
    city: str
    state: str
    gateway_name: str
    gateway_mode: GatewayMode
    cargo_types: tuple[CargoType, ...]
    domestic_transfer_cost: Decimal
    origin_handling_cost: Decimal
    international_freight_cost: Decimal
    destination_handling_cost: Decimal
    last_mile_cost: Decimal
    compliance_cost: Decimal
    transit_days: int
    pickup_available: bool = True
    tracking_available: bool = True
    pod_available: bool = True
    door_to_door_available: bool = True
    capacity_confirmed: bool = False
    compliance_cleared: bool = False
    carrier_service_score: int = 50

    @property
    def effective_door_to_door_cost(self) -> Decimal:
        return money(sum([
            self.domestic_transfer_cost,
            self.origin_handling_cost,
            self.international_freight_cost,
            self.destination_handling_cost,
            self.last_mile_cost,
            self.compliance_cost,
        ], Decimal('0.00')))


def eligible(candidate: GatewayCandidate, cargo_type: CargoType) -> bool:
    return (
        cargo_type in candidate.cargo_types
        and candidate.door_to_door_available
        and candidate.tracking_available
        and candidate.pod_available
    )


def gateway_score(candidate: GatewayCandidate, cargo_type: CargoType) -> tuple:
    if not eligible(candidate, cargo_type):
        return (-1, -1, Decimal('-999999'), -999999)
    ready = 1 if candidate.capacity_confirmed and candidate.compliance_cleared else 0
    service = max(0, min(candidate.carrier_service_score, 100))
    return (
        ready,
        service,
        -candidate.effective_door_to_door_cost,
        -candidate.transit_days,
    )


def rank_gateways(candidates: list[GatewayCandidate], cargo_type: CargoType) -> list[GatewayCandidate]:
    valid = [c for c in candidates if eligible(c, cargo_type)]
    return sorted(valid, key=lambda c: gateway_score(c, cargo_type), reverse=True)


def select_best_gateway(candidates: list[GatewayCandidate], cargo_type: CargoType) -> dict:
    ranked = rank_gateways(candidates, cargo_type)
    if not ranked:
        return {
            'status':'NO_ELIGIBLE_GATEWAY',
            'reason':'No door-to-door gateway with tracking and POD is currently eligible for this cargo type.',
        }
    best = ranked[0]
    return {
        'status':'SELECTED',
        'gateway_id':best.gateway_id,
        'gateway_name':best.gateway_name,
        'gateway_city':best.city,
        'gateway_state':best.state,
        'gateway_mode':best.gateway_mode,
        'cargo_type':cargo_type,
        'effective_door_to_door_cost':float(best.effective_door_to_door_cost),
        'transit_days':best.transit_days,
        'service_score':best.carrier_service_score,
        'capacity_confirmed':best.capacity_confirmed,
        'compliance_cleared':best.compliance_cleared,
        'firm_quote_eligible':bool(best.capacity_confirmed and best.compliance_cleared),
        'selection_rule':'Lowest effective door-to-door cost among eligible gateways, weighted by confirmed capacity, compliance clearance, service quality and transit time.',
        'alternatives':[
            {
                'gateway_id':g.gateway_id,
                'gateway_name':g.gateway_name,
                'gateway_city':g.city,
                'gateway_state':g.state,
                'gateway_mode':g.gateway_mode,
                'effective_door_to_door_cost':float(g.effective_door_to_door_cost),
                'transit_days':g.transit_days,
                'service_score':g.carrier_service_score,
            }
            for g in ranked[1:]
        ],
    }
