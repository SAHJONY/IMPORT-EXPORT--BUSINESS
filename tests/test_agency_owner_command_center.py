from fastapi.testclient import TestClient
import agency_owner_api as mod

class FakeBackend:
    def __init__(self):
        self.tables={
            'logistics_agencies':[{'agency_id':'agy_a','legal_name':'Agency A','owner_name':'Owner A','status':'active'}],
            'logistics_agency_owner_credentials':[{'agency_id':'agy_a','owner_id':'owner_a','token_hash':mod.digest('secret-a'),'status':'active'}],
            'logistics_agency_employees':[{'employee_id':'emp_a','agency_id':'agy_a','full_name':'Worker A','status':'active'}],
            'logistics_agency_shipments':[{'agency_shipment_id':'s1','agency_id':'agy_a','tracking_reference':'A-1','status':'CREATED','customer_price':10,'agency_cost':7}],
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
