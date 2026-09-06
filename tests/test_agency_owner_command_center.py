from fastapi.testclient import TestClient
import agency_owner_api as mod

class FakeBackend:
    def __init__(self):
        self.tables={
            'logistics_agencies':[{'agency_id':'agy_a','legal_name':'Agency A','owner_name':'Owner A','status':'active'}],
            'logistics_agency_owner_credentials':[{'agency_id':'agy_a','owner_id':'owner_a','token_hash':mod.digest('secret-a'),'status':'active'}],
            'logistics_agency_employees':[{'employee_id':'emp_a','agency_id':'agy_a','full_name':'Worker A','status':'active'}],
            'logistics_agency_shipments':[{'agency_shipment_id':'s1','agency_id':'agy_a','tracking_reference':'A-1','status':'CREATED','customer_price':10,'agency_cost':7}],
            'logistics_agency_payment_providers':[], 'logistics_agency_payments':[], 'logistics_agency_payment_settlements':[],
        }
    async def select(self, table, params=None):
        rows=list(self.tables.get(table,[])); params=params or {}
        for k,v in params.items():
            if k in {'limit','order'} or not isinstance(v,str) or not v.startswith('eq.'): continue
            val=v[3:]; rows=[r for r in rows if str(r.get(k))==val]
        return rows
    async def insert(self, table, row): self.tables.setdefault(table,[]).append(dict(row)); return row
    async def patch(self, table, patch, params=None):
        rows=await self.select(table,params)
        for r in self.tables.get(table,[]):
            if r in rows: r.update(patch)
        return rows

def test_agency_owner_is_tenant_scoped(monkeypatch):
    b=FakeBackend(); monkeypatch.setattr(mod,'get_backend',lambda:b)
    c=TestClient(mod.app); h={'Authorization':'Bearer secret-a','X-Agency-Id':'agy_a'}
    assert c.get('/agency-os/me',headers=h).status_code==200
    assert c.get('/agency-os/summary',headers=h).json()['metrics']['gross_profit']==3.0
    assert c.get('/agency-os/me',headers={**h,'X-Agency-Id':'agy_b'}).status_code==403

def test_only_agency_owner_updates_employee_access(monkeypatch):
    b=FakeBackend(); monkeypatch.setattr(mod,'get_backend',lambda:b)
    c=TestClient(mod.app); h={'Authorization':'Bearer secret-a','X-Agency-Id':'agy_a'}
    r=c.patch('/agency-os/employees/emp_a/access',headers=h,json={'status':'suspended','permissions':['scan','pod']})
    assert r.status_code==200
    assert b.tables['logistics_agency_employees'][0]['status']=='suspended'
    assert b.tables['logistics_agency_employees'][0]['access_granted_by_owner_id']=='owner_a'

def test_paperless_record_is_tenant_scoped_and_signature_not_stored_raw(monkeypatch):
    b=FakeBackend(); b.tables['logistics_agency_paperless_records']=[]; monkeypatch.setattr(mod,'get_backend',lambda:b)
    c=TestClient(mod.app); h={'Authorization':'Bearer secret-a','X-Agency-Id':'agy_a'}
    r=c.post('/agency-os/paperless/records',headers=h,json={'record_type':'POD','title':'Final delivery','related_type':'shipment','related_id':'s1','signer_name':'Receiver','signature_method':'DRAWN','signature_value':'raw-signature'})
    assert r.status_code==200
    row=b.tables['logistics_agency_paperless_records'][0]
    assert row['agency_id']=='agy_a' and row['status']=='SIGNED'
    assert row['signature_hash']==mod.digest('raw-signature')
    assert 'signature_value' not in row
    assert c.get('/agency-os/paperless/records',headers={**h,'X-Agency-Id':'agy_b'}).status_code==403

def test_agency_owner_controls_paperless_release(monkeypatch):
    b=FakeBackend(); b.tables['logistics_agency_paperless_records']=[{'record_id':'apr_1','agency_id':'agy_a','record_type':'POD','title':'Delivery','status':'SIGNED'}]; monkeypatch.setattr(mod,'get_backend',lambda:b)
    c=TestClient(mod.app); h={'Authorization':'Bearer secret-a','X-Agency-Id':'agy_a'}
    r=c.patch('/agency-os/paperless/records/apr_1/status',headers=h,json={'status':'RELEASED','note':'Owner approved'})
    assert r.status_code==200
    assert b.tables['logistics_agency_paperless_records'][0]['status']=='RELEASED'
    assert b.tables['logistics_agency_paperless_records'][0]['updated_by_owner_id']=='owner_a'


def test_payment_layer_is_provider_agnostic_and_tenant_scoped(monkeypatch):
    b=FakeBackend(); monkeypatch.setattr(mod,'get_backend',lambda:b)
    c=TestClient(mod.app); h={'Authorization':'Bearer secret-a','X-Agency-Id':'agy_a'}
    pr=c.post('/agency-os/payments/providers',headers=h,json={'provider_name':'Any POS','provider_type':'EXTERNAL_POS','integration_mode':'REFERENCE_ONLY'})
    assert pr.status_code==200
    pid=pr.json()['provider']['provider_id']
    r=c.post('/agency-os/payments',headers=h,json={'amount':125.50,'method':'CARD','provider_id':pid,'external_reference':'TXN-001','fee_amount':3.50,'card_brand':'VISA','card_last4':'4242'})
    assert r.status_code==200
    body=r.json(); assert body['pan_stored'] is False and body['cvv_stored'] is False
    assert body['payment']['net_amount']==122.0
    assert c.get('/agency-os/payments',headers={**h,'X-Agency-Id':'agy_b'}).status_code==403

def test_settlement_only_accepts_same_agency_payments(monkeypatch):
    b=FakeBackend(); monkeypatch.setattr(mod,'get_backend',lambda:b)
    c=TestClient(mod.app); h={'Authorization':'Bearer secret-a','X-Agency-Id':'agy_a'}
    r=c.post('/agency-os/payments',headers=h,json={'amount':50,'method':'CASH','external_reference':'CASH-001'})
    pid=r.json()['payment']['payment_id']
    s=c.post('/agency-os/payments/settlements',headers=h,json={'payment_ids':[pid],'settlement_reference':'SET-1','settled_amount':50})
    assert s.status_code==200 and s.json()['payments_reconciled']==1
    assert b.tables['logistics_agency_payments'][0]['status']=='SETTLED'


def test_zelle_and_cash_app_are_supported_payment_rails(monkeypatch):
    b=FakeBackend(); monkeypatch.setattr(mod,'get_backend',lambda:b)
    c=TestClient(mod.app); h={'Authorization':'Bearer secret-a','X-Agency-Id':'agy_a'}
    z=c.post('/agency-os/payments',headers=h,json={'amount':75,'method':'ZELLE','external_reference':'ZELLE-001','sender_reference':'+12815550123'})
    assert z.status_code==200 and z.json()['payment']['method']=='ZELLE'
    ca=c.post('/agency-os/payments',headers=h,json={'amount':42,'method':'CASH_APP','external_reference':'CA-001','sender_reference':'$customer'})
    assert ca.status_code==200 and ca.json()['payment']['method']=='CASH_APP'


def test_paypal_is_supported_payment_rail(monkeypatch):
    b=FakeBackend(); monkeypatch.setattr(mod,'get_backend',lambda:b)
    c=TestClient(mod.app); h={'Authorization':'Bearer secret-a','X-Agency-Id':'agy_a'}
    r=c.post('/agency-os/payments',headers=h,json={'amount':88.25,'method':'PAYPAL','external_reference':'PP-001','sender_reference':'payer@example.com'})
    assert r.status_code==200 and r.json()['payment']['method']=='PAYPAL'


def test_any_debit_card_via_external_processor_is_supported(monkeypatch):
    b=FakeBackend(); monkeypatch.setattr(mod,'get_backend',lambda:b)
    c=TestClient(mod.app); h={'Authorization':'Bearer secret-a','X-Agency-Id':'agy_a'}
    r=c.post('/agency-os/payments',headers=h,json={'amount':19.99,'method':'DEBIT_CARD','external_reference':'POS-DEBIT-001','card_brand':'MASTERCARD','card_last4':'1234'})
    assert r.status_code==200
    body=r.json(); assert body['payment']['method']=='DEBIT_CARD' and body['pan_stored'] is False and body['cvv_stored'] is False
