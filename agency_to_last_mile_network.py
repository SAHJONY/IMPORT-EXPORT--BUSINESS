from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title='SAHJONY Agency-to-Last-Mile Network', version='1.0.0', docs_url=None, redoc_url=None)

Mode = Literal['AIR','SEA','MULTIMODAL']
LegType = Literal['AGENCY_ORIGIN','CITY_VIRTUAL_HUB','DOMESTIC_LINEHAUL','US_GATEWAY','INTERNATIONAL_CARRIER','CUBA_DESTINATION_PARTNER','LAST_MILE','FINAL_RECIPIENT']
ProviderStatus = Literal['CANDIDATE','VERIFIED','ACTIVE','HOLD','SUSPENDED']
CargoType = Literal['SINGLE_ITEM','BOX','MULTIPLE_BOXES','PALLET','LTL','LCL','FCL','VEHICLE','MOTORCYCLE','OVERSIZED','SPECIAL_REGULATED']


def money(v: float | int | str | Decimal) -> Decimal:
    return Decimal(str(v)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ProviderCandidate:
    provider_id: str
    provider_name: str
    leg_type: LegType
    city: str
    region: str
    status: ProviderStatus
    supported_modes: tuple[str, ...]
    supported_cargo: tuple[str, ...]
    base_cost: Decimal
    variable_cost: Decimal
    estimated_days: int
    capacity_score: int
    service_score: int
    on_time_score: int
    claims_score: int
    tracking: bool
    qr_handoff: bool
    pod: bool
    door_delivery: bool
    compliance_cleared: bool

    @property
    def effective_cost(self) -> Decimal:
        return money(self.base_cost + self.variable_cost)


class ProviderIn(BaseModel):
    provider_id: str = Field(min_length=2, max_length=160)
    provider_name: str = Field(min_length=2, max_length=240)
    leg_type: LegType
    city: str = Field(min_length=2, max_length=160)
    region: str = Field(min_length=2, max_length=160)
    status: ProviderStatus = 'CANDIDATE'
    supported_modes: list[Mode] = Field(default_factory=list)
    supported_cargo: list[CargoType] = Field(default_factory=list)
    base_cost: float = Field(default=0, ge=0)
    variable_cost: float = Field(default=0, ge=0)
    estimated_days: int = Field(default=1, ge=0, le=365)
    capacity_score: int = Field(default=50, ge=0, le=100)
    service_score: int = Field(default=50, ge=0, le=100)
    on_time_score: int = Field(default=50, ge=0, le=100)
    claims_score: int = Field(default=50, ge=0, le=100)
    tracking: bool = True
    qr_handoff: bool = True
    pod: bool = False
    door_delivery: bool = False
    compliance_cleared: bool = False


class NetworkPlanIn(BaseModel):
    mode: Mode
    cargo_type: CargoType
    origin_city: str = Field(min_length=2, max_length=160)
    origin_state: str = Field(min_length=2, max_length=2)
    destination_province: str = Field(min_length=2, max_length=160)
    destination_city: str = Field(min_length=2, max_length=160)
    final_address: str = Field(min_length=5, max_length=400)
    providers: list[ProviderIn] = Field(min_length=1, max_length=500)


def _candidate(p: ProviderIn) -> ProviderCandidate:
    return ProviderCandidate(
        provider_id=p.provider_id,
        provider_name=p.provider_name,
        leg_type=p.leg_type,
        city=p.city,
        region=p.region,
        status=p.status,
        supported_modes=tuple(p.supported_modes),
        supported_cargo=tuple(p.supported_cargo),
        base_cost=money(p.base_cost),
        variable_cost=money(p.variable_cost),
        estimated_days=p.estimated_days,
        capacity_score=p.capacity_score,
        service_score=p.service_score,
        on_time_score=p.on_time_score,
        claims_score=p.claims_score,
        tracking=p.tracking,
        qr_handoff=p.qr_handoff,
        pod=p.pod,
        door_delivery=p.door_delivery,
        compliance_cleared=p.compliance_cleared,
    )


def eligible(p: ProviderCandidate, *, mode: Mode, cargo_type: CargoType) -> bool:
    if p.status not in {'VERIFIED','ACTIVE'}:
        return False
    if mode not in p.supported_modes:
        return False
    if cargo_type not in p.supported_cargo:
        return False
    if not p.compliance_cleared:
        return False
    if not p.qr_handoff:
        return False
    if p.leg_type == 'LAST_MILE' and (not p.door_delivery or not p.pod or not p.tracking):
        return False
    return True


def provider_score(p: ProviderCandidate) -> tuple:
    quality = (
        p.capacity_score * 0.25 +
        p.service_score * 0.25 +
        p.on_time_score * 0.25 +
        p.claims_score * 0.15 +
        (10 if p.tracking else 0)
    )
    return (round(quality, 2), -float(p.effective_cost), -p.estimated_days)


def choose_provider(providers: list[ProviderCandidate], *, leg_type: LegType, mode: Mode, cargo_type: CargoType) -> ProviderCandidate:
    candidates = [p for p in providers if p.leg_type == leg_type and eligible(p, mode=mode, cargo_type=cargo_type)]
    if not candidates:
        raise HTTPException(409, f'No eligible provider for {leg_type}')
    return sorted(candidates, key=provider_score, reverse=True)[0]


NETWORK_SEQUENCE: tuple[LegType, ...] = (
    'AGENCY_ORIGIN',
    'CITY_VIRTUAL_HUB',
    'DOMESTIC_LINEHAUL',
    'US_GATEWAY',
    'INTERNATIONAL_CARRIER',
    'CUBA_DESTINATION_PARTNER',
    'LAST_MILE',
    'FINAL_RECIPIENT',
)


@app.get('/agency-last-mile/health')
async def health():
    return {
        'status':'ok',
        'door_to_door_default':True,
        'no_scan_no_handoff':True,
        'pod_required':True,
        'multi_provider_per_city':True,
        'dynamic_provider_selection':True,
        'service_and_cost_optimized':True,
        'compliance_fail_closed':True,
        'network_sequence':NETWORK_SEQUENCE,
    }


@app.post('/agency-last-mile/plan')
async def plan(p: NetworkPlanIn):
    providers = [_candidate(x) for x in p.providers]
    operational_legs: list[LegType] = [
        'AGENCY_ORIGIN','CITY_VIRTUAL_HUB','DOMESTIC_LINEHAUL','US_GATEWAY',
        'INTERNATIONAL_CARRIER','CUBA_DESTINATION_PARTNER','LAST_MILE'
    ]
    selected = []
    total_cost = Decimal('0.00')
    total_days = 0
    for leg in operational_legs:
        provider = choose_provider(providers, leg_type=leg, mode=p.mode, cargo_type=p.cargo_type)
        selected.append({
            'leg_type':leg,
            'provider_id':provider.provider_id,
            'provider_name':provider.provider_name,
            'city':provider.city,
            'region':provider.region,
            'effective_cost':float(provider.effective_cost),
            'estimated_days':provider.estimated_days,
            'tracking':provider.tracking,
            'qr_handoff':provider.qr_handoff,
            'pod':provider.pod,
            'door_delivery':provider.door_delivery,
        })
        total_cost += provider.effective_cost
        total_days += provider.estimated_days

    return {
        'status':'PLANNED',
        'mode':p.mode,
        'cargo_type':p.cargo_type,
        'origin':{'city':p.origin_city,'state':p.origin_state},
        'destination':{'province':p.destination_province,'city':p.destination_city,'final_address':p.final_address},
        'selected_legs':selected,
        'final_leg':{
            'leg_type':'FINAL_RECIPIENT',
            'address':p.final_address,
            'completion_requires':['RECIPIENT_VERIFIED','POD','DELIVERY_TIMESTAMP','FINAL_ADDRESS_CONFIRMATION'],
        },
        'internal_network_cost':float(money(total_cost)),
        'estimated_network_days':total_days,
        'handoff_rule':'NO_SCAN_NO_HANDOFF',
        'completion_rule':'NOT_COMPLETE_UNTIL_FINAL_ADDRESS_DELIVERY_AND_POD',
        'quote_rule':'Customer quote must include every selected leg through final door delivery.',
    }
