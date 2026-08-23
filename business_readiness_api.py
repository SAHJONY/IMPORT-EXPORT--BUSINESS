from __future__ import annotations

import os, secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from auth import verify_owner_token
from insforge_backend import get_backend

app=FastAPI(title='SAHJONY Business Operational Readiness',version='1.1.0',docs_url=None,redoc_url=None)
Role=Literal['owner','employee']

def now(): return datetime.now(timezone.utc).isoformat()
def emp_token():
 t=os.getenv('EMPLOYEE_TOKEN','').strip()
 if not t: raise HTTPException(503,'Employee access not configured')
 return t

def actor(role,authorization,employee_id):
 if role not in {'owner','employee'}: raise HTTPException(400,'X-Role must be owner or employee')
 if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
 token=authorization.removeprefix('Bearer ').strip()
 if role=='owner':
  if not verify_owner_token(token): raise HTTPException(403,'Invalid owner credential')
  return {'role':'owner','id':'owner'}
 if token!=emp_token(): raise HTTPException(403,'Invalid employee credential')
 return {'role':'employee','id':(employee_id or 'staff')[:160]}

class PartnerIn(BaseModel):
 partner_type:Literal['CUSTOMS_BROKER','FREIGHT_FORWARDER','CARRIER','CARGO_INSURER','TRADE_CREDIT_INSURER','PAYMENT_PROVIDER','BANK','WAREHOUSE_3PL','LEGAL_COUNSEL','ACCOUNTING_TAX','INSPECTION_QC']
 legal_name:str=Field(min_length=2,max_length=240)
 country_code:str|None=None
 contact_name:str|None=None
 contact_email:str|None=None
 contact_phone:str|None=None
 license_or_registration:str|None=None
 coverage_scope:dict={}
 evidence_document_ids:list[str]=[]

class PartnerReviewIn(BaseModel):
 due_diligence_status:Literal['PENDING','PASS','FAIL']|None=None
 contract_status:Literal['NONE','PENDING','SIGNED','EXPIRED','TERMINATED']|None=None
 active:bool|None=None
 owner_approved:bool|None=None

class DossierIn(BaseModel):
 counterparty_type:Literal['CUSTOMER','PRIVATE_BUSINESS','SUPPLIER','PARTNER']
 counterparty_ref:str|None=None
 legal_name:str
 country_code:str|None=None
 beneficial_owners:list[dict]=[]
 identity_documents:list[str]=[]
 registration_documents:list[str]=[]
 tax_registration:str|None=None
 bank_evidence_document_ids:list[str]=[]

class ProductDossierIn(BaseModel):
 product_id:str|None=None
 sku:str|None=None
 product_name:str
 origin_country:str|None=None
 destination_country:str|None=None
 hts_code:str|None=None
 schedule_b:str|None=None
 eccn:str|None=None
 ear99:bool|None=None
 authorization_basis:str|None=None
 license_or_exception_reference:str|None=None
 prohibited_or_restricted:bool=False
 classification_evidence_document_ids:list[str]=[]
 labeling_requirements:dict={}
 permit_requirements:dict={}

class IncidentIn(BaseModel):
 managed_case_id:str|None=None
 trade_case_id:str|None=None
 incident_type:Literal['CUSTOMS_HOLD','DOCUMENT_ERROR','DAMAGE','SUPPLIER_DELAY','MISSED_SAILING','PAYMENT_FAILURE','SANCTIONS_HIT','DEMURRAGE_DETENTION','CLAIM','REFUND_DISPUTE','QUALITY_FAILURE','OTHER']
 severity:Literal['LOW','MEDIUM','HIGH','CRITICAL']='MEDIUM'
 summary:str=Field(min_length=2,max_length=4000)
 owner_required:bool=False
 evidence_document_ids:list[str]=[]

class CertificationIn(BaseModel):
 managed_case_id:str
 trade_case_id:str|None=None
 customer_ref:str|None=None
 supplier_ref:str|None=None

REQUIRED_PARTNER_TYPES={'CUSTOMS_BROKER','FREIGHT_FORWARDER','CARGO_INSURER','PAYMENT_PROVIDER','ACCOUNTING_TAX'}

def partner_is_production_usable(p:dict)->bool:
 return bool(p.get('active') and p.get('owner_approved') and p.get('due_diligence_status')=='PASS' and p.get('contract_status')=='SIGNED')

@app.get('/business-readiness/health')
async def health(): return {'status':'ok','service':'business-operational-readiness','version':'1.1.0','fail_closed':True,'definition_of_done':'first-controlled-live-trade'}

@app.get('/business-readiness/summary')
async def summary(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor(x_role,authorization,x_employee_id)
 b=get_backend()
 partners=await b.select('operating_partners',params={'limit':'500'}) or []
 dd=await b.select('counterparty_due_diligence',params={'limit':'500'}) or []
 products=await b.select('trade_product_dossiers',params={'limit':'500'}) or []
 certs=await b.select('first_live_trade_certification',params={'order':'created_at.desc','limit':'20'}) or []
 active_types={p.get('partner_type') for p in partners if partner_is_production_usable(p)}
 return {'required_partner_types':sorted(REQUIRED_PARTNER_TYPES),'missing_partner_types':sorted(REQUIRED_PARTNER_TYPES-active_types),'active_partner_types':sorted(active_types),'partner_count':len(partners),'production_usable_partner_count':sum(1 for p in partners if partner_is_production_usable(p)),'kyb_pass_count':sum(1 for r in dd if r.get('kyb_status')=='PASS' and r.get('sanctions_screening_status')=='CLEAR'),'product_dossiers_passed':sum(1 for r in products if r.get('status')=='PASS' and r.get('owner_approved')),'first_live_trade_passed':any(r.get('e2e_status')=='PASSED' and r.get('owner_certified') for r in certs)}

@app.get('/business-readiness/partners')
async def list_partners(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor(x_role,authorization,x_employee_id)
 partners=await get_backend().select('operating_partners',params={'order':'updated_at.desc','limit':'500'}) or []
 active_types={p.get('partner_type') for p in partners if partner_is_production_usable(p)}
 return {
  'partners':partners,
  'required_partner_types':sorted(REQUIRED_PARTNER_TYPES),
  'missing_partner_types':sorted(REQUIRED_PARTNER_TYPES-active_types),
  'production_usable_count':sum(1 for p in partners if partner_is_production_usable(p)),
 }

@app.post('/business-readiness/partners')
async def add_partner(p:PartnerIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 a=actor(x_role,authorization,x_employee_id); pid=f'op_{secrets.token_urlsafe(10)}'; ts=now()
 row={'partner_id':pid,**p.model_dump(),'due_diligence_status':'PENDING','contract_status':'NONE','active':False,'owner_approved':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('operating_partners',row); return {'partner':row,'created_by':a}

@app.patch('/business-readiness/partners/{partner_id}')
async def review_partner(partner_id:str,p:PartnerReviewIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 a=actor(x_role,authorization,x_employee_id)
 rows=await get_backend().select('operating_partners',params={'partner_id':f'eq.{partner_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'Operating partner not found')
 current=rows[0]
 values={k:v for k,v in p.model_dump().items() if v is not None}
 if ('owner_approved' in values or 'active' in values) and a['role']!='owner':
  raise HTTPException(403,'Only owner may approve or activate an operating partner')
 candidate={**current,**values}
 if values.get('owner_approved') is True and (candidate.get('due_diligence_status')!='PASS' or candidate.get('contract_status')!='SIGNED'):
  raise HTTPException(409,'Owner approval requires due diligence PASS and contract SIGNED')
 if values.get('active') is True and not (candidate.get('owner_approved') and candidate.get('due_diligence_status')=='PASS' and candidate.get('contract_status')=='SIGNED'):
  raise HTTPException(409,'Activation requires owner approval, due diligence PASS, and contract SIGNED')
 values['updated_at']=now()
 await get_backend().patch('operating_partners',values,params={'partner_id':f'eq.{partner_id}'})
 updated={**current,**values}
 return {'partner':updated,'production_usable':partner_is_production_usable(updated),'reviewed_by':a}

@app.post('/business-readiness/dossiers')
async def add_dossier(p:DossierIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor(x_role,authorization,x_employee_id); did=f'dd_{secrets.token_urlsafe(10)}'; ts=now()
 row={'dossier_id':did,**p.model_dump(),'sanctions_screening_status':'PENDING','kyb_status':'PENDING','risk_rating':'UNRATED','active':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('counterparty_due_diligence',row); return {'dossier':row}

@app.post('/business-readiness/products')
async def add_product_dossier(p:ProductDossierIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor(x_role,authorization,x_employee_id); did=f'prdossier_{secrets.token_urlsafe(10)}'; ts=now()
 row={'dossier_id':did,**p.model_dump(),'status':'PENDING','owner_approved':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('trade_product_dossiers',row); return {'product_dossier':row}

@app.post('/business-readiness/incidents')
async def add_incident(p:IncidentIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor(x_role,authorization,x_employee_id); iid=f'inc_{secrets.token_urlsafe(10)}'; ts=now()
 row={'incident_id':iid,**p.model_dump(),'status':'OPEN','created_at':ts,'updated_at':ts}
 await get_backend().insert('business_incident_cases',row); return {'incident':row}

@app.post('/business-readiness/first-live-trade')
async def start_cert(p:CertificationIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 a=actor(x_role,authorization,x_employee_id)
 if a['role']!='owner': raise HTTPException(403,'Only owner may start first-live-trade certification')
 cid=f'flt_{secrets.token_urlsafe(10)}'; ts=now()
 row={'certification_id':cid,**p.model_dump(),'started_at':ts,'customer_paid':False,'supplier_paid':False,'freight_duty_reconciled':False,'sahjony_fee_collected':False,'audit_closed':False,'unresolved_incidents':0,'e2e_status':'IN_PROGRESS','owner_certified':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('first_live_trade_certification',row); return {'certification':row}

@app.post('/business-readiness/first-live-trade/{certification_id}/certify')
async def certify(certification_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 a=actor(x_role,authorization,x_employee_id)
 if a['role']!='owner': raise HTTPException(403,'Only owner may certify full business readiness')
 rows=await get_backend().select('first_live_trade_certification',params={'certification_id':f'eq.{certification_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'Certification not found')
 r=rows[0]
 required=['customer_paid','supplier_paid','freight_duty_reconciled','sahjony_fee_collected','audit_closed']
 missing=[k for k in required if not r.get(k)]
 if (r.get('unresolved_incidents') or 0)>0: missing.append('unresolved_incidents')
 if not r.get('delivered_at'): missing.append('delivered_at')
 if not r.get('reconciled_at'): missing.append('reconciled_at')
 if missing: raise HTTPException(409,'Cannot certify; incomplete: '+', '.join(missing))
 ts=now(); await get_backend().patch('first_live_trade_certification',{'e2e_status':'PASSED','owner_certified':True,'owner_certified_at':ts,'updated_at':ts},params={'certification_id':f'eq.{certification_id}'})
 return {'certification_id':certification_id,'e2e_status':'PASSED','owner_certified':True}
