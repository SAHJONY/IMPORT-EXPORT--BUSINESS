from __future__ import annotations

import os, secrets
from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from country_activation_api import validate_ready_live_corridor
from insforge_backend import get_backend

app=FastAPI(title='SAHJONY Global Supplier Sourcing',version='1.2.0',docs_url=None,redoc_url=None)
Role=Literal['owner','employee']
CONTROL_FIELDS=[
 'supplier_screening_status','origin_export_control_status','destination_import_control_status',
 'product_restriction_status','banking_status','logistics_status','tax_duty_status','us_nexus_status'
]


def now(): return datetime.now(timezone.utc).isoformat()


def _parse_time(value:Any)->datetime|None:
 if not value: return None
 if isinstance(value,datetime): moment=value
 else:
  try: moment=datetime.fromisoformat(str(value).replace('Z','+00:00'))
  except ValueError: return None
 if moment.tzinfo is None: moment=moment.replace(tzinfo=timezone.utc)
 return moment


def _expired(value:Any)->bool:
 moment=_parse_time(value)
 return bool(value) and (moment is None or moment <= datetime.now(timezone.utc))


def _country_code(value:str)->str:
 code=(value or '').strip().upper()
 if len(code) not in {2,3} or not code.isalpha():
  raise HTTPException(422,'Country must use a 2- or 3-letter ISO-style country code')
 return code


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


class SourcingRequestIn(BaseModel):
 managed_request_id:str|None=None
 private_business_id:str|None=None
 product_need:str=Field(min_length=2,max_length=1000)
 specifications:str|None=None
 quantity:float|None=None
 destination_country:str=Field(default='CU',min_length=2,max_length=3)
 allowed_origin_countries:list[str]=Field(default_factory=list,max_length=250)
 excluded_origin_countries:list[str]=Field(default_factory=list,max_length=250)
 worldwide_search:bool=True
 target_budget:float|None=None
 currency:str='USD'
 target_delivery_date:str|None=None


class CandidateIn(BaseModel):
 supplier_name:str=Field(min_length=2,max_length=240)
 supplier_country:str=Field(min_length=2,max_length=3)
 supplier_id:str|None=None
 website:str|None=None
 product_match:str|None=None
 unit_cost:float|None=None
 currency:str|None='USD'
 moq:float|None=None
 lead_time_days:int|None=None
 incoterm:str|None=None
 payment_terms:str|None=None
 source_reference:str|None=None
 source_evidence:dict=Field(default_factory=dict)
 landed_cost_estimate:float|None=None
 score:float|None=None


class ControlUpdate(BaseModel):
 status:Literal['PASS','FAIL','REVIEW','NOT_APPLICABLE']
 authority:str|None=None
 reference:str|None=None
 summary:str=Field(min_length=2,max_length=4000)
 effective_at:str|None=None
 expires_at:str|None=None


class SupplierQuoteIn(BaseModel):
 unit_cost:float=Field(gt=0)
 currency:str=Field(default='USD',min_length=3,max_length=3)
 moq:float=Field(gt=0)
 lead_time_days:int=Field(ge=0,le=3650)
 incoterm:str=Field(min_length=2,max_length=32)
 payment_terms:str=Field(min_length=2,max_length=1000)
 landed_cost_estimate:float|None=Field(default=None,gt=0)
 quote_reference:str=Field(min_length=2,max_length=500)
 quote_date:date
 valid_until:date
 available_capacity:str|None=Field(default=None,max_length=1000)
 evidence_urls:list[str]=Field(default_factory=list,max_length=20)
 notes:str|None=Field(default=None,max_length=4000)
 verified:bool=False


async def audit(candidate_id,control,p,actor):
 await get_backend().insert('global_sourcing_control_evidence',{
  'evidence_id':f'gse_{secrets.token_urlsafe(10)}','global_candidate_id':candidate_id,'control_key':control,
  'authority':p.authority,'reference':p.reference,'summary':p.summary,'effective_at':p.effective_at,'expires_at':p.expires_at,
  'verified':actor['role']=='owner','verified_by':actor['id'] if actor['role']=='owner' else None,'verified_at':now() if actor['role']=='owner' else None,'created_at':now()})


def derive(row):
 vals=[row.get(k) for k in CONTROL_FIELDS]
 if any(v=='FAIL' for v in vals): return 'BLOCKED'
 if any(v in {'PENDING','REVIEW',None} for v in vals): return 'LIMITED'
 return 'READY'


def quote_data(row):
 evidence=row.get('source_evidence') or {}
 if not isinstance(evidence,dict): evidence={}
 quote=evidence.get('supplier_quote') or {}
 return quote if isinstance(quote,dict) else {}


def quote_status(row):
 quote=quote_data(row)
 required=['unit_cost','currency','moq','lead_time_days','incoterm','payment_terms','quote_reference','quote_date','valid_until']
 missing=[key for key in required if quote.get(key) in (None,'')]
 expired=True
 if quote.get('valid_until'):
  try: expired=date.fromisoformat(str(quote['valid_until'])[:10]) < date.today()
  except ValueError: expired=True
 verified=quote.get('verified') is True
 basis='LANDED' if quote.get('landed_cost_estimate') is not None else f"UNIT_{str(quote.get('incoterm') or 'UNKNOWN').upper()}"
 amount=quote.get('landed_cost_estimate') if basis=='LANDED' else quote.get('unit_cost')
 eligible=not missing and not expired and verified and row.get('corridor_status')=='READY'
 blockers=[]
 if missing: blockers.append('MISSING_QUOTE_FIELDS: '+', '.join(missing))
 if expired: blockers.append('QUOTE_EXPIRED_OR_INVALID')
 if not verified: blockers.append('QUOTE_NOT_OWNER_VERIFIED')
 if row.get('corridor_status')!='READY': blockers.append('CANDIDATE_CONTROLS_NOT_READY')
 return {'complete':not missing,'completeness_score':round(100*(len(required)-len(missing))/len(required)),
  'missing_fields':missing,'expired':expired,'verified':verified,'selection_eligible':eligible,
  'comparison_basis':basis,'comparison_amount':amount,'currency':quote.get('currency'),'blockers':blockers}


async def control_evidence_status(candidate_id:str,row:dict)->dict:
 evidence=await get_backend().select('global_sourcing_control_evidence',params={'global_candidate_id':f'eq.{candidate_id}','order':'created_at.desc','limit':'250'}) or []
 latest={}
 for item in evidence:
  key=str(item.get('control_key') or '')
  if key in CONTROL_FIELDS and key not in latest: latest[key]=item
 failures=[]
 for key in CONTROL_FIELDS:
  status=row.get(key)
  if status not in {'PASS','NOT_APPLICABLE'}:
   failures.append(f'{key}:STATUS_{status or "MISSING"}')
   continue
  item=latest.get(key)
  if not item:
   failures.append(f'{key}:EVIDENCE_MISSING'); continue
  if item.get('verified') is not True:
   failures.append(f'{key}:EVIDENCE_NOT_OWNER_VERIFIED'); continue
  if not str(item.get('authority') or '').strip():
   failures.append(f'{key}:AUTHORITY_MISSING'); continue
  if not str(item.get('reference') or '').strip():
   failures.append(f'{key}:REFERENCE_MISSING'); continue
  if not str(item.get('summary') or '').strip():
   failures.append(f'{key}:SUMMARY_MISSING'); continue
  if _expired(item.get('expires_at')):
   failures.append(f'{key}:EVIDENCE_EXPIRED')
 return {'verified':not failures,'failures':failures,'verified_control_count':len(CONTROL_FIELDS)-len(failures),'required_control_count':len(CONTROL_FIELDS)}


async def actual_corridor_status(candidate:dict,request:dict)->dict:
 origin=_country_code(str(candidate.get('supplier_country') or ''))
 destination=_country_code(str(request.get('destination_country') or ''))
 rows=await get_backend().select('trade_corridor_activations',params={
  'origin_country_code':f'eq.{origin}','destination_country_code':f'eq.{destination}',
  'execution_mode':'eq.LIVE','status':'eq.READY','owner_approved':'eq.true','limit':'1'}) or []
 if not rows:
  return {'ready':False,'origin':origin,'destination':destination,'reason':'NO_OWNER_APPROVED_LIVE_READY_COUNTRY_CORRIDOR'}
 corridor=rows[0]
 validation=await validate_ready_live_corridor(corridor)
 return {'ready':bool(validation.get('ready')),'origin':origin,'destination':destination,'corridor':corridor,
  'validation':validation,'reason':None if validation.get('ready') else 'COUNTRY_CORRIDOR_GOVERNANCE_FAILED'}


async def candidate_selection_status(candidate:dict,request:dict)->dict:
 quote=quote_status(candidate)
 controls=await control_evidence_status(str(candidate.get('global_candidate_id')),candidate)
 corridor=await actual_corridor_status(candidate,request)
 blockers=[]
 if not quote['selection_eligible']: blockers.extend(quote['blockers'])
 if not controls['verified']: blockers.extend(controls['failures'])
 if not corridor['ready']: blockers.append(str(corridor.get('reason') or 'COUNTRY_CORRIDOR_NOT_READY'))
 return {'selection_eligible':not blockers,'blockers':blockers,'quote_status':quote,'control_evidence':controls,'country_corridor':corridor}


@app.get('/global-sourcing/health')
async def health(): return {'status':'ok','service':'global-supplier-sourcing','version':'1.2.0','worldwide_supplier_search':True,'fail_closed':True,
 'destination_specific_controls':True,'supplier_quote_capture':True,'like_for_like_quote_comparison':True,
 'owner_quote_verification_required_for_selection':True,'owner_control_evidence_required_for_selection':True,
 'country_corridor_governance_required_for_selection':True,'binding_acceptance':False}


@app.get('/global-sourcing/requests')
async def requests(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 identity(x_role,authorization,x_employee_id)
 return {'requests':await get_backend().select('global_sourcing_requests',params={'order':'updated_at.desc','limit':'250'}) or []}


@app.post('/global-sourcing/requests')
async def create_request(p:SourcingRequestIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id); sid=f'gsr_{secrets.token_urlsafe(10)}'; ts=now()
 destination=_country_code(p.destination_country)
 allowed=[_country_code(x) for x in p.allowed_origin_countries]
 excluded=[_country_code(x) for x in p.excluded_origin_countries]
 if set(allowed)&set(excluded): raise HTTPException(422,'A country cannot be both allowed and excluded')
 row={'sourcing_request_id':sid,**p.model_dump(),'destination_country':destination,'allowed_origin_countries':allowed,
  'excluded_origin_countries':excluded,'currency':p.currency.upper(),'status':'SEARCHING','created_by':actor['id'],'created_at':ts,'updated_at':ts}
 await get_backend().insert('global_sourcing_requests',row)
 return {'sourcing_request':row}


@app.get('/global-sourcing/requests/{request_id}/candidates')
async def list_candidates(request_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 identity(x_role,authorization,x_employee_id)
 rows=await get_backend().select('global_supplier_candidates',params={'sourcing_request_id':f'eq.{request_id}','order':'score.desc.nullslast,updated_at.desc','limit':'500'}) or []
 return {'candidates':rows}


@app.post('/global-sourcing/requests/{request_id}/candidates')
async def add_candidate(request_id:str,p:CandidateIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 identity(x_role,authorization,x_employee_id)
 req=await get_backend().select('global_sourcing_requests',params={'sourcing_request_id':f'eq.{request_id}','limit':'1'}) or []
 if not req: raise HTTPException(404,'Sourcing request not found')
 r=req[0]; country=_country_code(p.supplier_country)
 allowed=[_country_code(x) for x in (r.get('allowed_origin_countries') or [])]; excluded=[_country_code(x) for x in (r.get('excluded_origin_countries') or [])]
 if country in excluded: raise HTTPException(409,'Supplier origin country is excluded for this sourcing request')
 if allowed and country not in allowed: raise HTTPException(409,'Supplier origin country is outside the allowed origin list')
 cid=f'gsc_{secrets.token_urlsafe(10)}'; ts=now()
 row={'global_candidate_id':cid,'sourcing_request_id':request_id,**p.model_dump(),'supplier_country':country,
  'supplier_screening_status':'PENDING','origin_export_control_status':'PENDING','destination_import_control_status':'PENDING',
  'product_restriction_status':'PENDING','banking_status':'PENDING','logistics_status':'PENDING','tax_duty_status':'PENDING','us_nexus_status':'PENDING',
  'corridor_status':'BLOCKED','selected':False,'created_at':ts,'updated_at':ts}
 await get_backend().insert('global_supplier_candidates',row)
 return {'candidate':row}


@app.put('/global-sourcing/candidates/{candidate_id}/quote')
async def save_quote(candidate_id:str,p:SupplierQuoteIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if p.valid_until < p.quote_date: raise HTTPException(422,'Quote validity cannot end before the quote date')
 if p.verified and actor['role']!='owner': raise HTTPException(403,'Only owner may verify a supplier quote')
 rows=await get_backend().select('global_supplier_candidates',params={'global_candidate_id':f'eq.{candidate_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'Candidate not found')
 current=rows[0]; evidence=current.get('source_evidence') or {}
 if not isinstance(evidence,dict): evidence={}
 ts=now(); quote={**p.model_dump(mode='json'),'currency':p.currency.upper(),'incoterm':p.incoterm.upper(),
  'verified':p.verified and actor['role']=='owner','verified_by':actor['id'] if p.verified else None,
  'verified_at':ts if p.verified else None,'recorded_by':actor['id'],'recorded_at':ts}
 evidence={**evidence,'supplier_quote':quote}
 values={'unit_cost':p.unit_cost,'currency':p.currency.upper(),'moq':p.moq,'lead_time_days':p.lead_time_days,
  'incoterm':p.incoterm.upper(),'payment_terms':p.payment_terms,'source_reference':p.quote_reference,
  'source_evidence':evidence,'landed_cost_estimate':p.landed_cost_estimate,'updated_at':ts}
 await get_backend().patch('global_supplier_candidates',values,params={'global_candidate_id':f'eq.{candidate_id}'})
 await get_backend().insert('global_sourcing_control_evidence',{
  'evidence_id':f'gse_{secrets.token_urlsafe(10)}','global_candidate_id':candidate_id,'control_key':'supplier_quote',
  'authority':'SUPPLIER_QUOTE','reference':p.quote_reference,
  'summary':f'Supplier quote recorded: {p.currency.upper()} {p.unit_cost:g} {p.incoterm.upper()}; valid through {p.valid_until.isoformat()}.',
  'effective_at':p.quote_date.isoformat(),'expires_at':p.valid_until.isoformat(),
  'verified':quote['verified'],'verified_by':quote['verified_by'],'verified_at':quote['verified_at'],'created_at':ts})
 updated={**current,**values}
 return {'global_candidate_id':candidate_id,'quote':quote,'quote_status':quote_status(updated),'binding_acceptance':False}


@app.get('/global-sourcing/requests/{request_id}/comparison')
async def compare_quotes(request_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 identity(x_role,authorization,x_employee_id)
 reqs=await get_backend().select('global_sourcing_requests',params={'sourcing_request_id':f'eq.{request_id}','limit':'1'}) or []
 if not reqs: raise HTTPException(404,'Sourcing request not found')
 request=reqs[0]
 rows=await get_backend().select('global_supplier_candidates',params={'sourcing_request_id':f'eq.{request_id}','limit':'500'}) or []
 comparisons=[]; groups={}
 for row in rows:
  status=await candidate_selection_status(row,request); quote=quote_data(row); qstatus=status['quote_status']
  item={'global_candidate_id':row.get('global_candidate_id'),'supplier_name':row.get('supplier_name'),
   'supplier_country':row.get('supplier_country'),'candidate_control_status':row.get('corridor_status'),
   'selected':bool(row.get('selected')),'quote':quote,'quote_status':qstatus,'selection_status':status}
  comparisons.append(item)
  if status['selection_eligible'] and qstatus['comparison_amount'] is not None:
   key=f"{qstatus['currency']}|{qstatus['comparison_basis']}"; groups.setdefault(key,[]).append(item)
 best=[]
 for key,items in groups.items():
  winner=min(items,key=lambda x:float(x['quote_status']['comparison_amount']))
  currency,basis=key.split('|',1)
  best.append({'currency':currency,'comparison_basis':basis,'candidate_count':len(items),
   'best_candidate_id':winner['global_candidate_id'],'best_supplier_name':winner['supplier_name'],
   'best_amount':winner['quote_status']['comparison_amount']})
 comparisons.sort(key=lambda x:(not x['selection_status']['selection_eligible'],-x['quote_status']['completeness_score'],x['supplier_name'] or ''))
 return {'request':request,'comparisons':comparisons,'best_by_comparable_group':best,
  'eligible_quote_count':sum(1 for x in comparisons if x['selection_status']['selection_eligible']),
  'notice':'Selection eligibility requires like-for-like quote evidence, current owner-verified controls, and a separate owner-approved LIVE/READY country corridor. No FX conversion, availability claim, or binding acceptance is inferred.',
  'binding_acceptance':False,'sahjony_own_capital_required':False}


@app.patch('/global-sourcing/candidates/{candidate_id}/controls/{control}')
async def update_control(candidate_id:str,control:str,p:ControlUpdate,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner/compliance authority may verify global sourcing controls')
 if control not in CONTROL_FIELDS: raise HTTPException(404,'Unknown sourcing control')
 if p.status in {'PASS','NOT_APPLICABLE'}:
  if not (p.authority or '').strip() or not (p.reference or '').strip():
   raise HTTPException(422,'PASS/NOT_APPLICABLE controls require authority and reference evidence')
  if p.expires_at and _expired(p.expires_at):
   raise HTTPException(422,'Control evidence expiry must be a valid future timestamp')
 rows=await get_backend().select('global_supplier_candidates',params={'global_candidate_id':f'eq.{candidate_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'Candidate not found')
 row=rows[0]; row[control]=p.status; candidate_control_status=derive(row); ts=now()
 await get_backend().patch('global_supplier_candidates',{control:p.status,'corridor_status':candidate_control_status,'selected':False,'updated_at':ts},params={'global_candidate_id':f'eq.{candidate_id}'})
 await audit(candidate_id,control,p,actor)
 return {'global_candidate_id':candidate_id,'control':control,'status':p.status,'candidate_control_status':candidate_control_status,'selection_revoked':True}


@app.post('/global-sourcing/candidates/{candidate_id}/select')
async def select_candidate(candidate_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
 actor=identity(x_role,authorization,x_employee_id)
 if actor['role']!='owner': raise HTTPException(403,'Only owner may select a global supplier')
 rows=await get_backend().select('global_supplier_candidates',params={'global_candidate_id':f'eq.{candidate_id}','limit':'1'}) or []
 if not rows: raise HTTPException(404,'Candidate not found')
 c=rows[0]
 reqs=await get_backend().select('global_sourcing_requests',params={'sourcing_request_id':f'eq.{c["sourcing_request_id"]}','limit':'1'}) or []
 if not reqs: raise HTTPException(409,'Sourcing request is missing')
 status=await candidate_selection_status(c,reqs[0])
 if not status['selection_eligible']:
  raise HTTPException(409,detail={'message':'Supplier cannot be selected until all sourcing and country-corridor gates are READY','blockers':status['blockers']})
 await get_backend().patch('global_supplier_candidates',{'selected':False},params={'sourcing_request_id':f'eq.{c["sourcing_request_id"]}'})
 await get_backend().patch('global_supplier_candidates',{'selected':True,'updated_at':now()},params={'global_candidate_id':f'eq.{candidate_id}'})
 await get_backend().patch('global_sourcing_requests',{'status':'SHORTLISTED','updated_at':now()},params={'sourcing_request_id':f'eq.{c["sourcing_request_id"]}'})
 return {'global_candidate_id':candidate_id,'selected':True,'supplier_country':c.get('supplier_country'),
  'candidate_control_status':c.get('corridor_status'),'country_corridor':status['country_corridor'],'selection_status':status}
