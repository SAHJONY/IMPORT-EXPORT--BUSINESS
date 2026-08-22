from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_customer_token, verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Global Trade Commercial Operations', version='1.1.0', docs_url=None, redoc_url=None)
Role = Literal['owner','employee','customer']

READINESS = [
    ('supplier_verified','Verified supplier and bank details'),
    ('buyer_verified','Verified buyer and commercial terms'),
    ('product_passport','Product trade passport complete'),
    ('corridor_approved','Trade corridor approved'),
    ('quote_approved','Commercial quote margin approved'),
    ('sales_order','Sales order accepted'),
    ('purchase_order','Purchase order approved'),
    ('funds_ready','Payment/treasury conditions satisfied'),
    ('quality_passed','QC / inspection passed'),
    ('compliance_released','Legal/customs compliance released'),
    ('documents_ready','Required trade documents released'),
    ('shipping_booked','Shipment booked and tracking active'),
    ('insurance_active','Required cargo/credit insurance evidenced'),
    ('delivery_completed','Final delivery confirmed'),
    ('receivable_collected','Customer receivable collected'),
    ('profit_reconciled','Landed cost and profit reconciled'),
]

class MasterCreate(BaseModel):
    legal_name: str = Field(min_length=2,max_length=240)
    country: str | None = Field(default=None,max_length=100)
    contact_name: str | None = Field(default=None,max_length=160)
    contact_email: str | None = Field(default=None,max_length=240)
    contact_phone: str | None = Field(default=None,max_length=80)
    payment_terms: str | None = Field(default=None,max_length=240)
    currency: str | None = Field(default='USD',max_length=12)

class ProductCreate(BaseModel):
    sku: str = Field(min_length=1,max_length=100)
    name: str = Field(min_length=2,max_length=240)
    description: str | None = Field(default=None,max_length=2000)
    origin_country: str | None = Field(default=None,max_length=100)
    hts_code: str | None = Field(default=None,max_length=40)
    schedule_b: str | None = Field(default=None,max_length=40)
    eccn: str | None = Field(default=None,max_length=40)
    target_landed_cost: float | None = None
    target_sell_price: float | None = None
    minimum_margin_pct: float | None = None

class CorridorCreate(BaseModel):
    origin_country: str = Field(min_length=2,max_length=100)
    destination_country: str = Field(min_length=2,max_length=100)
    default_incoterm: str | None = Field(default=None,max_length=20)
    preferred_broker: str | None = Field(default=None,max_length=240)
    preferred_forwarder: str | None = Field(default=None,max_length=240)
    transit_days: int | None = Field(default=None,ge=0,le=365)

class QuoteCreate(BaseModel):
    trade_case_id: str = Field(min_length=1,max_length=160)
    buyer_id: str | None = Field(default=None,max_length=160)
    product_id: str | None = Field(default=None,max_length=160)
    corridor_id: str | None = Field(default=None,max_length=160)
    quantity: float = Field(gt=0)
    unit_price: float = Field(gt=0)
    currency: str = Field(default='USD',max_length=12)
    incoterm: str | None = Field(default=None,max_length=20)
    supplier_cost: float = Field(default=0,ge=0)
    freight_estimate: float = Field(default=0,ge=0)
    duty_estimate: float = Field(default=0,ge=0)
    insurance_estimate: float = Field(default=0,ge=0)
    finance_cost_estimate: float = Field(default=0,ge=0)
    other_cost_estimate: float = Field(default=0,ge=0)

class ReadinessUpdate(BaseModel):
    check_key: str = Field(min_length=1,max_length=120)
    status: Literal['pending','pass','fail','waived']
    evidence_ref: str | None = Field(default=None,max_length=500)
    notes: str | None = Field(default=None,max_length=2000)


def now(): return datetime.now(timezone.utc).isoformat()

def employee_token():
    token=os.getenv('EMPLOYEE_TOKEN')
    if not token: raise HTTPException(503,'Employee commercial operations are not configured')
    return token

def identity(role, authorization, employee_id):
    if role not in {'owner','employee','customer'}: raise HTTPException(400,'Invalid X-Role')
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
    token=authorization.removeprefix('Bearer ').strip()
    if role=='owner':
        if not verify_owner_token(token): raise HTTPException(403,'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if role=='employee':
        if not secrets.compare_digest(token,employee_token()): raise HTTPException(403,'Invalid employee credential')
        return {'role':'employee','id':(employee_id or 'staff')[:160]}
    c=verify_customer_token(token)
    if not c: raise HTTPException(403,'Invalid customer credential')
    return {'role':'customer','id':str(c['participant_id'])}

def internal_actor(role, authorization, employee_id):
    actor=identity(role,authorization,employee_id)
    if actor['role']=='customer': raise HTTPException(403,'Commercial economics and readiness controls are internal')
    return actor

async def publish(trade_case_id,actor,title,body,severity='info',action_required=False):
    try:
        await get_backend().insert('business_events',{
            'event_id':f'evt_{secrets.token_urlsafe(14)}','trade_case_id':trade_case_id,'customer_id':None,
            'event_type':'commercial','source':'commercial_api','source_ref':trade_case_id,'title':title,'body':body,
            'severity':severity,'action_required':action_required,'customer_visible':False,
            'actor_role':actor['role'],'actor_id':actor['id'],'created_at':now()})
    except Exception:
        pass

@app.get('/commercial/health')
async def health():
    return {'status':'ok','service':'commercial-execution','persistence':'insforge','first_live_trade_gate':True,'customer_economics_exposed':False}

@app.post('/commercial/suppliers')
async def create_supplier(payload: MasterCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    internal_actor(x_role,authorization,x_employee_id)
    sid=f'sup_{secrets.token_urlsafe(12)}'; ts=now()
    row={'supplier_id':sid,**payload.model_dump(),'compliance_status':'pending','quality_status':'pending','bank_verified':False,'created_at':ts,'updated_at':ts}
    await get_backend().insert('trade_suppliers',row); return {'supplier':row}

@app.get('/commercial/suppliers')
async def list_suppliers(x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    internal_actor(x_role,authorization,x_employee_id)
    return {'suppliers':await get_backend().select('trade_suppliers',params={'order':'updated_at.desc','limit':'250'}) or []}

@app.post('/commercial/buyers')
async def create_buyer(payload: MasterCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    internal_actor(x_role,authorization,x_employee_id)
    bid=f'buy_{secrets.token_urlsafe(12)}'; ts=now()
    row={'buyer_id':bid,**payload.model_dump(),'credit_status':'pending','compliance_status':'pending','created_at':ts,'updated_at':ts}
    await get_backend().insert('trade_buyers',row); return {'buyer':row}

@app.post('/commercial/products')
async def create_product(payload: ProductCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    internal_actor(x_role,authorization,x_employee_id)
    pid=f'prd_{secrets.token_urlsafe(12)}'; ts=now()
    row={'product_id':pid,**payload.model_dump(),'active':True,'created_at':ts,'updated_at':ts}
    await get_backend().insert('trade_products',row); return {'product':row}

@app.post('/commercial/corridors')
async def create_corridor(payload: CorridorCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    internal_actor(x_role,authorization,x_employee_id)
    cid=f'cor_{secrets.token_urlsafe(12)}'; ts=now()
    row={'corridor_id':cid,**payload.model_dump(),'active':True,'created_at':ts,'updated_at':ts}
    await get_backend().insert('trade_corridors',row); return {'corridor':row}

@app.post('/commercial/quotes')
async def create_quote(payload: QuoteCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=internal_actor(x_role,authorization,x_employee_id)
    revenue=payload.quantity*payload.unit_price
    landed=(payload.quantity*payload.supplier_cost)+payload.freight_estimate+payload.duty_estimate+payload.insurance_estimate+payload.finance_cost_estimate+payload.other_cost_estimate
    margin=revenue-landed; margin_pct=(margin/revenue*100) if revenue else 0
    qid=f'quo_{secrets.token_urlsafe(12)}'; ts=now()
    row={'quote_id':qid,**payload.model_dump(exclude={'supplier_cost'}),'estimated_landed_cost':landed,'estimated_margin':margin,'estimated_margin_pct':margin_pct,'status':'draft','owner_approved':False,'created_by_role':actor['role'],'created_by_id':actor['id'],'created_at':ts,'updated_at':ts}
    await get_backend().insert('commercial_quotes',row)
    await publish(payload.trade_case_id,actor,'Commercial quote created',f'Quote {qid} margin {margin_pct:.2f}% requires approval before commitment.','info',True)
    return {'quote':row}

@app.get('/commercial/cases/{trade_case_id}/summary')
async def case_summary(trade_case_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=internal_actor(x_role,authorization,x_employee_id)
    tables=['commercial_quotes','sales_orders','purchase_orders','quality_inspections','landed_costs','trade_payments','trade_incidents','trade_readiness_checks']
    out={}
    for table in tables:
        order='updated_at.desc' if table=='trade_readiness_checks' else 'created_at.desc'
        rows=await get_backend().select(table,params={'trade_case_id':f'eq.{trade_case_id}','order':order,'limit':'250'})
        out[table]=rows or []
    return {'trade_case_id':trade_case_id,'actor':actor,'operations':out}

@app.post('/commercial/cases/{trade_case_id}/readiness/initialize')
async def initialize_readiness(trade_case_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=internal_actor(x_role,authorization,x_employee_id)
    existing=await get_backend().select('trade_readiness_checks',params={'trade_case_id':f'eq.{trade_case_id}','limit':'250'}) or []
    existing_keys={r.get('check_key') for r in existing}
    new=[{'check_id':f'chk_{secrets.token_urlsafe(12)}','trade_case_id':trade_case_id,'check_key':key,'label':label,'status':'pending','updated_at':now()} for key,label in READINESS if key not in existing_keys]
    if new: await get_backend().insert('trade_readiness_checks',new)
    await publish(trade_case_id,actor,'First Live Trade readiness opened','Commercial execution gates initialized. Production trade is not ready until all required gates pass.','warning',True)
    return {'trade_case_id':trade_case_id,'checks_created':len(new),'total_checks':len(READINESS)}

@app.patch('/commercial/cases/{trade_case_id}/readiness')
async def update_readiness(trade_case_id: str, payload: ReadinessUpdate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=internal_actor(x_role,authorization,x_employee_id)
    if payload.check_key not in {k for k,_ in READINESS}: raise HTTPException(400,'Unknown readiness check')
    if payload.status=='waived' and actor['role']!='owner': raise HTTPException(403,'Only owner may waive a readiness control')
    values={'status':payload.status,'evidence_ref':payload.evidence_ref,'notes':payload.notes,'updated_at':now()}
    result=await get_backend().patch('trade_readiness_checks',values,params={'trade_case_id':f'eq.{trade_case_id}','check_key':f'eq.{payload.check_key}'})
    return {'trade_case_id':trade_case_id,'check_key':payload.check_key,'status':payload.status,'persistence':result}

@app.get('/commercial/cases/{trade_case_id}/readiness')
async def readiness(trade_case_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=internal_actor(x_role,authorization,x_employee_id)
    rows=await get_backend().select('trade_readiness_checks',params={'trade_case_id':f'eq.{trade_case_id}','order':'updated_at.asc','limit':'250'}) or []
    unresolved=[r for r in rows if r.get('status') not in {'pass','waived'}]
    ready=bool(rows) and not unresolved
    return {'trade_case_id':trade_case_id,'first_live_trade_ready':ready,'checks':rows,'unresolved_count':len(unresolved),'actor':actor}
