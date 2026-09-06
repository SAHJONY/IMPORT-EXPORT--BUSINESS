from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title='SAHJONY Independent Trucking Marketplace', version='1.0.0', docs_url=None, redoc_url=None)

VehicleType = Literal['COURIER','PICKUP','CARGO_VAN','SPRINTER_VAN','BOX_TRUCK','HOTSHOT_FLATBED','GOOSENECK','STRAIGHT_TRUCK']
PricingBasis = Literal['LIVE_QUOTE_REQUIRED','PER_MILE_BENCHMARK','PER_HOUR_BENCHMARK','FIXED_PROJECT_QUOTE']
ProviderType = Literal['OWNER_OPERATOR','SMALL_FLEET','DELIVERY_PLATFORM','LOCAL_CARRIER']

PUBLIC_MARKET_BENCHMARKS = {
    'CARGO_VAN': {'low_per_mile': 1.20, 'high_per_mile': 1.80, 'source_type': 'MARKET_GUIDE', 'binding': False},
    'BOX_TRUCK': {'low_per_mile': 1.50, 'high_per_mile': 2.60, 'source_type': 'MARKET_GUIDE', 'binding': False},
    'HOTSHOT_FLATBED': {'low_per_mile': 1.50, 'high_per_mile': 3.00, 'source_type': 'MARKET_GUIDE', 'binding': False},
    'GOOSENECK': {'low_per_mile': 1.80, 'high_per_mile': 2.50, 'source_type': 'MARKET_GUIDE', 'binding': False},
}

PUBLIC_PLATFORM_REFERENCES = {
    'GOSHARE': {
        'provider_type': 'DELIVERY_PLATFORM',
        'vehicles': ['COURIER','PICKUP','CARGO_VAN','BOX_TRUCK'],
        'pricing_basis': 'LIVE_QUOTE_REQUIRED',
        'independent_driver_network': True,
        'same_day': True,
        'scheduled': True,
        'tracking': True,
        'cargo_and_liability_coverage': True,
        'long_distance_max_miles_publicly_stated': 2500,
        'public_driver_earnings_reference': {
            'COURIER_per_hour_up_to': 46,
            'PICKUP_per_hour_up_to': 60,
            'CARGO_VAN_per_hour_up_to': 105,
            'BOX_TRUCK_per_hour_up_to': 188,
        },
        'customer_rate_note': 'Customized project estimate; do not treat driver earnings as customer price.',
    },
}

@dataclass(frozen=True)
class IndependentCarrierOffer:
    provider_id: str
    provider_type: ProviderType
    vehicle_type: VehicleType
    origin_city: str
    origin_state: str
    destination_city: str
    destination_state: str
    distance_miles: float
    quoted_total_usd: float
    insured: bool
    cargo_insurance_verified: bool
    active_authority_verified: bool
    tracking: bool
    pod: bool
    pickup: bool
    residential_delivery: bool
    liftgate: bool
    appointment_delivery: bool
    same_day: bool
    capacity_confirmed: bool
    rating_0_100: float = 50.0

    @property
    def effective_per_mile(self) -> float | None:
        if self.distance_miles <= 0:
            return None
        return round(self.quoted_total_usd / self.distance_miles, 2)

    @property
    def eligible(self) -> bool:
        return bool(
            self.insured and self.cargo_insurance_verified and self.active_authority_verified
            and self.tracking and self.pod and self.capacity_confirmed
        )


def rank_offer(o: IndependentCarrierOffer) -> tuple:
    return (
        1 if o.eligible else 0,
        o.rating_0_100,
        -o.quoted_total_usd,
        -float(o.effective_per_mile or 10**9),
    )


class OfferIn(BaseModel):
    provider_id: str = Field(min_length=2, max_length=160)
    provider_type: ProviderType
    vehicle_type: VehicleType
    origin_city: str
    origin_state: str = Field(min_length=2, max_length=2)
    destination_city: str
    destination_state: str = Field(min_length=2, max_length=2)
    distance_miles: float = Field(gt=0)
    quoted_total_usd: float = Field(gt=0)
    insured: bool
    cargo_insurance_verified: bool
    active_authority_verified: bool
    tracking: bool = True
    pod: bool = True
    pickup: bool = True
    residential_delivery: bool = True
    liftgate: bool = False
    appointment_delivery: bool = False
    same_day: bool = False
    capacity_confirmed: bool = False
    rating_0_100: float = Field(default=50, ge=0, le=100)


@app.get('/independent-trucking/health')
async def health():
    return {
        'status': 'ok',
        'owner_operator_support': True,
        'small_fleet_support': True,
        'cargo_van': True,
        'sprinter_van': True,
        'box_truck': True,
        'hotshot': True,
        'pickup': True,
        'live_quote_required_for_booking': True,
        'public_market_ranges_are_nonbinding': True,
        'insurance_and_authority_verification_required': True,
        'pod_required': True,
    }


@app.get('/independent-trucking/benchmarks')
async def benchmarks():
    return {
        'market_benchmarks': PUBLIC_MARKET_BENCHMARKS,
        'platform_references': PUBLIC_PLATFORM_REFERENCES,
        'rule': 'Benchmarks are reference ranges only. Booking price must come from a current provider quote for the exact load and lane.',
    }


@app.post('/independent-trucking/rank')
async def rank(offers: list[OfferIn]):
    normalized = [IndependentCarrierOffer(**o.model_dump()) for o in offers]
    ranked = sorted(normalized, key=rank_offer, reverse=True)
    return {
        'eligible_offers': [
            {
                **o.__dict__,
                'effective_per_mile': o.effective_per_mile,
                'eligible': o.eligible,
            } for o in ranked if o.eligible
        ],
        'rejected_offers': [
            {
                **o.__dict__,
                'effective_per_mile': o.effective_per_mile,
                'eligible': o.eligible,
            } for o in ranked if not o.eligible
        ],
        'selection_rule': 'Prefer verified, insured, capacity-confirmed providers with tracking and POD; then optimize service quality and total cost.',
    }
