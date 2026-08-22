from __future__ import annotations

import os, secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from auth import verify_owner_token
from insforge_backend import get_backend

app=FastAPI(title='SAHJONY United States Import Desk',version='1.0.0',docs_url=None,redoc_url=None)
Role=Literal['owner','employee']
GATES=[
 ('supplier_screening','Supplier and restricted-party screening'),
 ('origin_export_controls','Origin-country export controls'),
 ('hts_classification','U.S. HTS classification verified'),
 ('customs_value','Customs valuation verified'),
 ('country_of_origin','Country of origin and marking verified'),
 ('pga_requirements','Partner Government Agency requirements verified'),
 ('importer_of_record','Importer of Record assigned and verified'),
 ('customs_broker','Customs broker assigned and verified'),
 ('customs_bond','Customs bond / entry authority verified'),
 ('payment_path','Supplier payment and banking path approved'),
 ('documents','Commercial invoice, packing list and required documents complete'),
 ('logistics','Forwarder/carrier/port path ready'),
 ('cargo_insurance','Cargo insurance verified or N/A'),
 ('duty_tax','Duty/tariff/tax treatment verified'),
 ('compliance_release','Compliance release approved'),
 ('owner_release','Owner final release'),
]

def now(): return datetime.now(timezone.utc).isoformat()
def emp_token():
 t=os.getenv('EMPLOYEE_TOKEN','').strip()
 if not t: raise HTTPException(503,'Employee access not configured')
 return t

def identity(role,authorization,employee_id):
 if role not in {'owner','employee'}: raise HTTPException(400,'X-Role must be owner or employee')
 if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
 token=authorization.removeprefix('Bearer ').strip()
 if role=='owner':
  if not verify_owner_token(token): raise HTTPException(403,'Invalid owner credential')
  return {'role':'owner','id':'owner'}
 if not secrets.compare_digest(token,emp_token()): raise HTTPException(403,'Invalid employee credential')
 return {'role':'employee','id':(employee_id or 'staff')[:160]}

class CaseIn(BaseModel):
 product_description:str=Field(min_length=2,max_length=1000)
 supplier_name:str|None=None
 supplier_country:str=Field(min_length=2,max_length=2)
 origin_country:str=Field(min_length=2,max_length=2)
 customer_ref:str|None=None
 assigned_employee_id:str|None=None
 managed_trade_case_id:str|None=None
 port_of_entry:str|None=None
 importer_of_record:str|None=None
 customs_broker:str|None=None
 freight_forwarder:str|None=None
 carrier:str|None=None
 incoterm:str|None=None
 hts_code:str|None=None
 country_of_origin_marking:str|None=None
 estimated_customs_value:float|None=None
 estimated_duty:float|None=None
 estimated_freight:float|None=None
 estimated_insurance:float|None=None
 estimated_other_costs:float|None=None
 currency:str='USD'

class GateIn(BaseModel):
 status:Literal['PASS','FAIL','NOT_APPLICABLE']
 evidence_reference:str|None=None
 notes:str|None=None

async def audit(actor,event,summary,case_id=None,payload=None):
 await get_backend().insert('us_import_audit',{'event_id':f'usia_{secrets.token_urlsafe(10)}','import_case_id':case_id,'actor_role':actor['role'],'actor_id':actor['id'],'event_type':event,'summary':summary,'payload':payload or {},'created_at':now()})

@app.get('/us-import/health')
async def health(): return {'status':'ok','service':'us-import-desk','destination':'US','fail_closed':True,'gates':len(GATES)}

@app.get('/us-import/cases')
async def list_cases(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id); params={'order':'updated_at.desc','limit':'250'}
 if actor['role']=='employee': params['assigned_employee_id']=f'eq.{actor["id"]}'
 return {'cases':await get_backend().select('us_import_cases',params=params) or []}

@app.post('/us-import/cases')
async def create_case(p:CaseIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id); cid=f'usi_{secrets.token_urlsafe(10)}'; ts=now()
 assigned=actor['id'] if actor['role']=='employee' else p.assigned_employee_id
 landed=sum(v or 0 for v in [p.estimated_customs_value,p.estimated_duty,p.estimated_freight,p.estimated_insurance,p.estimated_other_costs])
 row={'import_case_id':cid,**p.model_dump(),'supplier_country':p.supplier_country.upper(),'origin_country':p.origin_country.upper(),'destination_country':'US','assigned_employee_id':assigned,'estimated_landed_cost':landed,'status':'INTAKE','release_allowed':False,'owner_approved':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('us_import_cases',row)
 gates=[{'gate_id':f'usig_{secrets.token_urlsafe(10)}','import_case_id':cid,'gate_key':k,'label':label,'status':'PENDING','created_at':ts,'updated_at':ts} for k,label in GATES]
 await get_backend().insert('us_import_gates',gates); await audit(actor,'case_created','U.S. import case opened',cid)
 return {'case':row,'gates':gates}

@app.get('/us-import/cases/{case_id}/gates')
async def list_gates(case_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 identity(x_role,authorization,x_employee_id)
 return {'gates':await get_backend().select('us_import_gates',params={'import_case_id':f'eq.{case_id}','order':'id.asc','limit':'100'}) or []}

@app.patch('/us-import/cases/{case_id}/gates/{key}')
async def update_gate(case_id:str,key:str,p:GateIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if key not in {k for k,_ in GATES}: raise HTTPException(404,'Unknown import gate')
 if key in {'compliance_release','owner_release'} and actor['role']!='owner': raise HTTPException(403,'Only owner may approve compliance/final release')
 ts=now(); await get_backend().patch('us_import_gates',{'status':p.status,'evidence_reference':p.evidence_reference,'notes':p.notes,'reviewed_by':actor['id'],'reviewed_at':ts,'updated_at':ts},params={'import_case_id':f'eq.{case_id}','gate_key':f'eq.{key}'})
 if p.status=='FAIL': await get_backend().patch('us_import_cases',{'status':'HOLD','release_allowed':False,'owner_approved':False,'updated_at':ts},params={'import_case_id':f'eq.{case_id}'})
 await audit(actor,'gate_reviewed',f'{key} -> {p.status}',case_id)
 return {'import_case_id':case_id,'gate_key':key,'status':p.status}

@app.post('/us-import/cases/{case_id}/release')
async def release(case_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may release a U.S. import case')
 rows=await get_backend().select('us_import_cases',params={'import_case_id':f'eq.{case_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'U.S. import case not found')
 gates=await get_backend().select('us_import_gates',params={'import_case_id':f'eq.{case_id}','limit':'100'}) or []
 by={g.get('gate_key'):g.get('status') for g in gates}; missing=[k for k,_ in GATES if by.get(k) not in {'PASS','NOT_APPLICABLE'}]
 if missing: raise HTTPException(409,'U.S. import release blocked; incomplete gates: '+', '.join(missing))
 c=rows[0]
 required={'importer_of_record':c.get('importer_of_record'),'customs_broker':c.get('customs_broker'),'hts_code':c.get('hts_code'),'origin_country':c.get('origin_country')}
 absent=[k for k,v in required.items() if not v]
 if absent: raise HTTPException(409,'U.S. import release blocked; missing required fields: '+', '.join(absent))
 ts=now(); await get_backend().patch('us_import_cases',{'status':'READY_FOR_ENTRY','release_allowed':True,'owner_approved':True,'updated_at':ts},params={'import_case_id':f'eq.{case_id}'})
 await audit(actor,'case_released','Owner released U.S. import case for customs/logistics execution',case_id)
 return {'import_case_id':case_id,'status':'READY_FOR_ENTRY','release_allowed':True}
