from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from logistics_profit_optimizer import RouteCandidate, optimize_route, policy_snapshot, rank_routes

app = FastAPI(title='SAHJONY Logistics Profit Optimizer', version='1.1.0', docs_url=None, redoc_url=None)


def owner_required(authorization: str | None, x_role: str | None):
    if x_role != 'owner':
        raise HTTPException(403, 'Owner role required')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(authorization.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid owner credential')


class RouteIn(BaseModel):
    route_id: str = Field(min_length=2, max_length=180)
    mode: Literal['AIR','SEA','MULTIMODAL']
    service_level: Literal['ECONOMY','STANDARD','EXPRESS','PREMIUM']='STANDARD'
    linehaul_cost: float = Field(default=0, ge=0)
    international_freight: float = Field(default=0, ge=0)
    origin_handling: float = Field(default=0, ge=0)
    destination_handling: float = Field(default=0, ge=0)
    last_mile: float = Field(default=0, ge=0)
    compliance_cost: float = Field(default=0, ge=0)
    insurance_cost: float = Field(default=0, ge=0)
    payment_cost: float = Field(default=0, ge=0)
    transit_days: int = Field(ge=0, le=365)
    tracking: bool = True
    pod: bool = True
    claims: bool = True
    pickup: bool = False
    door_delivery: bool = True
    capacity_confirmed: bool = False
    compliance_cleared: bool = False


class OptimizeIn(BaseModel):
    routes: list[RouteIn] = Field(min_length=1, max_length=100)
    customer_type: Literal['RETAIL','AGENCY','BUSINESS']='RETAIL'
    competitor_effective_price: float | None = Field(default=None, gt=0)
    competitor_door_to_door: bool = True
    agency_partner: bool = False
    home_collection_partner: bool = False


def to_route(r: RouteIn) -> RouteCandidate:
    d = r.model_dump()
    for key in ('linehaul_cost','international_freight','origin_handling','destination_handling','last_mile','compliance_cost','insurance_cost','payment_cost'):
        d[key] = Decimal(str(d[key]))
    return RouteCandidate(**d)


@app.get('/logistics-profit/health')
async def health():
    return {
        'status':'ok',
        'profit_floor_protected':True,
        'competitor_benchmarking':True,
        'competitor_comparison_requires_door_to_door':True,
        'door_to_door_default':True,
        'pod_required_for_completion':True,
        'last_mile_included_in_cost_basis':True,
        'air_sea_multimodal':True,
        'agency_revenue_share':True,
        'home_partner_revenue_share':True,
        'customer_cost_basis_hidden':True,
        'compliance_fail_closed':True,
    }


@app.get('/logistics-profit/policy')
async def policy(authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    owner_required(authorization, x_role)
    return policy_snapshot()


@app.post('/logistics-profit/optimize')
async def optimize(p: OptimizeIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    owner_required(authorization, x_role)
    results = [
        optimize_route(
            to_route(route),
            customer_type=p.customer_type,
            competitor_effective_price=p.competitor_effective_price,
            competitor_door_to_door=p.competitor_door_to_door,
            agency_partner=p.agency_partner,
            home_collection_partner=p.home_collection_partner,
        ) for route in p.routes
    ]
    ranked = rank_routes(results)
    return {
        'status':'ok',
        'best_route': ranked[0],
        'alternatives': ranked[1:],
        'binding_quote':False,
        'delivery_standard':'DOOR_TO_DOOR',
        'rule':'Firm quote requires door delivery, POD, confirmed capacity and compliance clearance. Competitor prices are comparable only when they represent equivalent door-to-door service. Internal cost and margin fields remain owner-only.',
    }
