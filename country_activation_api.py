from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Global Country Activation', version='1.0.0', docs_url=None, redoc_url=None)
Role = Literal['owner','employee']
Status = Literal['READY','LIMITED','BLOCKED']
ControlStatus = Literal['READY','LIMITED','BLOCKED','NOT_APPLICABLE']

MANDATORY_CONTROLS = [
    ('legal_entity_trading_eligibility','Legal entity / trading eligibility'),
    ('importer_exporter_registration','Importer / exporter registration'),
    ('customs_broker_coverage','Customs broker coverage'),
    ('sanctions_export_controls','Sanctions / export controls'),
    ('product_restrictions','Product restrictions'),
    ('tax_vat_gst','Tax / VAT / GST'),
    ('banking_settlement','Banking / settlement'),
    ('currency_support','Supported currencies'),
    ('freight_carrier_coverage','Freight / carrier coverage'),
    ('cargo_liability_insurance','Cargo / liability insurance'),
    ('document_requirements','Document requirements'),
    ('translation_language','Translation / language'),
    ('local_contracts','Local contracts'),
    ('warehouse_3pl','Warehouse / 3PL'),
    ('data_privacy','Data / privacy'),
    ('accounting_reconciliation','Accounting / reconciliation'),
]

class CountryCreate(BaseModel):
    country_code: str = Field(min_length=2,max_length=3)
    country_name: str = Field(min_length=2,max_length=120)
    region: str | None = Field(default=None,max_length=120)
    default_currency: str | None = Field(default=None,max_length=12)
    default_locale: str | None = Field(default=None,max_length=32)
    notes: str | None = Field(default=None,max_length=2000)

class ControlUpdate(BaseModel):
    status: ControlStatus
    evidence_summary: str | None = Field(default=None,max_length=4000)
    evidence_source: str | None = Field(default=None,max_length=300)
    evidence_reference: str | None = Field(default=None,max_length=1000)
    expires_at: str | None = None

class ApprovalRequest(BaseModel):
    operating_status: Status
    note: str | None = Field(default=None,max_length=2000)

class CorridorCreate(BaseModel):
    origin_country_code: str = Field(min_length=2,max_length=3)
    destination_country_code: str = Field(min_length=2,max_length=3)
    status: Status = 'BLOCKED'
    allowed_incoterms: list[str] = Field(default_factory=list,max_length=20)
    supported_currencies: list[str] = Field(default_factory=list,max_length=20)
    carrier_coverage: bool = False
    broker_coverage: bool = False
    banking_coverage: bool = False
    insurance_coverage: bool = False
    tax_model_verified: bool = False


def now(): return datetime.now(timezone.utc).isoformat()

def employee_token():
    token=os.getenv('EMPLOYEE_TOKEN','').strip()
    if not token: raise HTTPException(503,'Employee country access is not configured')
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

async def audit(country_code, actor, event_type, summary, payload=None):
    row={'event_id':f'cae_{secrets.token_urlsafe(12)}','country_code':country_code,'actor_role':actor['role'],'actor_id':actor['id'],
         'event_type':event_type,'summary':summary,'payload':payload or {},'created_at':now()}
    await get_backend().insert('country_activation_audit',row)
    return row

async def controls_for(country_code: str):
    return await get_backend().select('country_activation_controls',params={'country_code':f'eq.{country_code}','order':'control_key.asc','limit':'100'}) or []

def derived_status(controls):
    by={c.get('control_key'):c.get('status') for c in controls}
    states=[by.get(key,'BLOCKED') for key,_ in MANDATORY_CONTROLS]
    if any(s=='BLOCKED' for s in states): return 'BLOCKED'
    if any(s=='LIMITED' for s in states): return 'LIMITED'
    return 'READY'

@app.get('/countries/health')
async def health():
    return {'status':'ok','service':'global-country-activation','fail_closed':True,'mandatory_controls':len(MANDATORY_CONTROLS)}

@app.get('/countries')
async def list_countries(status: str|None=Query(default=None,max_length=20), x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    params={'order':'country_name.asc','limit':'300'}
    if status: params['operating_status']=f'eq.{status.upper()}'
    rows=await get_backend().select('country_activation_profiles',params=params) or []
    return {'countries':rows,'actor':actor}

@app.post('/countries')
async def create_country(payload: CountryCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    code=payload.country_code.upper(); ts=now()
    row={'country_code':code,'country_name':payload.country_name,'region':payload.region,'operating_status':'BLOCKED','default_currency':(payload.default_currency or '').upper() or None,
         'default_locale':payload.default_locale,'notes':payload.notes,'owner_approved':False,'created_at':ts,'updated_at':ts}
    await get_backend().insert('country_activation_profiles',row)
    control_rows=[]
    for key,label in MANDATORY_CONTROLS:
        control_rows.append({'control_id':f'cac_{secrets.token_urlsafe(12)}','country_code':code,'control_key':key,'control_label':label,'status':'BLOCKED','created_at':ts,'updated_at':ts})
    await get_backend().insert('country_activation_controls',control_rows)
    await audit(code,actor,'country_created',f'{payload.country_name} added in BLOCKED state')
    return {'country':row,'controls':control_rows}

@app.get('/countries/{country_code}')
async def country_detail(country_code: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); code=country_code.upper()
    rows=await get_backend().select('country_activation_profiles',params={'country_code':f'eq.{code}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Country not found')
    controls=await controls_for(code)
    corridors=await get_backend().select('trade_corridor_activations',params={'or':f'(origin_country_code.eq.{code},destination_country_code.eq.{code})','limit':'100'}) or []
    return {'country':rows[0],'controls':controls,'derived_status':derived_status(controls),'corridors':corridors,'actor':actor}

@app.patch('/countries/{country_code}/controls/{control_key}')
async def update_control(country_code: str, control_key: str, payload: ControlUpdate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); code=country_code.upper()
    valid={k for k,_ in MANDATORY_CONTROLS}
    if control_key not in valid: raise HTTPException(404,'Unknown country control')
    ts=now(); values={'status':payload.status,'evidence_summary':payload.evidence_summary,'evidence_source':payload.evidence_source,'evidence_reference':payload.evidence_reference,
                     'reviewed_by_role':actor['role'],'reviewed_by_id':actor['id'],'reviewed_at':ts,'expires_at':payload.expires_at,'updated_at':ts}
    result=await get_backend().patch('country_activation_controls',values,params={'country_code':f'eq.{code}','control_key':f'eq.{control_key}'})
    controls=await controls_for(code); derived=derived_status(controls)
    # Any material control change invalidates owner approval and pushes country to derived state.
    await get_backend().patch('country_activation_profiles',{'operating_status':derived,'owner_approved':False,'approved_by':None,'approved_at':None,'updated_at':ts},params={'country_code':f'eq.{code}'})
    await audit(code,actor,'control_updated',f'{control_key} -> {payload.status}',{'derived_status':derived})
    return {'country_code':code,'control_key':control_key,'status':payload.status,'derived_status':derived,'persistence':result}

@app.post('/countries/{country_code}/approve')
async def approve_country(country_code: str, payload: ApprovalRequest, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner': raise HTTPException(403,'Only owner may approve country activation')
    code=country_code.upper(); controls=await controls_for(code); derived=derived_status(controls)
    if payload.operating_status=='READY' and derived!='READY':
        raise HTTPException(409,f'Country cannot be READY while derived control status is {derived}')
    if payload.operating_status=='LIMITED' and derived=='BLOCKED':
        raise HTTPException(409,'Country cannot be LIMITED while mandatory controls remain BLOCKED')
    ts=now(); values={'operating_status':payload.operating_status,'owner_approved':True,'approved_by':actor['id'],'approved_at':ts,'notes':payload.note,'updated_at':ts}
    await get_backend().patch('country_activation_profiles',values,params={'country_code':f'eq.{code}'})
    await audit(code,actor,'country_approved',f'Country approved as {payload.operating_status}',{'derived_status':derived,'note':payload.note})
    return {'country_code':code,'operating_status':payload.operating_status,'derived_status':derived,'owner_approved':True}

@app.post('/countries/corridors')
async def create_corridor(payload: CorridorCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    origin=payload.origin_country_code.upper(); destination=payload.destination_country_code.upper()
    if origin==destination: raise HTTPException(400,'Origin and destination must differ')
    if payload.status=='READY' and not (payload.carrier_coverage and payload.broker_coverage and payload.banking_coverage and payload.insurance_coverage and payload.tax_model_verified):
        raise HTTPException(409,'READY corridor requires carrier, broker, banking, insurance and tax coverage')
    cid=f'corr_{origin}_{destination}_{secrets.token_urlsafe(6)}'; ts=now()
    row={'corridor_id':cid,'origin_country_code':origin,'destination_country_code':destination,'status':payload.status,'allowed_incoterms':payload.allowed_incoterms,
         'supported_currencies':[x.upper() for x in payload.supported_currencies],'carrier_coverage':payload.carrier_coverage,'broker_coverage':payload.broker_coverage,
         'banking_coverage':payload.banking_coverage,'insurance_coverage':payload.insurance_coverage,'tax_model_verified':payload.tax_model_verified,
         'owner_approved':actor['role']=='owner','approval_note':None,'created_at':ts,'updated_at':ts}
    await get_backend().insert('trade_corridor_activations',row)
    await audit(destination,actor,'corridor_created',f'{origin} -> {destination} corridor created as {payload.status}',{'corridor_id':cid})
    return {'corridor':row}
