from decimal import Decimal

from logistics_profit_optimizer import RouteCandidate, optimize_route, rank_routes


def route(**overrides):
    data = dict(
        route_id='sea-houston-miami', mode='SEA', service_level='STANDARD',
        linehaul_cost=Decimal('20'), international_freight=Decimal('40'),
        origin_handling=Decimal('5'), destination_handling=Decimal('5'),
        last_mile=Decimal('10'), compliance_cost=Decimal('2'),
        insurance_cost=Decimal('1'), payment_cost=Decimal('1'),
        transit_days=20, tracking=True, pod=True, claims=True,
        pickup=True, door_delivery=True, capacity_confirmed=True,
        compliance_cleared=True,
    )
    data.update(overrides)
    return RouteCandidate(**data)


def test_never_undercuts_below_margin_floor():
    result = optimize_route(route(), competitor_effective_price=50)
    assert result['internal']['gross_margin_pct'] >= result['internal']['minimum_margin_pct']
    assert result['pricing_position'] == 'SERVICE_VALUE_REQUIRED'


def test_undercuts_when_profitable():
    result = optimize_route(route(), competitor_effective_price=160)
    assert result['pricing_position'] == 'PRICE_ADVANTAGE'
    assert result['recommended_customer_price'] < 160
    assert result['internal']['gross_profit'] >= 5


def test_agency_and_home_partner_reserves_are_protected():
    result = optimize_route(route(), customer_type='AGENCY', agency_partner=True, home_collection_partner=True)
    assert result['internal']['agency_share_reserve'] > 0
    assert result['internal']['home_partner_share_reserve'] > 0
    assert result['internal']['gross_margin_pct'] >= result['internal']['minimum_margin_pct']


def test_compliance_or_capacity_keeps_quote_preliminary():
    result = optimize_route(route(compliance_cleared=False), competitor_effective_price=150)
    assert result['booking_ready'] is False
    assert result['quote_status'] == 'PRELIMINARY_COMPLIANCE_OR_CAPACITY_PENDING'


def test_rank_routes_rewards_booking_service_profit_and_price():
    a = optimize_route(route(route_id='a'), competitor_effective_price=160)
    b = optimize_route(route(route_id='b', tracking=False, pod=False), competitor_effective_price=160)
    ranked = rank_routes([b, a])
    assert ranked[0]['route_id'] == 'a'
