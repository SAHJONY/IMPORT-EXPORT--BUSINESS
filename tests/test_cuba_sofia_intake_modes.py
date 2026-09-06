from cuba_sofia_sales_bridge_api import classify_customer_intent


def test_pallet_purchase_is_not_forced_to_container():
    result = classify_customer_intent('Quiero comprar 4 pales de aceite para enviar a Cuba')
    assert result['intent'] == 'PALLET_PURCHASE'
    assert any('numero aproximado de pales' in q for q in result['questions'])
    assert 'incoterm' in result['first_contact_do_not_require']


def test_consolidated_cargo_is_detected():
    result = classify_customer_intent('Necesito una carga consolidada para La Habana')
    assert result['intent'] == 'CONSOLIDATED_CARGO_PURCHASE'
    assert any('cantidad aproximada' in q for q in result['questions'])


def test_shipping_only_is_separate_from_sourcing():
    result = classify_customer_intent('Ya tengo la mercancia, solo quiero enviar a Cuba')
    assert result['intent'] == 'SHIPPING_ONLY'
    assert any('ciudad/pais de origen' in q for q in result['questions'])


def test_vehicle_and_food_have_specialized_intake():
    vehicle = classify_customer_intent('Quiero comprar un carro para Santiago de Cuba')
    food = classify_customer_intent('Necesito arroz y aceite para mi negocio')
    assert vehicle['intent'] == 'VEHICLE_PURCHASE'
    assert food['intent'] == 'FOOD_AGRI_PURCHASE'
