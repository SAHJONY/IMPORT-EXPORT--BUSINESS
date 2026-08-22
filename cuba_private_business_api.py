from __future__ import annotations

import os, secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Cuba Private Business Desk', version='1.0.0', docs_url=None, redoc_url=None)
Role = Literal['owner','employee']


def now(): return datetime.now(timezone.utc).isoformat()
def employee_token():
    token=os.getenv('EMPLOYEE_TOKEN','').strip()
    if not token: raise HTTPException(503,'Employee access not configured')
    return token

def identity(role, authorization, employee_id):
    if role not in {'owner','employee'}: raise HTTPException(400,'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
    token=authorization.removeprefix('Bearer ').strip()
    if role=='owner':
        if not verify_owner_token(token): raise HTTPException(403,'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if not secrets.compare_digest(token,employee_token()): raise HTTPException(403,'Invalid employee credential')
    return {'role':'employee','id':(employee_id or 'staff')[:160]}

class BusinessIn(BaseModel):
    legal_name:str=Field(min_length=2,max_length=240)
    trade_name:str|None=Field(default=None,max_length=240)
    business_type:Literal['SOLE_PROPRIETOR','SMALL_PRIVATE_BUSINESS','PRIVATE_COOPERATIVE','INDEPENDENT_CONTRACTOR','CONSULTANT','SMALL_FARMER','USUFRUCT_FARMER','OTHER_PRIVATE']
    registration_reference:str|None=Field(default=None,max_length=240)
    province:str|None=Field(default=None,max_length=120)
    municipality:str|None=Field(default=None,max_length=120)
    employee_count:int=Field(default=0,ge=0,le=100000)
    owner_names:list[str]=Field(default_factory=list,max_length=100)
    ownership_evidence_document_ids:list[str]=Field(default_factory=list,max_length=100)
    business_categories:list[str]=Field(default_factory=list,max_length=100)
    state_entity_involvement:str|None=Field(default=None,max_length=2000)
    state_entity_involvement_level:Literal['NONE','PACKING_ONLY','EXPORT_AGENT_ONLY','DISTRIBUTION_ONLY','PROCESSING','MANUFACTURING','CONTROL','OTHER']='NONE'
    prohibited_official_owner:bool=False
    prohibited_party_member_owner:bool=False
    government_owned:bool=False
    government_operated:bool=False
    government_controlled:bool=False
    uses_cuban_owned_bank:bool=False

class ReviewIn(BaseModel):
    restricted_party_screening_status:Literal['CLEAR','HIT','REVIEW_REQUIRED']
    banking_path_verified:bool=False
    bis_scp_eligible_end_user:bool=False
    eligibility_basis:str=Field(min_length=2,max_length=4000)

class EvidenceIn(BaseModel):
    evidence_type:str=Field(min_length=2,max_length=120)
    source:str|None=Field(default=None,max_length=240)
    reference:str|None=Field(default=None,max_length=1000)
    document_id:str|None=Field(default=None,max_length=240)
    summary:str=Field(min_length=2,max_length=4000)


def derive_eligibility(row:dict, review:ReviewIn|None=None):
    reasons=[]
    if int(row.get('employee_count') or 0)>100: reasons.append('Employee count exceeds current OFAC independent-private-sector small-business threshold')
    if row.get('prohibited_official_owner'): reasons.append('Ownership includes a prohibited Government of Cuba official')
    if row.get('prohibited_party_member_owner'): reasons.append('Ownership includes a prohibited Cuban Communist Party member')
    if row.get('government_owned') or row.get('government_operated') or row.get('government_controlled'): reasons.append('Business is government-owned, operated, or controlled')
    if row.get('state_entity_involvement_level') in {'CONTROL'}: reasons.append('State entity control is incompatible with independent private-sector eligibility')
    if review and review.restricted_party_screening_status=='HIT': reasons.append('Restricted-party screening hit')
    if reasons: return 'INELIGIBLE', False, reasons
    if not row.get('owner_names'): return 'REVIEW_REQUIRED', False, ['Ownership evidence is incomplete']
    if review and row.get('uses_cuban_owned_bank') and review.bis_scp_eligible_end_user:
        return 'REVIEW_REQUIRED', False, ['SCP banking restriction requires transaction-specific review because a Cuban-owned bank is involved']
    if review and review.restricted_party_screening_status=='CLEAR' and review.banking_path_verified:
        return 'ELIGIBLE', True, []
    return 'REVIEW_REQUIRED', False, ['Screening and banking review remain incomplete']

@app.get('/cuba-private/health')
async def health():
    return {'status':'ok','service':'cuba-private-business-desk','ofac_definition':'31 CFR 515.340','max_small_business_employees':100,'fail_closed':True}

@app.get('/cuba-private/businesses')
async def list_businesses(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role,authorization,x_employee_id)
    rows=await get_backend().select('cuba_private_businesses',params={'order':'legal_name.asc','limit':'300'}) or []
    return {'businesses':rows}

@app.post('/cuba-private/businesses')
async def create_business(p:BusinessIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    bid=f'cpb_{secrets.token_urlsafe(10)}'; ts=now()
    base={
        'private_business_id':bid,**p.model_dump(),'eligible_independent_private_sector':False,'eligibility_status':'PENDING',
        'eligibility_basis':None,'ofac_reviewed_at':None,'bis_scp_eligible_end_user':False,'bis_scp_reviewed_at':None,
        'banking_path_verified':False,'restricted_party_screening_status':'PENDING','restricted_party_screened_at':None,
        'status':'ACTIVE','verified_by':None,'verified_at':None,'created_at':ts,'updated_at':ts,
    }
    status,eligible,reasons=derive_eligibility(base)
    base['eligibility_status']=status;base['eligible_independent_private_sector']=eligible
    if reasons: base['eligibility_basis']='; '.join(reasons)
    await get_backend().insert('cuba_private_businesses',base)
    return {'business':base}

@app.post('/cuba-private/businesses/{business_id}/evidence')
async def add_evidence(business_id:str,p:EvidenceIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    eid=f'cpbe_{secrets.token_urlsafe(10)}'
    row={'evidence_id':eid,'private_business_id':business_id,**p.model_dump(),'status':'PENDING','reviewed_by':None,'reviewed_at':None,'created_at':now()}
    await get_backend().insert('cuba_private_business_evidence',row)
    return {'evidence':row,'actor':actor}

@app.post('/cuba-private/businesses/{business_id}/review')
async def review_business(business_id:str,p:ReviewIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner': raise HTTPException(403,'Only owner/compliance authority may verify private-business eligibility')
    rows=await get_backend().select('cuba_private_businesses',params={'private_business_id':f'eq.{business_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Private business not found')
    business=rows[0]
    status,eligible,reasons=derive_eligibility(business,p)
    basis=p.eligibility_basis + ((' | '+ '; '.join(reasons)) if reasons else '')
    ts=now(); values={
        'eligible_independent_private_sector':eligible,'eligibility_status':status,'eligibility_basis':basis,
        'restricted_party_screening_status':p.restricted_party_screening_status,'restricted_party_screened_at':ts,
        'banking_path_verified':p.banking_path_verified,'bis_scp_eligible_end_user':p.bis_scp_eligible_end_user,
        'ofac_reviewed_at':ts,'bis_scp_reviewed_at':ts,'verified_by':actor['id'] if eligible else None,'verified_at':ts if eligible else None,'updated_at':ts,
    }
    await get_backend().patch('cuba_private_businesses',values,params={'private_business_id':f'eq.{business_id}'})
    return {'private_business_id':business_id,'eligibility_status':status,'eligible_independent_private_sector':eligible,'reasons':reasons}

@app.get('/cuba-private/businesses/{business_id}')
async def detail(business_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role,authorization,x_employee_id)
    rows=await get_backend().select('cuba_private_businesses',params={'private_business_id':f'eq.{business_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Private business not found')
    evidence=await get_backend().select('cuba_private_business_evidence',params={'private_business_id':f'eq.{business_id}','order':'created_at.desc','limit':'100'}) or []
    return {'business':rows[0],'evidence':evidence}
