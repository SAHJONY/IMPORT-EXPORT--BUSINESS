from logistics_go_to_business_api import CityActivationIn, PartnerEconomicsIn, activation_gates, city_stage, economics


def city(**overrides):
    data = dict(
        city='Houston', state='TX', verified_agencies=2, verified_collection_partners=1,
        verified_trucking_options=2, verified_gateway_options=2, verified_last_mile_options=2,
        live_door_to_door_rate_available=True, compliance_route_validated=True,
        pod_capable=True, pilot_shipments_completed=30, collected_gross_profit_usd=2500,
        claim_rate_pct=1.0, on_time_delivery_pct=95.0,
    )
    data.update(overrides)
    return CityActivationIn(**data)


def test_city_reaches_scale_only_with_complete_network():
    assert city_stage(city()) == 'SCALE'
    assert all(g['passed'] for g in activation_gates(city()))


def test_missing_last_mile_blocks_activation():
    p = city(verified_last_mile_options=0)
    assert city_stage(p) == 'PROVIDER_DISCOVERY'
    assert any(g['gate'] == 'LAST_MILE' and not g['passed'] for g in activation_gates(p))


def test_no_live_door_to_door_rate_blocks_commercial_validation():
    p = city(live_door_to_door_rate_available=False)
    assert city_stage(p) == 'COMMERCIAL_VALIDATION'


def test_partner_economics_protect_sahjony_gp():
    p = PartnerEconomicsIn(
        partner_type='SHIPPING_AGENCY', provider_cost_usd=70, customer_price_usd=100,
        agency_margin_usd=10, partner_payout_usd=5, payment_cost_usd=2,
        claims_reserve_usd=3, minimum_sahjony_gp_usd=5,
    )
    result = economics(p)
    assert result['profit_floor_passed'] is True
    assert result['sahjony_gross_profit_usd'] == 10


def test_unprofitable_partner_structure_is_not_released():
    p = PartnerEconomicsIn(
        partner_type='LAST_MILE_PROVIDER', provider_cost_usd=92, customer_price_usd=100,
        agency_margin_usd=4, partner_payout_usd=2, payment_cost_usd=2,
        claims_reserve_usd=1, minimum_sahjony_gp_usd=5,
    )
    result = economics(p)
    assert result['profit_floor_passed'] is False
    assert result['release'] == 'COMMERCIAL_REVIEW'
