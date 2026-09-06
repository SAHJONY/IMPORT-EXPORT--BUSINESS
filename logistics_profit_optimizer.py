from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

Mode = Literal['AIR','SEA','MULTIMODAL']
ServiceLevel = Literal['ECONOMY','STANDARD','EXPRESS','PREMIUM']
CustomerType = Literal['RETAIL','AGENCY','BUSINESS']


def money(value: float | int | str | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ProfitPolicy:
    minimum_margin_pct: Decimal = Decimal('12.00')
    target_margin_pct: Decimal = Decimal('22.00')
    premium_margin_pct: Decimal = Decimal('28.00')
    minimum_gp_usd: Decimal = Decimal('5.00')
    max_competitor_undercut_pct: Decimal = Decimal('5.00')
    contingency_pct: Decimal = Decimal('3.00')
    agency_share_pct: Decimal = Decimal('6.00')
    home_partner_share_pct: Decimal = Decimal('3.00')
    door_to_door_required: bool = True
    pod_required: bool = True
    last_mile_cost_required: bool = True


DEFAULT_POLICY = ProfitPolicy()


@dataclass(frozen=True)
class RouteCandidate:
    route_id: str
    mode: Mode
    service_level: ServiceLevel
    linehaul_cost: Decimal
    international_freight: Decimal
    origin_handling: Decimal
    destination_handling: Decimal
    last_mile: Decimal
    compliance_cost: Decimal
    insurance_cost: Decimal
    payment_cost: Decimal
    transit_days: int
    tracking: bool = True
    pod: bool = True
    claims: bool = True
    pickup: bool = False
    door_delivery: bool = True
    capacity_confirmed: bool = False
    compliance_cleared: bool = False

    @property
    def operating_cost(self) -> Decimal:
        return sum([
            self.linehaul_cost, self.international_freight, self.origin_handling,
            self.destination_handling, self.last_mile, self.compliance_cost,
            self.insurance_cost, self.payment_cost,
        ], Decimal('0.00'))


def _pct(base: Decimal, pct: Decimal) -> Decimal:
    return (base * pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _price_for_margin(cost: Decimal, margin_pct: Decimal) -> Decimal:
    if margin_pct >= Decimal('95'):
        raise ValueError('Margin is not commercially valid')
    return (cost / (Decimal('1') - margin_pct / Decimal('100'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _door_to_door_ready(route: RouteCandidate, policy: ProfitPolicy) -> bool:
    if policy.door_to_door_required and not route.door_delivery:
        return False
    if policy.pod_required and not route.pod:
        return False
    if policy.last_mile_cost_required and route.last_mile < 0:
        return False
    return True


def _service_score(r: RouteCandidate) -> int:
    if not r.door_delivery or not r.pod:
        return 0
    score = 30
    score += 15 if r.tracking else 0
    score += 15 if r.claims else 0
    score += 10 if r.pickup else 0
    score += 15 if r.capacity_confirmed else 0
    score += 15 if r.compliance_cleared else 0
    return min(score, 100)


def optimize_route(
    route: RouteCandidate,
    *,
    customer_type: CustomerType = 'RETAIL',
    competitor_effective_price: float | None = None,
    competitor_door_to_door: bool = True,
    policy: ProfitPolicy = DEFAULT_POLICY,
    agency_partner: bool = False,
    home_collection_partner: bool = False,
) -> dict:
    d2d_ready = _door_to_door_ready(route, policy)
    base_cost = money(route.operating_cost)
    contingency = _pct(base_cost, policy.contingency_pct)
    protected_cost = base_cost + contingency

    agency_share = Decimal('0.00')
    home_partner_share = Decimal('0.00')
    if agency_partner or customer_type == 'AGENCY':
        agency_share = _pct(protected_cost, policy.agency_share_pct)
    if home_collection_partner:
        home_partner_share = _pct(protected_cost, policy.home_partner_share_pct)
    fully_loaded = money(protected_cost + agency_share + home_partner_share)

    target_margin = policy.premium_margin_pct if route.service_level in {'EXPRESS','PREMIUM'} else policy.target_margin_pct
    if customer_type == 'AGENCY':
        target_margin = max(policy.minimum_margin_pct, target_margin - Decimal('4.00'))

    floor_price = max(_price_for_margin(fully_loaded, policy.minimum_margin_pct), fully_loaded + policy.minimum_gp_usd)
    target_price = _price_for_margin(fully_loaded, target_margin)

    competitor = money(competitor_effective_price) if competitor_effective_price is not None and competitor_door_to_door else None
    competitive_target = None
    if competitor is not None and competitor > 0:
        competitive_target = money(competitor - _pct(competitor, policy.max_competitor_undercut_pct))

    if not d2d_ready:
        recommended = max(target_price, floor_price)
        pricing_position = 'DOOR_TO_DOOR_REQUIRED'
    elif competitive_target is not None and competitive_target >= floor_price:
        recommended = min(target_price, competitive_target)
        pricing_position = 'PRICE_ADVANTAGE'
    elif competitor is not None and floor_price <= competitor:
        recommended = min(target_price, competitor)
        pricing_position = 'MATCH_OR_BETTER_VALUE'
    elif competitor is not None:
        recommended = max(target_price, floor_price)
        pricing_position = 'SERVICE_VALUE_REQUIRED'
    else:
        recommended = max(target_price, floor_price)
        pricing_position = 'MARKET_BENCHMARK_REQUIRED'

    recommended = money(max(recommended, floor_price))
    gp = money(recommended - fully_loaded)
    margin = money((gp / recommended) * Decimal('100')) if recommended else Decimal('0')

    booking_ready = bool(d2d_ready and route.capacity_confirmed and route.compliance_cleared)
    if not d2d_ready:
        quote_status = 'DOOR_TO_DOOR_INCOMPLETE'
    elif booking_ready:
        quote_status = 'FIRM_QUOTE_ELIGIBLE'
    else:
        quote_status = 'PRELIMINARY_COMPLIANCE_OR_CAPACITY_PENDING'

    return {
        'route_id': route.route_id,
        'mode': route.mode,
        'service_level': route.service_level,
        'recommended_customer_price': float(recommended),
        'currency': 'USD',
        'pricing_position': pricing_position,
        'quote_status': quote_status,
        'booking_ready': booking_ready,
        'door_to_door_ready': d2d_ready,
        'service_score': _service_score(route),
        'transit_days': route.transit_days,
        'internal': {
            'base_operating_cost': float(base_cost),
            'contingency': float(contingency),
            'agency_share_reserve': float(agency_share),
            'home_partner_share_reserve': float(home_partner_share),
            'fully_loaded_cost': float(fully_loaded),
            'floor_price': float(money(floor_price)),
            'target_price': float(money(target_price)),
            'competitor_effective_price': float(competitor) if competitor is not None else None,
            'competitor_comparable_door_to_door': bool(competitor is not None),
            'gross_profit': float(gp),
            'gross_margin_pct': float(margin),
            'minimum_margin_pct': float(policy.minimum_margin_pct),
        },
        'customer_safe': {
            'price': float(recommended), 'currency': 'USD', 'mode': route.mode,
            'service_level': route.service_level, 'estimated_transit_days': route.transit_days,
            'tracking': route.tracking, 'pod': route.pod, 'claims_support': route.claims,
            'pickup': route.pickup, 'door_delivery': route.door_delivery,
            'delivery_standard': 'DOOR_TO_DOOR',
        },
    }


def rank_routes(candidates: list[dict]) -> list[dict]:
    def score(row: dict) -> tuple:
        internal = row.get('internal') or {}
        return (
            1 if row.get('door_to_door_ready') else 0,
            1 if row.get('booking_ready') else 0,
            int(row.get('service_score') or 0),
            float(internal.get('gross_profit') or 0),
            -float(row.get('recommended_customer_price') or 10**12),
            -int(row.get('transit_days') or 10**6),
        )
    return sorted(candidates, key=score, reverse=True)


def policy_snapshot() -> dict:
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in asdict(DEFAULT_POLICY).items()}
