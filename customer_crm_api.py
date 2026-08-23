from __future__ import annotations

import os, secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from auth import verify_owner_token
from insforge_backend import get_backend
from crm_campaign_bootstrap import CAMPAIGN, bootstrap_cuba_mipyme_outreach, load_seed

app=FastAPI(title='SAHJONY Customer CRM',version='1.1.0',docs_url=None,redoc_url=None)
Role=Literal['owner','employee']
_BOOTSTRAP_STATUS={'campaign':CAMPAIGN,'seed_count':len(load_seed()),'status':'PENDING','result':None}

def now(): return datetime.now(timezone.utc).isoformat()
def employee_token():
    token=os.getenv('EMPLOYEE_TOKEN','').strip()
    if not token: raise HTTPException(503,'Employee access not configured')
    return token

def identity(role,authorization,employee_id):
    if role not in {'owner','employee'}: raise HTTPException(400,'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
    token=authorization.removeprefix('Bearer ').strip()
    if role=='owner':
        if not verify_owner_token(token): raise HTTPException(403,'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if not secrets.compare_digest(token,employee_token()): raise HTTPException(403,'Invalid employee credential')
    return {'role':'employee','id':(employee_id or 'staff')[:160]}

@app.on_event('startup')
async def bootstrap_campaign_leads():
    global _BOOTSTRAP_STATUS
    try:
        result=await bootstrap_cuba_mipyme_outreach()
        _BOOTSTRAP_STATUS={'campaign':CAMPAIGN,'seed_count':len(load_seed()),'status':'IMPORTED','result':result}
    except Exception as exc:
        _BOOTSTRAP_STATUS={'campaign':CAMPAIGN,'seed_count':len(load_seed()),'status':'WAITING_FOR_DURABLE_BACKEND','result':{'error_type':type(exc).__name__}}

class IntakeIn(BaseModel):
    legal_name:str=Field(min_length=2,max_length=240)
    trade_name:str|None=None
    contact_name:str=Field(min_length=2,max_length=160)
    email:str=Field(min_length=5,max_length=320)
    phone:str|None=None
    country_code:str|None=None
    website:str|None=None
    product_need:str=Field(min_length=2,max_length=1000)
    specifications:str|None=None
    quantity:float|None=None
    target_budget:float|None=None
    currency:str='USD'
    destination_country:str=Field(min_length=2,max_length=3)
    target_delivery_date:str|None=None
    preferred_incoterm:str|None=None
    notes:str|None=None

    @field_validator('email')
    @classmethod
    def validate_email(cls,v:str)->str:
        value=v.strip().lower()
        if '@' not in value or value.startswith('@') or value.endswith('@') or '.' not in value.split('@',1)[1]:
            raise ValueError('Valid email required')
        return value

class QualifyIn(BaseModel):
    status:Literal['QUALIFIED','NEEDS_INFO','DISQUALIFIED']
    assigned_employee_id:str|None=None
    notes:str|None=None

async def audit(actor,event,summary,customer_id=None,intake_id=None,payload=None):
    await get_backend().insert('customer_crm_audit',{
        'event_id':f'crm_{secrets.token_urlsafe(10)}','customer_id':customer_id,'intake_id':intake_id,
        'actor_role':actor['role'],'actor_id':actor['id'],'event_type':event,'summary':summary,
        'payload':payload or {},'created_at':now()
    })

@app.get('/crm/health')
async def health(): return {'status':'ok','service':'customer-crm','public_intake':True,'fail_closed_promotion':True,'campaign_bootstrap':_BOOTSTRAP_STATUS}

@app.post('/crm/intake')
async def public_intake(p:IntakeIn):
    backend=get_backend(); ts=now(); email=p.email
    existing=await backend.select('customer_accounts',params={'email':f'eq.{email}','limit':'1'}) or []
    if existing:
        customer_id=existing[0]['customer_id']
        await backend.patch('customer_accounts',{'legal_name':p.legal_name,'trade_name':p.trade_name,'contact_name':p.contact_name,'phone':p.phone,'country_code':(p.country_code or '').upper() or None,'website':p.website,'updated_at':ts},params={'customer_id':f'eq.{customer_id}'})
    else:
        customer_id=f'cus_{secrets.token_urlsafe(10)}'
        await backend.insert('customer_accounts',{'customer_id':customer_id,'legal_name':p.legal_name,'trade_name':p.trade_name,'contact_name':p.contact_name,'email':email,'phone':p.phone,'country_code':(p.country_code or '').upper() or None,'website':p.website,'status':'PROSPECT','source':'WEB','created_at':ts,'updated_at':ts})
    intake_id=f'int_{secrets.token_urlsafe(10)}'
    row={'intake_id':intake_id,'customer_id':customer_id,'product_need':p.product_need,'specifications':p.specifications,'quantity':p.quantity,'target_budget':p.target_budget,'currency':p.currency.upper(),'destination_country':p.destination_country.upper(),'target_delivery_date':p.target_delivery_date,'preferred_incoterm':p.preferred_incoterm,'notes':p.notes,'status':'NEW','qualification_status':'PENDING','created_at':ts,'updated_at':ts}
    await backend.insert('customer_trade_intakes',row)
    await audit({'role':'customer','id':customer_id},'intake_created','Customer submitted a new trade sourcing request',customer_id,intake_id)
    return {'intake':row,'customer':{'customer_id':customer_id,'legal_name':p.legal_name,'contact_name':p.contact_name,'email':email}}

@app.get('/crm/customers')
async def list_customers(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); params={'order':'updated_at.desc','limit':'250'}
    if actor['role']=='employee': params['assigned_employee_id']=f'eq.{actor["id"]}'
    return {'customers':await get_backend().select('customer_accounts',params=params) or []}

@app.get('/crm/intakes')
async def list_intakes(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); params={'order':'updated_at.desc','limit':'250'}
    if actor['role']=='employee': params['assigned_employee_id']=f'eq.{actor["id"]}'
    return {'intakes':await get_backend().select('customer_trade_intakes',params=params) or []}

@app.patch('/crm/intakes/{intake_id}/qualify')
async def qualify(intake_id:str,p:QualifyIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); rows=await get_backend().select('customer_trade_intakes',params={'intake_id':f'eq.{intake_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Intake not found')
    assigned=p.assigned_employee_id or (actor['id'] if actor['role']=='employee' else rows[0].get('assigned_employee_id'))
    values={'qualification_status':p.status,'status':'QUALIFIED' if p.status=='QUALIFIED' else ('NEEDS_INFO' if p.status=='NEEDS_INFO' else 'CLOSED'),'assigned_employee_id':assigned,'updated_at':now()}
    await get_backend().patch('customer_trade_intakes',values,params={'intake_id':f'eq.{intake_id}'})
    if assigned: await get_backend().patch('customer_accounts',{'assigned_employee_id':assigned,'status':'ACTIVE' if p.status=='QUALIFIED' else 'PROSPECT','updated_at':now()},params={'customer_id':f'eq.{rows[0]["customer_id"]}'})
    await audit(actor,'intake_qualified',f'Intake qualification -> {p.status}',rows[0]['customer_id'],intake_id,{'notes':p.notes,'assigned_employee_id':assigned})
    return {'intake_id':intake_id,'qualification_status':p.status,'assigned_employee_id':assigned}

@app.post('/crm/intakes/{intake_id}/promote')
async def promote(intake_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); backend=get_backend(); rows=await backend.select('customer_trade_intakes',params={'intake_id':f'eq.{intake_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Intake not found')
    row=rows[0]
    if row.get('qualification_status')!='QUALIFIED': raise HTTPException(409,'Only QUALIFIED customer intakes may enter managed trade')
    if row.get('managed_trade_request_id'): return {'intake_id':intake_id,'managed_trade_request_id':row.get('managed_trade_request_id'),'sourcing_request_id':row.get('sourcing_request_id'),'already_promoted':True}
    ts=now(); mtr=f'mtr_{secrets.token_urlsafe(10)}'; gsr=f'gsr_{secrets.token_urlsafe(10)}'
    common={'product_need':row['product_need'],'specifications':row.get('specifications'),'quantity':row.get('quantity'),'target_budget':row.get('target_budget'),'currency':row.get('currency') or 'USD','destination_country':row.get('destination_country'),'target_delivery_date':row.get('target_delivery_date')}
    await backend.insert('managed_trade_requests',{'request_id':mtr,'requester_type':'BUYER','requester_ref':row['customer_id'],'private_business_id':None,'employee_id':row.get('assigned_employee_id'),'assigned_owner_id':'owner','assigned_employee_id':row.get('assigned_employee_id'),**common,'status':'INTAKE','created_at':ts,'updated_at':ts})
    await backend.insert('global_sourcing_requests',{'sourcing_request_id':gsr,'requester_type':'BUYER','requester_ref':row['customer_id'],**common,'worldwide_search':True,'status':'SEARCHING','assigned_owner_id':'owner','assigned_employee_id':row.get('assigned_employee_id'),'created_at':ts,'updated_at':ts})
    await backend.patch('customer_trade_intakes',{'status':'PROMOTED','managed_trade_request_id':mtr,'sourcing_request_id':gsr,'updated_at':ts},params={'intake_id':f'eq.{intake_id}'})
    await audit(actor,'intake_promoted','Qualified customer intake promoted into Managed Trade and Worldwide Sourcing',row['customer_id'],intake_id,{'managed_trade_request_id':mtr,'sourcing_request_id':gsr})
    return {'intake_id':intake_id,'managed_trade_request_id':mtr,'sourcing_request_id':gsr,'already_promoted':False}
