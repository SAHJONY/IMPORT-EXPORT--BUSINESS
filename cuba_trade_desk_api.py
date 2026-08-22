from __future__ import annotations

import os, secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from auth import verify_owner_token
from insforge_backend import get_backend

app=FastAPI(title='SAHJONY Cuba Authorized Trade Desk',version='1.1.0',docs_url=None,redoc_url=None)
Role=Literal['owner','employee']
REQUIRED_GATES=[
 ('private_business_eligibility','Cuban private business / independent private sector eligibility'),
 ('product_classification','Product classification / ECCN or EAR99'),
 ('authorization_scope','Government authorization / license exception scope'),
 ('end_user_end_use','End user and end use eligibility'),
 ('restricted_party_screening','Restricted-party / sanctions screening'),
 ('banking_payment','Banking and payment path compliance'),
 ('documents','Required commercial/export/customs documents'),
 ('logistics','Carrier / forwarder acceptance and route compliance'),
 ('recordkeeping','Required compliance and recordkeeping evidence'),
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

class EmployeeIn(BaseModel):
 employee_id:str=Field(min_length=1,max_length=160)
 display_name:str=Field(min_length=2,max_length=160)
 email:str|None=None
 may_prepare:bool=True
 may_submit:bool=False

class AuthorizationIn(BaseModel):
 employee_id:str
 authorization_type:str
 authority:str
 reference_number:str|None=None
 license_exception:str|None=None
 legal_basis:str
 effective_at:str|None=None
 expires_at:str|None=None
 scope_products:list[str]=[]
 scope_eccns:list[str]=[]
 scope_end_users:list[str]=[]
 scope_end_uses:list[str]=[]
 evidence_document_id:str|None=None
 notes:str|None=None

class CaseIn(BaseModel):
 employee_id:str
 authorization_id:str|None=None
 private_business_id:str|None=None
 product_description:str
 product_id:str|None=None
 eccn:str|None=None
 ear99:bool|None=None
 quantity:float|None=None
 transaction_value:float|None=None
 currency:str='USD'
 consignee_name:str
 end_user_name:str
 end_use:str
 payment_path:str|None=None
 bank_name:str|None=None

class GateUpdate(BaseModel):
 status:Literal['PASS','FAIL','NOT_APPLICABLE']
 evidence_summary:str=Field(min_length=2,max_length=4000)
 evidence_reference:str|None=None

async def audit(case_id,actor,event,summary,payload=None):
 await get_backend().insert('cuba_trade_audit',{'event_id':f'cta_{secrets.token_urlsafe(10)}','trade_case_id':case_id,'actor_role':actor['role'],'actor_id':actor['id'],'event_type':event,'summary':summary,'payload':payload or {},'created_at':now()})

@app.get('/cuba-desk/health')
async def health(): return {'status':'ok','service':'cuba-authorized-trade-desk','country':'CU','fail_closed':True,'required_gates':len(REQUIRED_GATES),'employee_release_authority':False,'private_business_eligibility_required_when_linked':True}

@app.get('/cuba-desk/employees')
async def employees(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 rows=await get_backend().select('cuba_trade_employees',params={'order':'display_name.asc','limit':'200'}) or []
 if actor['role']=='employee': rows=[r for r in rows if r.get('employee_id')==actor['id']]
 return {'employees':rows}

@app.post('/cuba-desk/employees')
async def add_employee(p:EmployeeIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may create Cuba trade employees')
 row={'employee_id':p.employee_id,'display_name':p.display_name,'email':p.email,'status':'ACTIVE','may_prepare':p.may_prepare,'may_submit':p.may_submit,'may_release':False,'created_at':now(),'updated_at':now()}
 await get_backend().insert('cuba_trade_employees',row)
 return {'employee':row}

@app.post('/cuba-desk/authorizations')
async def add_authorization(p:AuthorizationIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may register government authorizations')
 aid=f'cua_{secrets.token_urlsafe(10)}'
 row={'authorization_id':aid,**p.model_dump(),'status':'PENDING','created_at':now(),'updated_at':now()}
 await get_backend().insert('cuba_trade_authorizations',row)
 return {'authorization':row}

@app.post('/cuba-desk/authorizations/{authorization_id}/verify')
async def verify_authorization(authorization_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may verify government authorizations')
 ts=now(); await get_backend().patch('cuba_trade_authorizations',{'status':'VERIFIED','verified_by':actor['id'],'verified_at':ts,'updated_at':ts},params={'authorization_id':f'eq.{authorization_id}'})
 return {'authorization_id':authorization_id,'status':'VERIFIED'}

@app.get('/cuba-desk/cases')
async def cases(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 params={'order':'created_at.desc','limit':'200'}
 if actor['role']=='employee': params['employee_id']=f'eq.{actor["id"]}'
 return {'cases':await get_backend().select('cuba_trade_cases',params=params) or []}

@app.post('/cuba-desk/cases')
async def create_case(p:CaseIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']=='employee' and p.employee_id!=actor['id']: raise HTTPException(403,'Employees may only create their own trade cases')
 emp=await get_backend().select('cuba_trade_employees',params={'employee_id':f'eq.{p.employee_id}','status':'eq.ACTIVE','limit':'1'}) or []
 if not emp or not emp[0].get('may_prepare'): raise HTTPException(403,'Employee is not authorized to prepare Cuba transactions')
 if p.private_business_id:
  businesses=await get_backend().select('cuba_private_businesses',params={'private_business_id':f'eq.{p.private_business_id}','status':'eq.ACTIVE','limit':'1'}) or []
  if not businesses: raise HTTPException(404,'Cuban private business record not found')
 cid=f'cut_{secrets.token_urlsafe(10)}'; ts=now()
 row={'trade_case_id':cid,**p.model_dump(),'origin_country':'US','destination_country':'CU','status':'DRAFT','release_allowed':False,'owner_approved':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('cuba_trade_cases',row)
 gates=[{'gate_id':f'cug_{secrets.token_urlsafe(10)}','trade_case_id':cid,'gate_key':k,'gate_label':label,'status':'PENDING','created_at':ts,'updated_at':ts} for k,label in REQUIRED_GATES]
 await get_backend().insert('cuba_trade_case_gates',gates); await audit(cid,actor,'case_created','US -> CU trade case created in fail-closed DRAFT',{'private_business_id':p.private_business_id})
 return {'case':row,'gates':gates}

@app.patch('/cuba-desk/cases/{case_id}/gates/{gate_key}')
async def gate(case_id:str,gate_key:str,p:GateUpdate,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if gate_key not in {k for k,_ in REQUIRED_GATES}: raise HTTPException(404,'Unknown gate')
 if actor['role']!='owner': raise HTTPException(403,'Only owner/compliance authority may mark transaction gates')
 ts=now(); await get_backend().patch('cuba_trade_case_gates',{'status':p.status,'evidence_summary':p.evidence_summary,'evidence_reference':p.evidence_reference,'reviewed_by':actor['id'],'reviewed_at':ts,'updated_at':ts},params={'trade_case_id':f'eq.{case_id}','gate_key':f'eq.{gate_key}'})
 if p.status=='FAIL': await get_backend().patch('cuba_trade_cases',{'status':'HOLD','release_allowed':False,'release_reason':f'{gate_key} failed','updated_at':ts},params={'trade_case_id':f'eq.{case_id}'})
 await audit(case_id,actor,'gate_reviewed',f'{gate_key} -> {p.status}')
 return {'trade_case_id':case_id,'gate_key':gate_key,'status':p.status}

@app.post('/cuba-desk/cases/{case_id}/authorize')
async def authorize_case(case_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may authorize Cuba transaction release')
 rows=await get_backend().select('cuba_trade_cases',params={'trade_case_id':f'eq.{case_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'Trade case not found')
 case=rows[0]
 if not case.get('authorization_id'): raise HTTPException(409,'Government authorization record is required')
 auths=await get_backend().select('cuba_trade_authorizations',params={'authorization_id':f'eq.{case["authorization_id"]}','status':'eq.VERIFIED','limit':'1'}) or []
 if not auths: raise HTTPException(409,'Government authorization has not been verified')
 if case.get('private_business_id'):
  businesses=await get_backend().select('cuba_private_businesses',params={'private_business_id':f'eq.{case["private_business_id"]}','eligibility_status':'eq.ELIGIBLE','eligible_independent_private_sector':'eq.true','restricted_party_screening_status':'eq.CLEAR','status':'eq.ACTIVE','limit':'1'}) or []
  if not businesses: raise HTTPException(409,'Linked Cuban private business has not passed independent-private-sector eligibility and screening')
  business=businesses[0]
  if business.get('uses_cuban_owned_bank') and (auths[0].get('license_exception') or '').upper()=='SCP':
   raise HTTPException(409,'SCP transaction involving a Cuban-owned bank requires a different compliant payment path or specific authorization review')
 gates=await get_backend().select('cuba_trade_case_gates',params={'trade_case_id':f'eq.{case_id}','limit':'100'}) or []
 by={g.get('gate_key'):g.get('status') for g in gates}; missing=[k for k,_ in REQUIRED_GATES if by.get(k) not in {'PASS','NOT_APPLICABLE'}]
 if missing: raise HTTPException(409,'Transaction cannot be authorized; incomplete gates: '+', '.join(missing))
 ts=now(); await get_backend().patch('cuba_trade_cases',{'status':'AUTHORIZED','release_allowed':True,'release_reason':'Verified authorization plus all required gates passed','owner_approved':True,'owner_approved_at':ts,'updated_at':ts},params={'trade_case_id':f'eq.{case_id}'})
 await audit(case_id,actor,'case_authorized','Owner authorized lawful US -> CU transaction after verified authorization, private-business eligibility where applicable, and all gates passed')
 return {'trade_case_id':case_id,'status':'AUTHORIZED','release_allowed':True}

@app.post('/cuba-desk/cases/{case_id}/hold')
async def hold(case_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id); ts=now()
 await get_backend().patch('cuba_trade_cases',{'status':'HOLD','release_allowed':False,'release_reason':'Manual compliance hold','owner_approved':False,'updated_at':ts},params={'trade_case_id':f'eq.{case_id}'})
 await audit(case_id,actor,'case_held','Transaction placed on compliance hold')
 return {'trade_case_id':case_id,'status':'HOLD','release_allowed':False}
