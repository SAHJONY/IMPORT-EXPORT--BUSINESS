from __future__ import annotations

import os, secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from auth import verify_owner_token
from insforge_backend import get_backend

app=FastAPI(title='SAHJONY Managed Trade Gateway',version='1.0.0',docs_url=None,redoc_url=None)
Role=Literal['owner','employee']
MILESTONES=[
 ('request_qualified','Business request qualified'),
 ('private_business_eligible','Cuban private business eligibility verified'),
 ('supplier_sourced','Supplier sourced'),
 ('supplier_due_diligence','Supplier due diligence passed'),
 ('product_classified','Product classification verified'),
 ('authorization_matched','Government authorization scope matched'),
 ('commercial_terms','Commercial terms approved'),
 ('payment_path','Lawful payment path approved'),
 ('documents_ready','Documents complete'),
 ('logistics_ready','Broker/forwarder/carrier path ready'),
 ('compliance_release','Compliance release approved'),
 ('owner_release','Owner final release'),
 ('delivery','Delivery confirmed'),
 ('reconciliation','Final financial reconciliation complete'),
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

class RequestIn(BaseModel):
 requester_type:Literal['PRIVATE_BUSINESS','BUYER','EMPLOYEE','OTHER']='PRIVATE_BUSINESS'
 requester_ref:str|None=None
 private_business_id:str|None=None
 employee_id:str|None=None
 product_need:str=Field(min_length=2,max_length=1000)
 specifications:str|None=None
 quantity:float|None=None
 target_budget:float|None=None
 currency:str='USD'
 destination_country:str='CU'
 target_delivery_date:str|None=None

class SupplierCandidateIn(BaseModel):
 supplier_id:str|None=None
 supplier_name:str=Field(min_length=2,max_length=240)
 supplier_country:str|None=None
 product_match:str|None=None
 unit_cost:float|None=None
 moq:float|None=None
 lead_time_days:int|None=None
 payment_terms:str|None=None
 incoterm:str|None=None
 score:float|None=None
 evidence:dict={}

class CaseIn(BaseModel):
 request_id:str
 private_business_id:str|None=None
 supplier_candidate_id:str
 supplier_id:str|None=None
 sahjony_role:Literal['MANAGED_TRADE_ORCHESTRATOR','AGENT','DISTRIBUTOR','EXPORTER_OF_RECORD','IMPORTER_OF_RECORD','PRINCIPAL']='MANAGED_TRADE_ORCHESTRATOR'
 exporter_of_record:str|None=None
 importer_of_record:str|None=None
 customs_broker:str|None=None
 freight_forwarder:str|None=None
 settlement_provider:str|None=None

class MilestoneIn(BaseModel):
 status:Literal['PASS','FAIL','NOT_APPLICABLE']
 evidence_reference:str|None=None
 notes:str|None=None

async def audit(actor,event,summary,request_id=None,case_id=None,payload=None):
 await get_backend().insert('managed_trade_audit',{'event_id':f'mta_{secrets.token_urlsafe(10)}','managed_case_id':case_id,'request_id':request_id,'actor_role':actor['role'],'actor_id':actor['id'],'event_type':event,'summary':summary,'payload':payload or {},'created_at':now()})

@app.get('/managed-trade/health')
async def health(): return {'status':'ok','service':'managed-trade-gateway','operator':'SAHJONY','default_role':'MANAGED_TRADE_ORCHESTRATOR','fail_closed':True,'milestones':len(MILESTONES)}

@app.get('/managed-trade/requests')
async def list_requests(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id); params={'order':'updated_at.desc','limit':'250'}
 if actor['role']=='employee': params['assigned_employee_id']=f'eq.{actor["id"]}'
 return {'requests':await get_backend().select('managed_trade_requests',params=params) or []}

@app.post('/managed-trade/requests')
async def create_request(p:RequestIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id); rid=f'mtr_{secrets.token_urlsafe(10)}'; ts=now()
 assigned=actor['id'] if actor['role']=='employee' else p.employee_id
 row={'request_id':rid,**p.model_dump(),'status':'INTAKE','assigned_owner_id':'owner','assigned_employee_id':assigned,'created_at':ts,'updated_at':ts}
 await get_backend().insert('managed_trade_requests',row); await audit(actor,'request_created','Managed trade request entered SAHJONY gateway',rid)
 return {'request':row}

@app.post('/managed-trade/requests/{request_id}/suppliers')
async def add_supplier(request_id:str,p:SupplierCandidateIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id); cid=f'msc_{secrets.token_urlsafe(10)}'; ts=now()
 row={'candidate_id':cid,'request_id':request_id,**p.model_dump(),'compliance_status':'PENDING','quality_status':'PENDING','bank_status':'PENDING','selected':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('managed_supplier_candidates',row); await get_backend().patch('managed_trade_requests',{'status':'SOURCING','updated_at':ts},params={'request_id':f'eq.{request_id}'})
 await audit(actor,'supplier_candidate_added',f'Supplier candidate {p.supplier_name} added',request_id,payload={'candidate_id':cid})
 return {'supplier_candidate':row}

@app.post('/managed-trade/requests/{request_id}/suppliers/{candidate_id}/select')
async def select_supplier(request_id:str,candidate_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may select the supplier for commitment')
 rows=await get_backend().select('managed_supplier_candidates',params={'candidate_id':f'eq.{candidate_id}','request_id':f'eq.{request_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'Supplier candidate not found')
 c=rows[0]
 if c.get('compliance_status')!='PASS' or c.get('quality_status')!='PASS' or c.get('bank_status')!='PASS': raise HTTPException(409,'Supplier cannot be selected until compliance, quality and bank due diligence pass')
 await get_backend().patch('managed_supplier_candidates',{'selected':False},params={'request_id':f'eq.{request_id}'})
 await get_backend().patch('managed_supplier_candidates',{'selected':True,'updated_at':now()},params={'candidate_id':f'eq.{candidate_id}'})
 await get_backend().patch('managed_trade_requests',{'status':'SUPPLIER_SHORTLIST','updated_at':now()},params={'request_id':f'eq.{request_id}'})
 await audit(actor,'supplier_selected','Owner selected supplier after due diligence',request_id,payload={'candidate_id':candidate_id})
 return {'request_id':request_id,'selected_supplier_candidate_id':candidate_id}

@app.post('/managed-trade/cases')
async def create_case(p:CaseIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may open a managed execution case')
 if p.sahjony_role in {'EXPORTER_OF_RECORD','IMPORTER_OF_RECORD','PRINCIPAL'} and not (p.exporter_of_record or p.importer_of_record): raise HTTPException(409,'Principal/EOR/IOR role requires explicit legal-party assignment')
 cand=await get_backend().select('managed_supplier_candidates',params={'candidate_id':f'eq.{p.supplier_candidate_id}','selected':'eq.true','limit':'1'}) or []
 if not cand: raise HTTPException(409,'Selected supplier candidate required')
 mid=f'mtc_{secrets.token_urlsafe(10)}'; ts=now(); row={'managed_case_id':mid,**p.model_dump(),'orchestrator_name':'SAHJONY','status':'OPEN','release_allowed':False,'owner_approved':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('managed_trade_cases',row)
 ms=[{'milestone_id':f'mtm_{secrets.token_urlsafe(10)}','managed_case_id':mid,'milestone_key':k,'label':label,'status':'PENDING','created_at':ts,'updated_at':ts} for k,label in MILESTONES]
 await get_backend().insert('managed_trade_milestones',ms); await audit(actor,'managed_case_opened','SAHJONY opened managed execution case',p.request_id,mid,{'role':p.sahjony_role})
 return {'case':row,'milestones':ms}

@app.get('/managed-trade/cases')
async def list_cases(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 identity(x_role,authorization,x_employee_id)
 return {'cases':await get_backend().select('managed_trade_cases',params={'order':'updated_at.desc','limit':'250'}) or []}

@app.patch('/managed-trade/cases/{case_id}/milestones/{key}')
async def milestone(case_id:str,key:str,p:MilestoneIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if key not in {k for k,_ in MILESTONES}: raise HTTPException(404,'Unknown milestone')
 if key in {'compliance_release','owner_release'} and actor['role']!='owner': raise HTTPException(403,'Only owner may approve compliance/final release')
 ts=now(); await get_backend().patch('managed_trade_milestones',{'status':p.status,'evidence_reference':p.evidence_reference,'notes':p.notes,'reviewed_by':actor['id'],'reviewed_at':ts,'updated_at':ts},params={'managed_case_id':f'eq.{case_id}','milestone_key':f'eq.{key}'})
 if p.status=='FAIL': await get_backend().patch('managed_trade_cases',{'status':'HOLD','release_allowed':False,'owner_approved':False,'updated_at':ts},params={'managed_case_id':f'eq.{case_id}'})
 await audit(actor,'milestone_reviewed',f'{key} -> {p.status}',case_id=case_id)
 return {'managed_case_id':case_id,'milestone_key':key,'status':p.status}

@app.post('/managed-trade/cases/{case_id}/release')
async def release(case_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may release a managed trade case')
 rows=await get_backend().select('managed_trade_cases',params={'managed_case_id':f'eq.{case_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'Managed trade case not found')
 ms=await get_backend().select('managed_trade_milestones',params={'managed_case_id':f'eq.{case_id}','limit':'100'}) or []
 by={m.get('milestone_key'):m.get('status') for m in ms}; required=[k for k,_ in MILESTONES if k not in {'delivery','reconciliation'}]; missing=[k for k in required if by.get(k) not in {'PASS','NOT_APPLICABLE'}]
 if missing: raise HTTPException(409,'Managed trade release blocked; incomplete milestones: '+', '.join(missing))
 ts=now(); await get_backend().patch('managed_trade_cases',{'status':'READY_FOR_EXECUTION','release_allowed':True,'owner_approved':True,'updated_at':ts},params={'managed_case_id':f'eq.{case_id}'})
 await audit(actor,'managed_case_released','Owner released managed trade case for execution',case_id=case_id)
 return {'managed_case_id':case_id,'status':'READY_FOR_EXECUTION','release_allowed':True}
