from __future__ import annotations

import os, secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from auth import verify_owner_token
from insforge_backend import get_backend

app=FastAPI(title='SAHJONY Intermediary Mode',version='1.0.0',docs_url=None,redoc_url=None)
Role=Literal['owner','employee']
INTERMEDIARY_ROLES={'MANAGED_TRADE_ORCHESTRATOR','BROKER_INTERMEDIARY','SOURCING_AGENT','BUYING_AGENT','SELLING_AGENT'}
ALL_ROLES=INTERMEDIARY_ROLES|{'DISTRIBUTOR','PRINCIPAL_RESELLER','PRINCIPAL'}
REQUIRED_ASSIGNMENTS={'SELLER_OF_RECORD','BUYER_OF_RECORD','EXPORTER_OF_RECORD','IMPORTER_OF_RECORD','SAHJONY_COMMERCIAL_ROLE'}

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

class EngagementIn(BaseModel):
 request_id:str|None=None
 managed_case_id:str|None=None
 principal_side:Literal['BUYER','SUPPLIER','BOTH_DISCLOSED','SAHJONY_PRINCIPAL']
 client_party_ref:str|None=None
 client_party_name:str=Field(min_length=2,max_length=240)
 sahjony_role:str='BROKER_INTERMEDIARY'
 agreement_document_id:str|None=None
 scope_summary:str=Field(min_length=2,max_length=4000)
 compensation_disclosed:bool=False
 dual_agency_disclosed:bool=False
 authority_to_bind_client:bool=False
 authority_to_receive_funds:bool=False
 authority_to_take_title:bool=False
 effective_at:str|None=None
 expires_at:str|None=None

class EconomicsIn(BaseModel):
 managed_case_id:str
 payer_side:Literal['BUYER','SUPPLIER','BOTH','SAHJONY_MARGIN']
 compensation_type:Literal['FIXED_FEE','PERCENT_COMMISSION','SOURCING_FEE','MANAGEMENT_FEE','SUCCESS_FEE','BUY_SELL_MARGIN']
 currency:str='USD'
 base_amount:float|None=None
 rate_pct:float|None=None
 fixed_amount:float|None=None
 supplier_price:float|None=None
 customer_price:float|None=None
 third_party_costs:float=0
 disclosed_to_buyer:bool=False
 disclosed_to_supplier:bool=False

class AssignmentIn(BaseModel):
 managed_case_id:str
 role_key:Literal['SELLER_OF_RECORD','BUYER_OF_RECORD','EXPORTER_OF_RECORD','IMPORTER_OF_RECORD','CUSTOMS_BROKER','FREIGHT_FORWARDER','CARRIER','SETTLEMENT_PROVIDER','INSURER','SAHJONY_COMMERCIAL_ROLE']
 party_name:str=Field(min_length=2,max_length=240)
 party_ref:str|None=None
 evidence_document_id:str|None=None

class CaseModeIn(BaseModel):
 sahjony_role:str
 engagement_agreement_id:str
 economics_id:str
 takes_title_to_goods:bool=False
 controls_client_funds:bool=False

async def audit(actor,event,summary,case_id=None,payload=None):
 await get_backend().insert('managed_trade_audit',{'event_id':f'mta_{secrets.token_urlsafe(10)}','managed_case_id':case_id,'request_id':None,'actor_role':actor['role'],'actor_id':actor['id'],'event_type':event,'summary':summary,'payload':payload or {},'created_at':now()})

@app.get('/intermediary/health')
async def health():
 return {'status':'ok','service':'sahjony-intermediary-mode','default_role':'BROKER_INTERMEDIARY','intermediary_roles':sorted(INTERMEDIARY_ROLES),'title_default':False,'client_funds_default':False,'fail_closed':True}

@app.get('/intermediary/engagements')
async def engagements(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 identity(x_role,authorization,x_employee_id)
 return {'engagements':await get_backend().select('managed_trade_engagements',params={'order':'updated_at.desc','limit':'250'}) or []}

@app.post('/intermediary/engagements')
async def create_engagement(p:EngagementIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if p.sahjony_role not in ALL_ROLES: raise HTTPException(400,'Unsupported SAHJONY commercial role')
 if p.principal_side=='BOTH_DISCLOSED' and not p.dual_agency_disclosed: raise HTTPException(409,'Both-sides representation requires explicit dual-agency disclosure')
 if p.sahjony_role in INTERMEDIARY_ROLES and p.authority_to_take_title: raise HTTPException(409,'Intermediary/agent engagement cannot silently take title; use a principal/reseller role')
 eid=f'mte_{secrets.token_urlsafe(10)}'; ts=now()
 row={'engagement_id':eid,**p.model_dump(),'status':'DRAFT','owner_approved':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('managed_trade_engagements',row); await audit(actor,'engagement_created',f'{p.sahjony_role} engagement created',p.managed_case_id,{'engagement_id':eid})
 return {'engagement':row}

@app.post('/intermediary/engagements/{engagement_id}/approve')
async def approve_engagement(engagement_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may approve intermediary engagements')
 rows=await get_backend().select('managed_trade_engagements',params={'engagement_id':f'eq.{engagement_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'Engagement not found')
 e=rows[0]
 if not e.get('agreement_document_id'): raise HTTPException(409,'Signed/approved engagement agreement document is required')
 if not e.get('compensation_disclosed'): raise HTTPException(409,'Compensation disclosure is required before activation')
 ts=now(); await get_backend().patch('managed_trade_engagements',{'status':'ACTIVE','owner_approved':True,'updated_at':ts},params={'engagement_id':f'eq.{engagement_id}'})
 await audit(actor,'engagement_approved','Owner activated intermediary engagement',e.get('managed_case_id'),{'engagement_id':engagement_id})
 return {'engagement_id':engagement_id,'status':'ACTIVE','owner_approved':True}

@app.post('/intermediary/economics')
async def create_economics(p:EconomicsIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if p.compensation_type=='PERCENT_COMMISSION' and (p.base_amount is None or p.rate_pct is None): raise HTTPException(400,'Percent commission requires base_amount and rate_pct')
 if p.compensation_type in {'FIXED_FEE','SOURCING_FEE','MANAGEMENT_FEE','SUCCESS_FEE'} and p.fixed_amount is None: raise HTTPException(400,'Fee compensation requires fixed_amount')
 if p.compensation_type=='BUY_SELL_MARGIN' and (p.supplier_price is None or p.customer_price is None): raise HTTPException(400,'Buy/sell margin requires supplier and customer prices')
 est=None; gross=None; gross_pct=None
 if p.compensation_type=='PERCENT_COMMISSION': est=(p.base_amount or 0)*(p.rate_pct or 0)/100
 elif p.compensation_type in {'FIXED_FEE','SOURCING_FEE','MANAGEMENT_FEE','SUCCESS_FEE'}: est=p.fixed_amount
 else:
  gross=(p.customer_price or 0)-(p.supplier_price or 0)-p.third_party_costs; est=gross; gross_pct=(gross/(p.customer_price or 1))*100
 eid=f'mec_{secrets.token_urlsafe(10)}'; ts=now()
 row={'economics_id':eid,**p.model_dump(),'estimated_compensation':est,'gross_margin':gross,'gross_margin_pct':gross_pct,'owner_approved':False,'status':'DRAFT','created_at':ts,'updated_at':ts}
 await get_backend().insert('managed_trade_economics',row); await audit(actor,'economics_created','Intermediary compensation model created',p.managed_case_id,{'economics_id':eid,'estimated_compensation':est})
 return {'economics':row}

@app.post('/intermediary/economics/{economics_id}/approve')
async def approve_economics(economics_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may approve intermediary economics')
 rows=await get_backend().select('managed_trade_economics',params={'economics_id':f'eq.{economics_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'Economics record not found')
 e=rows[0]
 if e.get('payer_side') in {'BUYER','BOTH'} and not e.get('disclosed_to_buyer'): raise HTTPException(409,'Buyer compensation disclosure is required')
 if e.get('payer_side') in {'SUPPLIER','BOTH'} and not e.get('disclosed_to_supplier'): raise HTTPException(409,'Supplier compensation disclosure is required')
 ts=now(); await get_backend().patch('managed_trade_economics',{'status':'APPROVED','owner_approved':True,'updated_at':ts},params={'economics_id':f'eq.{economics_id}'})
 await audit(actor,'economics_approved','Owner approved intermediary compensation',e.get('managed_case_id'),{'economics_id':economics_id})
 return {'economics_id':economics_id,'status':'APPROVED','owner_approved':True}

@app.post('/intermediary/role-assignments')
async def assign_role(p:AssignmentIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 aid=f'mra_{secrets.token_urlsafe(10)}'; ts=now()
 await get_backend().delete('managed_trade_role_assignments',params={'managed_case_id':f'eq.{p.managed_case_id}','role_key':f'eq.{p.role_key}'})
 row={'assignment_id':aid,**p.model_dump(),'verified':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('managed_trade_role_assignments',row); await audit(actor,'role_assigned',f'{p.role_key} assigned to {p.party_name}',p.managed_case_id)
 return {'assignment':row}

@app.post('/intermediary/role-assignments/{assignment_id}/verify')
async def verify_role(assignment_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may verify legal-role assignments')
 ts=now(); await get_backend().patch('managed_trade_role_assignments',{'verified':True,'verified_by':actor['id'],'verified_at':ts,'updated_at':ts},params={'assignment_id':f'eq.{assignment_id}'})
 return {'assignment_id':assignment_id,'verified':True}

@app.post('/intermediary/cases/{case_id}/configure')
async def configure_case(case_id:str,p:CaseModeIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may configure SAHJONY transaction role')
 if p.sahjony_role not in ALL_ROLES: raise HTTPException(400,'Unsupported SAHJONY role')
 eng=await get_backend().select('managed_trade_engagements',params={'engagement_id':f'eq.{p.engagement_agreement_id}','status':'eq.ACTIVE','owner_approved':'eq.true','limit':'1'}) or []
 eco=await get_backend().select('managed_trade_economics',params={'economics_id':f'eq.{p.economics_id}','status':'eq.APPROVED','owner_approved':'eq.true','limit':'1'}) or []
 if not eng: raise HTTPException(409,'Active approved engagement required')
 if not eco: raise HTTPException(409,'Approved compensation economics required')
 if p.sahjony_role in INTERMEDIARY_ROLES and p.takes_title_to_goods: raise HTTPException(409,'Broker/agent/orchestrator mode cannot take title; use PRINCIPAL_RESELLER or PRINCIPAL')
 if p.sahjony_role in INTERMEDIARY_ROLES and p.controls_client_funds and not eng[0].get('authority_to_receive_funds'): raise HTTPException(409,'Engagement does not authorize SAHJONY to receive/control client funds')
 ts=now(); values={'sahjony_role':p.sahjony_role,'intermediary_mode':p.sahjony_role in INTERMEDIARY_ROLES,'takes_title_to_goods':p.takes_title_to_goods,'controls_client_funds':p.controls_client_funds,'engagement_agreement_id':p.engagement_agreement_id,'economics_id':p.economics_id,'release_allowed':False,'owner_approved':False,'updated_at':ts}
 await get_backend().patch('managed_trade_cases',values,params={'managed_case_id':f'eq.{case_id}'})
 await audit(actor,'intermediary_mode_configured',f'SAHJONY configured as {p.sahjony_role}',case_id,values)
 return {'managed_case_id':case_id,**values}

@app.get('/intermediary/cases/{case_id}/readiness')
async def readiness(case_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 identity(x_role,authorization,x_employee_id)
 cases=await get_backend().select('managed_trade_cases',params={'managed_case_id':f'eq.{case_id}','limit':'1'}) or []
 if not cases: raise HTTPException(404,'Managed case not found')
 c=cases[0]
 assignments=await get_backend().select('managed_trade_role_assignments',params={'managed_case_id':f'eq.{case_id}','limit':'50'}) or []
 verified={a.get('role_key') for a in assignments if a.get('verified')}
 missing_roles=sorted(REQUIRED_ASSIGNMENTS-verified)
 engagement_ok=False; economics_ok=False
 if c.get('engagement_agreement_id'):
  engagement_ok=bool(await get_backend().select('managed_trade_engagements',params={'engagement_id':f'eq.{c["engagement_agreement_id"]}','status':'eq.ACTIVE','owner_approved':'eq.true','limit':'1'}) or [])
 if c.get('economics_id'):
  economics_ok=bool(await get_backend().select('managed_trade_economics',params={'economics_id':f'eq.{c["economics_id"]}','status':'eq.APPROVED','owner_approved':'eq.true','limit':'1'}) or [])
 ready=engagement_ok and economics_ok and not missing_roles
 return {'managed_case_id':case_id,'intermediary_ready':ready,'engagement_ok':engagement_ok,'economics_ok':economics_ok,'missing_verified_roles':missing_roles,'sahjony_role':c.get('sahjony_role'),'takes_title_to_goods':c.get('takes_title_to_goods',False),'controls_client_funds':c.get('controls_client_funds',False)}
