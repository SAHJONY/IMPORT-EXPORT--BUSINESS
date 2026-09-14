from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def text(path):
    return (ROOT / path).read_text()


def test_homepage_plain_language_and_supplier_terms():
    app = text('src/App.tsx')
    assert 'Houston-based managed sourcing desk' in app
    assert 'Supplier terms' in app
    assert '/supplier-commercial-terms' in app


def test_language_control_is_top_visible():
    lang = text('public/global-language.js')
    assert '.sahjony-language{position:fixed;right:16px;top:16px;bottom:auto;' in lang
    for route in ['/es/customer-payments', '/es/supplier-commercial-terms', '/es/suppliers', '/es/supplier-cuba-terms']:
        assert route in lang


def test_payment_page_explains_methods_currency_and_invoice_controls():
    page = text('public/customer-payments.html')
    assert 'Methods & currencies' in page
    assert 'USD is the default currency shown in the public intake workflow' in page
    assert 'commercial quote or proforma' in page
    assert 'does not imply escrow' in page


def test_marketplace_has_real_evidence_lanes_not_fake_inventory():
    page = text('public/industrial-marketplace.html')
    assert 'CURRENT SOURCING LANES · EVIDENCE, NOT INVENTORY' in page
    assert 'India → Oman' in page
    assert '12–14 weeks' in page
    assert 'Qingdao → South Korea' in page
    assert 'not a completed shipment' in page


def test_native_spanish_commercial_pages_exist_and_routes_resolve():
    required = {
        '/es/customer-payments': 'customer-payments-es.html',
        '/es/supplier-commercial-terms': 'supplier-commercial-terms-es.html',
        '/es/suppliers': 'suppliers-es.html',
        '/supplier-cuba-terms': 'supplier-cuba-terms.html',
        '/es/supplier-cuba-terms': 'supplier-cuba-terms-es.html',
    }
    routes = json.loads(text('vercel.json'))['routes']
    mapping = {r.get('src'): r.get('dest') for r in routes if r.get('src')}
    for route, filename in required.items():
        assert mapping.get(route) == '/' + filename
        assert (ROOT / 'public' / filename).exists()


def test_supplier_cuba_terms_are_exporter_facing_and_nonbinding():
    en = text('public/supplier-cuba-terms.html')
    es = text('public/supplier-cuba-terms-es.html')
    assert 'Non-U.S. suppliers' in en
    assert 'There is no universal Cuba payment method' in en
    assert 'not legal advice' in en
    assert 'Proveedores no estadounidenses' in es
    assert 'No existe un método universal para Cuba' in es
