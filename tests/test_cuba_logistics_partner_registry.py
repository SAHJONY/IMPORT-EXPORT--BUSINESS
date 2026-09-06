from cuba_logistics_network_api import _partner_projection, _registry_rows


def test_registry_contains_airline_forwarder_and_cuba_last_mile_layers():
    rows = _registry_rows()
    names = {row['name'] for row in rows}
    layers = {row['layer'] for row in rows}
    assert 'IBC Airways' in names
    assert 'Six World Shipping' in names
    assert 'Aerovaradero S.A.' in names
    assert 'Correos de Cuba / EMCI' in names
    assert 'AIRLINE_LIFT' in layers
    assert 'FREIGHT_FORWARDER' in layers
    assert 'CUBA_POSTAL_LAST_MILE' in layers


def test_unverified_rate_never_becomes_booking_ready():
    item = _partner_projection({
        'name': 'Example', 'commercial_status': 'RATE_REQUEST_REQUIRED', 'risk_level': 'MEDIUM'
    })
    assert item['rate_ready'] is False
    assert item['booking_allowed'] is False
    assert item['binding_quote_allowed'] is False
