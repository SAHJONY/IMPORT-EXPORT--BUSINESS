from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def text(name): return (ROOT/'public'/name).read_text()
def test_supplier_home_has_real_post_registration_contract():
    page=text('suppliers.html')
    assert '24–48 business hours' in page
    assert 'Reference:' in page
    assert 'registration/qualification collects no fee' in page
    assert '/supplier-commercial-terms' in page

def test_supplier_commercial_policy_removes_blank_check():
    page=text('supplier-commercial-terms.html')
    assert '$0' in page
    assert 'No universal percentage' in page
    assert 'Registration itself creates no exclusivity' in page
    assert 'Submitted supplier pricing is non-public by default' in page

def test_supplier_demand_is_real_and_anonymized():
    page=text('supplier-demand.html')
    assert '/canonical-deals.json' in page
    assert 'SAHJONY-MOTOR-OM-20FT' in page
    assert 'food-processing-equipment RFQ' in page
    assert 'Buyer identities remain private' in page

def test_supplier_routes_are_real():
    cfg=json.loads((ROOT/'vercel.json').read_text())
    m={r.get('src'):r.get('dest') for r in cfg['routes'] if isinstance(r,dict)}
    assert m['/suppliers/demand']=='/supplier-demand.html'
    assert m['/suppliers/contact']=='/supplier-contact.html'
    assert m['/supplier-quote']=='/supplier-quote.html'
    assert m['/supplier-commercial-terms']=='/supplier-commercial-terms.html'

def test_homepage_exposes_supplier_entry():
    app=(ROOT/'src'/'App.tsx').read_text()
    assert 'href="/suppliers">Suppliers</a>' in app
    assert 'I sell / manufacture' in app
