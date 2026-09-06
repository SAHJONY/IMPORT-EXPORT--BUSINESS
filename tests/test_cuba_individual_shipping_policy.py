from cuba_consumer_marketplace_api import ConsumerRequestIn, request_notes


def test_individual_order_defaults_to_customer_paid_shipping():
    req = ConsumerRequestIn(
        full_name='Cliente Cuba',
        email='cliente@example.com',
        category='SOLAR_BACKUP',
        product_description='EcoFlow DELTA portable power station',
        intended_use='Respaldo electrico familiar durante apagones',
    )
    assert req.shipping_option == 'SAHJONY_ARRANGED'
    assert req.customer_pays_shipping is True
    assert req.consolidation_ok is True
    notes = request_notes(req)
    assert 'ORDER_MODE=INDIVIDUAL' in notes
    assert 'SHIPPING_PAYER=CUSTOMER' in notes
    assert 'SHIPPING_QUOTED_SEPARATELY=TRUE' in notes


def test_customer_can_choose_consolidated_shipping():
    req = ConsumerRequestIn(
        full_name='Cliente Cuba',
        phone='+5355555555',
        category='SOLAR_BACKUP',
        product_description='EcoFlow RIVER',
        intended_use='Respaldo personal',
        shipping_option='CONSOLIDATED',
    )
    assert 'SHIPPING_OPTION=CONSOLIDATED' in request_notes(req)
