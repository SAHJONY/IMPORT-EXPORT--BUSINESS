from fastapi.testclient import TestClient
import agency_freight_ops_api as mod
import agency_owner_api as owner_mod

class B:
    def __init__(self): self.t={'logistics_agency_owner_credentials':[{'agency_id':'a1','owner_id':'o1','token_hash':owner_mod.digest('s1'),'status':'active'}],'logistics_agency_packages':[{'agency_id':'a1','package_id':'pkg1','stage':'WAREHOUSE_IN'}]}
    async def select(self,table,params=None):
        rows=list(self.t.get(table,[])); params=params or {}
        for k,v in params.items():
            if k in {'limit','order'} or not isinstance(v,str) or not v.startswith('eq.'): continue
            rows=[r for r in rows if str(r.get(k))==v[3:]]
        return rows
    async def insert(self,table,row): self.t.setdefault(table,[]).append(dict(row)); return row
    async def patch(self,table,patch,params=None):
        rows=await self.select(table,params)
        for r in self.t.get(table,[]):
            if r in rows: r.update(patch)
        return rows

def h(): return {'Authorization':'Bearer s1','X-Agency-Id':'a1'}
def setup(monkeypatch):
    b=B(); monkeypatch.setattr(mod,'get_backend',lambda:b); monkeypatch.setattr(owner_mod,'get_backend',lambda:b); return b,TestClient(mod.app)

def test_consolidation_house_master_and_route(monkeypatch):
    b,c=setup(monkeypatch)
    con=c.post('/agency-freight/consolidations',headers=h(),json={'name':'HAV-AIR-01','mode':'AIR','origin':'Miami','destination':'Havana'}).json()['consolidation']
    r=c.post(f"/agency-freight/consolidations/{con['consolidation_id']}/items",headers=h(),json={'package_id':'pkg1','pieces':2,'weight_lb':25})
    assert r.status_code==200 and r.json()['summary']['piece_count']==2
    assert b.t['logistics_agency_packages'][0]['stage']=='CONSOLIDATED'
    d=c.post('/agency-freight/documents',headers=h(),json={'document_type':'HAWB','number':'HAWB-1','consolidation_id':con['consolidation_id']})
    assert d.status_code==200 and d.json()['printable'] is True
    route=c.post('/agency-freight/routes',headers=h(),json={'name':'Havana 1','destination_province':'La Habana','package_ids':['pkg1']})
    assert route.status_code==200 and route.json()['route']['stops']==1

def test_tariff_and_transitaria_invoice(monkeypatch):
    b,c=setup(monkeypatch)
    con=c.post('/agency-freight/consolidations',headers=h(),json={'name':'MAR-01','mode':'SEA','origin':'Miami','destination':'Mariel'}).json()['consolidation']
    t=c.post('/agency-freight/tariffs',headers=h(),json={'name':'Air lb','currency':'USD','basis':'PER_LB','amount':3.5,'applies_to':'PACKAGE'})
    assert t.status_code==200
    inv=c.post('/agency-freight/agency-invoices',headers=h(),json={'billed_agency_reference':'agency-b','consolidation_id':con['consolidation_id'],'currency':'USD','subtotal':100,'fees':12.5})
    assert inv.status_code==200 and inv.json()['invoice']['total']==112.5

def test_customs_links_are_contextual(monkeypatch):
    b,c=setup(monkeypatch)
    ca=c.get('/agency-freight/customs-links?origin_country=CA',headers=h())
    assert ca.status_code==200
    data=ca.json()
    assert data['origin_country']=='CANADA'
    assert any('CERS' in x['name'] for x in data['origin_customs'])
    assert any('Aduana' in x['name'] for x in data['destination_customs'])
    us=c.get('/agency-freight/customs-links?origin_country=USA',headers=h())
    assert us.status_code==200 and any('AES' in x['name'] for x in us.json()['origin_customs'])
