from __future__ import annotations

from typing import Literal
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title='SAHJONY Logistics Go-To-Business Engine', version='1.0.0', docs_url=None, redoc_url=None)

PartnerType = Literal['SHIPPING_AGENCY','HOME_COLLECTION_PARTNER','TRUCKING_PROVIDER','WAREHOUSE_PROVIDER','AIR_CARGO_PROVIDER','OCEAN_PROVIDER','DESTINATION_PARTNER','LAST_MILE_PROVIDER']
CityStage = Literal['RESEARCH','PROVIDER_DISCOVERY','COMMERCIAL_VALIDATION','PILOT_READY','ACTIVE','SCALE']

OFFER_STACK = {
    'CUSTOMER': [
        'DOOR_TO_DOOR', 'PICKUP_AVAILABLE', 'ONE_QUOTE', 'ONE_TRACKING_RECORD', 'QR_CHAIN_OF_CUSTODY',
        'AIR_OR_SEA_OPTIMIZATION', 'BEST_GATEWAY_SELECTION', 'LAST_MILE_TO_HOME_OR_BUSINESS', 'POD', 'CLAIMS_SUPPORT'
    ],
    'AGENCY': [
        'KEEP_YOUR_CUSTOMER', 'KEEP_YOUR_BRAND', 'WHOLESALE_RATES', 'AGENCY_MARGIN_PROTECTED',
        'LOCAL_VIRTUAL_HUB', 'TRUCKING_PROCUREMENT', 'AIR_SEA_PROCUREMENT', 'DOCUMENTS_COMPLIANCE',
        'TRACKING_POD', 'CLAIMS_RECONCILIATION', 'WHITE_LABEL_READY'
    ],
    'PROVIDER': [
        'QUALIFIED_LOADS', 'CLEAR_SCOPE', 'DIGITAL_HANDOFF', 'QR_CUSTODY', 'PERFORMANCE_SCORECARD',
        'SETTLEMENT_RECORD', 'REPEAT_LANE_VOLUME'
    ],
}

NORTH_STAR = 'QUALITY_ADJUSTED_COLLECTED_GROSS_PROFIT'

class CityActivationIn(BaseModel):
    city: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=2)
    verified_agencies: int = Field(default=0, ge=0)
    verified_collection_partners: int = Field(default=0, ge=0)
    verified_trucking_options: int = Field(default=0, ge=0)
    verified_gateway_options: int = Field(default=0, ge=0)
    verified_last_mile_options: int = Field(default=0, ge=0)
    live_door_to_door_rate_available: bool = False
    compliance_route_validated: bool = False
    pod_capable: bool = False
    pilot_shipments_completed: int = Field(default=0, ge=0)
    collected_gross_profit_usd: float = Field(default=0, ge=0)
    claim_rate_pct: float | None = Field(default=None, ge=0, le=100)
    on_time_delivery_pct: float | None = Field(default=None, ge=0, le=100)


def city_stage(p: CityActivationIn) -> CityStage:
    if p.verified_agencies == 0 and p.verified_collection_partners == 0:
        return 'RESEARCH'
    if p.verified_trucking_options == 0 or p.verified_last_mile_options == 0:
        return 'PROVIDER_DISCOVERY'
    if not (p.live_door_to_door_rate_available and p.compliance_route_validated and p.pod_capable):
        return 'COMMERCIAL_VALIDATION'
    if p.pilot_shipments_completed == 0:
        return 'PILOT_READY'
    if p.pilot_shipments_completed < 25 or p.collected_gross_profit_usd <= 0:
        return 'ACTIVE'
    return 'SCALE'


def activation_gates(p: CityActivationIn) -> list[dict]:
    return [
        {'gate':'DEMAND_NODE','passed':p.verified_agencies > 0 or p.verified_collection_partners > 0},
        {'gate':'DOMESTIC_CAPACITY','passed':p.verified_trucking_options > 0},
        {'gate':'EXPORT_GATEWAY','passed':p.verified_gateway_options > 0},
        {'gate':'LAST_MILE','passed':p.verified_last_mile_options > 0},
        {'gate':'LIVE_DOOR_TO_DOOR_PRICE','passed':p.live_door_to_door_rate_available},
        {'gate':'COMPLIANCE_ROUTE','passed':p.compliance_route_validated},
        {'gate':'POD','passed':p.pod_capable},
    ]


class PartnerEconomicsIn(BaseModel):
    partner_type: PartnerType
    provider_cost_usd: float = Field(ge=0)
    customer_price_usd: float = Field(gt=0)
    agency_margin_usd: float = Field(default=0, ge=0)
    partner_payout_usd: float = Field(default=0, ge=0)
    payment_cost_usd: float = Field(default=0, ge=0)
    claims_reserve_usd: float = Field(default=0, ge=0)
    minimum_sahjony_gp_usd: float = Field(default=5, ge=0)


def economics(p: PartnerEconomicsIn) -> dict:
    fully_loaded = p.provider_cost_usd + p.agency_margin_usd + p.partner_payout_usd + p.payment_cost_usd + p.claims_reserve_usd
    gp = round(p.customer_price_usd - fully_loaded, 2)
    margin_pct = round((gp / p.customer_price_usd) * 100, 2) if p.customer_price_usd else 0
    return {
        'fully_loaded_cost_usd': round(fully_loaded, 2),
        'sahjony_gross_profit_usd': gp,
        'gross_margin_pct': margin_pct,
        'profit_floor_passed': gp >= p.minimum_sahjony_gp_usd,
        'release': 'COMMERCIAL_REVIEW' if gp < p.minimum_sahjony_gp_usd else 'ECONOMICS_ELIGIBLE',
    }


@app.get('/go-to-business/health')
async def health():
    return {
        'status':'ok',
        'north_star':NORTH_STAR,
        'agency_first_distribution':True,
        'city_virtual_hub_expansion':True,
        'door_to_door_default':True,
        'provider_bidding':True,
        'margin_floor_protected':True,
        'customer_relationship_protection':True,
        'asset_light_launch':True,
    }


@app.get('/go-to-business/offer-stack')
async def offer_stack():
    return {'north_star':NORTH_STAR,'offers':OFFER_STACK}


@app.post('/go-to-business/city-stage')
async def evaluate_city(p: CityActivationIn):
    gates = activation_gates(p)
    return {
        'city':p.city,
        'state':p.state.upper(),
        'stage':city_stage(p),
        'gates':gates,
        'all_activation_gates_passed':all(g['passed'] for g in gates),
        'next_priority':[g['gate'] for g in gates if not g['passed']][:3],
        'scale_rule':'Do not scale paid acquisition until door-to-door economics, compliance, POD and provider capacity are validated with real shipments.',
    }


@app.post('/go-to-business/partner-economics')
async def evaluate_partner_economics(p: PartnerEconomicsIn):
    return {'partner_type':p.partner_type, **economics(p)}


@app.get('/go-to-business/playbook')
async def playbook():
    return {
        'sequence':[
            'SELECT_CITY_BY_DEMAND_AND_AGENCY_DENSITY',
            'RECRUIT_AND_VERIFY_AGENCIES_AND_COLLECTION_PARTNERS',
            'VERIFY_TRUCKING_AND_LOCAL_HANDOFF_CAPACITY',
            'LOAD_MULTIPLE_EXPORT_GATEWAY_OPTIONS',
            'VERIFY_DESTINATION_AND_LAST_MILE_CAPACITY',
            'BUILD_LIVE_DOOR_TO_DOOR_RATE',
            'VALIDATE_COMPLIANCE_AND_DOCUMENT_REQUIREMENTS',
            'RUN_CONTROLLED_PILOT_SHIPMENTS',
            'MEASURE_ACTUAL_TRANSIT_CLAIMS_AND_GROSS_PROFIT',
            'IMPROVE_PROVIDER_MIX_AND_NEGOTIATE_VOLUME_RATES',
            'SCALE_AGENCY_DISTRIBUTION_AND_CUSTOMER_ACQUISITION',
            'PROMOTE_HIGH_DENSITY_CITY_TO_REGIONAL_NODE',
        ],
        'commercial_rule':'SAHJONY is the logistics infrastructure and wholesale network; agencies retain their customer relationship and approved economics.',
        'customer_rule':'One quote, one tracking record, door-to-door delivery, one chain of custody, one POD.',
        'growth_flywheel':'MORE_AGENCIES -> MORE_VOLUME -> BETTER_PROVIDER_RATES -> BETTER_CUSTOMER_VALUE -> MORE_SHIPMENTS -> LOWER_UNIT_COST -> HIGHER_COLLECTED_GP -> MORE_AGENCIES',
    }
