from fastapi.testclient import TestClient

import public_conversion_api as api


class Store:
    def __init__(self): self.rows=[]
    async def insert(self, table, row):
        assert table == 'business_events'; self.rows.append(dict(row)); return [row]
    async def select(self, table, *, params=None):
        assert table == 'business_events'; return list(self.rows)


def test_public_event_stores_no_direct_personal_telemetry(monkeypatch):
    store=Store(); monkeypatch.setattr(api,'get_backend',lambda:store)
    client=TestClient(api.app)
    r=client.post('/conversion/event',json={'event':'rfq_submit','page':'/start','locale':'en','source':'static_rfq'})
    assert r.status_code == 200 and r.json()['accepted'] is True
    row=store.rows[0]
    payload=row['payload']
    assert set(payload) == {'event','page','locale','source'}
    assert row['visibility'] == 'owner'
    assert row['event_type'] == 'system'


def test_owner_dashboard_rates(monkeypatch):
    store=Store(); monkeypatch.setattr(api,'get_backend',lambda:store); monkeypatch.setattr(api,'verify_owner_token',lambda token: token=='ok')
    for event in ['rfq_view','rfq_view','rfq_submit','call_click','supplier_registration_start','supplier_registration_complete']:
        store.rows.append({'source_id':event,'payload':{'event':event},'created_at':'2026-09-14T00:00:00+00:00'})
    client=TestClient(api.app)
    r=client.get('/owner/conversion-dashboard',headers={'Authorization':'Bearer ok'})
    assert r.status_code == 200
    j=r.json()
    assert j['metrics']['rfq_submit_rate_pct'] == 50.0
    assert j['metrics']['call_click_rate_pct'] == 50.0
    assert j['metrics']['supplier_registration_completion_pct'] == 100.0
    assert j['targets']['rfq_submit_rate_pct'] == 4.0


def test_owner_dashboard_requires_owner(monkeypatch):
    monkeypatch.setattr(api,'verify_owner_token',lambda token: False)
    client=TestClient(api.app)
    assert client.get('/owner/conversion-dashboard',headers={'Authorization':'Bearer bad'}).status_code == 403

def test_supplier_demand_public_summary_enforces_k_anonymity(monkeypatch):
    store=Store(); monkeypatch.setattr(api,'get_backend',lambda:store)
    store.rows = []
    async def select(table, *, params=None):
        assert table == 'customer_trade_intakes'
        return [
            {'product_need':'industrial pump','destination_country':'US','quantity':10},
            {'product_need':'industrial motor','destination_country':'US','quantity':20},
            {'product_need':'machine equipment','destination_country':'US','quantity':30},
            {'product_need':'coffee beans','destination_country':'CO','quantity':50},
            {'product_need':'coffee beans','destination_country':'CO','quantity':60},
        ]
    store.select=select
    client=TestClient(api.app)
    r=client.get('/supplier-demand/public-summary')
    assert r.status_code == 200
    j=r.json()
    assert j['privacy_threshold'] == 3
    assert len(j['signals']) == 1
    assert j['signals'][0]['category'] == 'Industrial equipment'
    assert j['signals'][0]['rfq_count'] == 3
    assert j['signals'][0]['quantity_min'] == 10
    assert j['signals'][0]['quantity_max'] == 30
