from fastapi.testclient import TestClient
import cuba_agency_network_api as mod
import agency_owner_api as owner_mod

class B:
    def __init__(self): self.t={"logistics_agency_owner_credentials":[{"agency_id":"a1","owner_id":"o1","token_hash":mod.hashlib.sha256(b"s1").hexdigest(),"status":"active"}]}
    async def select(self,table,params=None):
        rows=list(self.t.get(table,[])); params=params or {}
        for k,v in params.items():
            if k in {"limit","order"} or not isinstance(v,str) or not v.startswith("eq."): continue
            rows=[r for r in rows if str(r.get(k))==v[3:]]
        return rows
    async def insert(self,table,row): self.t.setdefault(table,[]).append(dict(row)); return row
    async def patch(self,table,patch,params=None):
        rows=await self.select(table,params)
        for r in self.t.get(table,[]):
            if r in rows:r.update(patch)
        return rows

def h(): return {"Authorization":"Bearer s1","X-Agency-Id":"a1"}

def test_package_qr_and_public_tracking(monkeypatch):
    b=B(); monkeypatch.setattr(mod,"get_backend",lambda:b); monkeypatch.setattr(owner_mod,"get_backend",lambda:b); c=TestClient(mod.app)
    r=c.post('/agency-network/packages',headers=h(),json={"recipient_name":"Ana Perez","destination_province":"La Habana","description":"Ropa"})
    assert r.status_code==200
    token=r.json()['package']['public_tracking_token']
    pub=c.get('/agency-network/public/'+token)
    assert pub.status_code==200 and pub.json()['stage']=='CREATED'

def test_offline_custody_is_idempotent(monkeypatch):
    b=B(); monkeypatch.setattr(mod,"get_backend",lambda:b); monkeypatch.setattr(owner_mod,"get_backend",lambda:b); c=TestClient(mod.app)
    p=c.post('/agency-network/packages',headers=h(),json={"recipient_name":"Ana Perez","destination_province":"La Habana","description":"Ropa","weight_lb":10}).json()['package']
    body={"package_id":p['package_id'],"action":"SCAN_IN","stage":"WAREHOUSE_IN","weight_lb":12,"offline_event_id":"offline-123"}
    a=c.post('/agency-network/custody',headers=h(),json=body).json(); d=c.post('/agency-network/custody',headers=h(),json=body).json()
    assert a['created'] is True and d['idempotent_replay'] is True
    assert b.t['logistics_agency_packages'][0]['status']=='EXCEPTION'

def test_delivery_exception_opens_claim(monkeypatch):
    b=B(); monkeypatch.setattr(mod,"get_backend",lambda:b); monkeypatch.setattr(owner_mod,"get_backend",lambda:b); c=TestClient(mod.app)
    p=c.post('/agency-network/packages',headers=h(),json={"recipient_name":"Ana Perez","destination_province":"Holguin","description":"Medicinas"}).json()['package']
    r=c.post('/agency-network/deliveries',headers=h(),json={"package_id":p['package_id'],"recipient_name":"Ana Perez","parcel_count":1,"condition":"DAMAGED","recipient_confirmation":"CONFIRMED_PROBLEM","signature_method":"DRAW","signature_value":"sig","offline_event_id":"delivery-123","comments":"Caja dañada"})
    assert r.status_code==200 and r.json()['claim_opened'] is True
    assert r.json()['signature_value_persisted'] is False
    assert len(b.t['logistics_agency_exceptions'])==1
