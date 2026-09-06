from fastapi.testclient import TestClient
import cuba_private_sector_lead_api as api


def test_health_exposes_small_business_shipping_modes():
    c=TestClient(api.app)
    r=c.get('/cuba-private-sector/health')
    assert r.status_code == 200
    j=r.json()
    assert j['small_orders_enabled'] is True
    assert j['lcl_consolidation_enabled'] is True
    assert j['customer_paid_shipping_enabled'] is True
    assert j['shipping_quote_separate'] is True
    assert j['default_business_readiness'] == 'BUSINESS_REVIEW_REQUIRED'


def test_business_request_requires_customer_paid_shipping():
    try:
        api.PublicLeadIn(
            business_name='Empresa Demo', contact_name='Comprador Demo', contact_method='EMAIL',
            email='buyer@example.com', product_need='EcoFlow DELTA 3', consent_to_business_contact=True,
            customer_pays_shipping=False,
        )
        assert False, 'expected validation failure'
    except Exception as exc:
        assert 'separately quoted shipping costs' in str(exc)
