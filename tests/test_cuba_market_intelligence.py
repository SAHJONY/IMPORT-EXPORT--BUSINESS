from datetime import date
from cuba_market_intelligence import enrich, compare_prices
from insforge_backend import _record_key

def test_research_score_never_makes_a_deal():
    p=enrich({'observed_activity':'Instalación de paneles solares','public_emails':['sales@example.com']})
    assert p['supplier_ids']==['longi']
    assert p['ready_to_quote'] is False
    assert p['estimated_profit'] is None
    assert 'BUYER_DEMAND_UNCONFIRMED' in p['blockers']

def test_unrelated_service_does_not_get_supplier_matches():
    assert enrich({'observed_activity':'Programación informática','province':'Villa Clara'})['supplier_ids']==[]

def offer(**changes):
    return dict(product_spec='rice A 25kg',currency='USD',unit='MT',quantity=20,destination='Havana',incoterm='DAP',included_costs=['goods','freight','delivery'],payment_terms='prepaid',valid_until='2026-12-31',source_url='https://example.com/quote',landed_cost_complete=True,price=700,**changes)

def test_comparable_landed_price():
    a=offer();b=offer();b['price']=750
    assert compare_prices(a,b,date(2026,9,10))=={'comparable':True,'cheaper':True,'savings':50.0,'blockers':[]}

def test_port_to_port_not_compared_to_delivered_and_expired_quote_rejected():
    a=offer();b=offer();a['landed_cost_complete']=False;b['valid_until']='2026-09-01';b['quantity']=1
    r=compare_prices(a,b,date(2026,9,10))
    assert not r['comparable'] and r['cheaper'] is None
    assert set(r['blockers'])=={'DIFFERENT_QUANTITY','OFFER_LANDED_COST_INCOMPLETE','COMPETITOR_EXPIRED'}

def test_missing_and_nonfinite_prices_do_not_become_savings():
    for value in [None,0,-1,'NaN','Infinity']:
        a=offer();a['price']=value
        assert compare_prices(a,offer(),date(2026,9,10))['cheaper'] is None

def test_candidates_in_same_request_have_distinct_keys():
    a={'sourcing_request_id':'same','global_candidate_id':'one'}
    b={'sourcing_request_id':'same','global_candidate_id':'two'}
    assert _record_key(a)!=_record_key(b)

def test_private_research_requires_owner(monkeypatch):
    from fastapi.testclient import TestClient
    import global_supplier_sourcing_api as api
    client=TestClient(api.app)
    assert client.get('/global-sourcing/cuba-prospects').status_code in (400,401)
    monkeypatch.setattr(api,'identity',lambda *_:{'role':'employee','id':'staff'})
    assert client.get('/global-sourcing/cuba-prospects').status_code==403
    assert client.post('/global-sourcing/cuba-prospects/renova/import').status_code==403
    assert client.post('/global-sourcing/compare-prices',json={'offer':{},'competitor':{}}).status_code==403

def test_private_research_reads_crm_and_price_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    import global_supplier_sourcing_api as api
    class Backend:
        async def select(self,table,params=None):
            assert table=='cuba_market_research'
            return [{'kind':'BUYER','id':'one','priority_score':5},{'kind':'PROVIDER','id':'carrier'}]
    monkeypatch.setattr(api,'get_backend',lambda:Backend())
    monkeypatch.setattr(api,'identity',lambda *_:{'role':'owner','id':'owner'})
    client=TestClient(api.app)
    data=client.get('/global-sourcing/cuba-prospects').json()
    assert data['source']=='CRM' and len(data['prospects'])==1 and len(data['providers'])==1
    assert data['confirmed_deals']==0
    result=client.post('/global-sourcing/compare-prices',json={'offer':{},'competitor':{}}).json()
    assert result['comparable'] is False and result['cheaper'] is None
