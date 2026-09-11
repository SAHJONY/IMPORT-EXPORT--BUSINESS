from datetime import date, timedelta
from decimal import Decimal
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from fastapi import HTTPException
from deal_workbench import COSTS, DealWorksheet, evaluate
import business_readiness_api as api


def complete():
    return DealWorksheet(title='Test order', buyer='Buyer',buyer_contact='buyer@example.com',supplier='Supplier',product_spec='Product specification',quantity=10,unit='cases',origin='Origin port',destination='Mariel',incoterm='DAP named warehouse',buyer_evidence='demand-1',supplier_quote_evidence='quote-1',quote_valid_until=date.today()+timedelta(days=7),buyer_payment_terms='Balance on delivery',supplier_payment_terms='Advance',transaction_review_evidence='review-1',sale_total=2000,buyer_deposit_available=500,next_action='Owner reviews quote',costs={key:{'amount':1000 if key=='goods' else 0,'evidence':'quote-1' if key=='goods' else 'Included in goods quote'} for key in COSTS})


def test_unknown_cost_never_becomes_zero_profit():
    p=complete();del p.costs['international_freight']
    e=evaluate(p)
    assert e['delivered_cost'] is None
    assert e['projected_contribution'] is None
    assert e['full_cost_funding_gap'] is None
    assert e['status']=='INPUTS_REQUIRED'


def test_economics_and_funding_gap_are_order_totals():
    e=evaluate(complete())
    assert e['delivered_cost']==1000
    assert e['projected_contribution']==1000
    assert e['projected_margin_pct']==50
    assert e['full_cost_funding_gap']==500
    assert e['status']=='OWNER_REVIEW_READY'
    assert e['release_authorized'] is False
    assert e['collected_profit'] is None


def test_stale_quote_and_zero_without_evidence_block_review():
    p=complete();p.quote_valid_until=date.today()-timedelta(days=1);p.costs['insurance'].evidence=''
    e=evaluate(p)
    assert 'Supplier quote expired' in e['blockers']
    assert 'Cost evidence needed: insurance' in e['blockers']


def test_loss_and_excess_deposit_block_review():
    p=complete();p.sale_total=Decimal('900');p.buyer_deposit_available=Decimal('1000')
    e=evaluate(p)
    assert e['projected_contribution']==-100
    assert 'No positive projected contribution' in e['blockers']
    assert 'Buyer deposit exceeds sale total' in e['blockers']


@pytest.mark.parametrize('value',['NaN','Infinity','-1'])
def test_invalid_money_rejected(value):
    with pytest.raises(ValidationError):DealWorksheet(title='Test',sale_total=value)


def test_unknown_cost_category_rejected():
    with pytest.raises(ValidationError):DealWorksheet(title='Test',costs={'typo':{'amount':100}})


def test_owner_guard_and_persistence_roundtrip(monkeypatch):
    class Backend:
        def __init__(self):self.rows=[]
        async def insert(self,table,row):self.rows.append(row)
        async def select(self,table,params):return [r for r in self.rows if not params.get('id') or 'eq.'+r['id']==params['id']]
    b=Backend();monkeypatch.setattr(api,'get_backend',lambda:b)
    monkeypatch.setattr(api,'verify_owner_token',lambda token: token=='test-owner')
    c=TestClient(api.app)
    payload=complete().model_dump(mode='json')
    assert c.post('/business-readiness/deal-worksheets',json=payload,headers={'X-Role':'owner'}).status_code==401
    h={'X-Role':'owner','Authorization':'Bearer test-owner'}
    saved=c.post('/business-readiness/deal-worksheets',json=payload,headers=h)
    assert saved.status_code==200
    assert saved.json()['persisted'] is True
    rows=c.get('/business-readiness/deal-worksheets',headers=h).json()['worksheets']
    assert rows[0]['inputs']['title']=='Test order'
    assert rows[0]['evaluation']['projected_contribution']==1000
    assert rows[0]['outreach_authorized'] is False
    # Saving another snapshot retains the original.
    c.post('/business-readiness/deal-worksheets',json=payload,headers=h)
    assert len(b.rows)==2 and b.rows[0]['id']!=b.rows[1]['id']


def test_pricing_preview_identifies_missing_costs(monkeypatch):
    import pricing_api
    monkeypatch.setattr(pricing_api,'require_owner',lambda *a:None)
    c=TestClient(pricing_api.app)
    r=c.post('/owner-pricing/preview/business',json={'supplier_cost':100})
    assert r.status_code==200
    assert r.json()['costs_complete'] is False
    assert 'international_freight' in r.json()['missing_cost_fields']


def test_employee_cannot_read_or_save_owner_worksheets(monkeypatch):
    monkeypatch.setenv('EMPLOYEE_TOKEN','staff-token')
    c=TestClient(api.app)
    h={'X-Role':'employee','Authorization':'Bearer staff-token'}
    assert c.get('/business-readiness/deal-worksheets',headers=h).status_code==403
    assert c.post('/business-readiness/deal-worksheets',headers=h,json=complete().model_dump(mode='json')).status_code==403


def test_save_failure_never_reports_success(monkeypatch):
    class Backend:
        async def insert(self,*a):pass
        async def select(self,*a,**kw):return []
    monkeypatch.setattr(api,'get_backend',lambda:Backend())
    monkeypatch.setattr(api,'verify_owner_token',lambda token:True)
    c=TestClient(api.app)
    r=c.post('/business-readiness/deal-worksheets',headers={'X-Role':'owner','Authorization':'Bearer fixture'},json=complete().model_dump(mode='json'))
    assert r.status_code==503
