from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY LLC Global Industrial Marketplace', version='1.0.0', docs_url=None, redoc_url=None)

VerificationTier = Literal['LISTED','VERIFIED','FACTORY_VERIFIED','TRADE_READY','SAHJONY_MANAGED']
MediaRights = Literal['SUPPLIER_AUTHORIZED','DISTRIBUTOR_AUTHORIZED','LICENSED','PUBLIC_DOMAIN','PENDING_REVIEW']
PriceType = Literal['RFQ','INDICATIVE','FIXED']
SupplierType = Literal['MANUFACTURER','DISTRIBUTOR','WHOLESALER','EXPORTER']


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def employee_token() -> str:
    token = os.getenv('EMPLOYEE_TOKEN', '').strip()
    if not token:
        raise HTTPException(503, 'Employee access not configured')
    return token


def identity(role: str | None, authorization: str | None, employee_id: str | None) -> dict:
    if role not in {'owner','employee'}:
        raise HTTPException(400, 'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    token = authorization.removeprefix('Bearer ').strip()
    if role == 'owner':
        if not verify_owner_token(token):
            raise HTTPException(403, 'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if not secrets.compare_digest(token, employee_token()):
        raise HTTPException(403, 'Invalid employee credential')
    return {'role':'employee','id':(employee_id or 'staff')[:160]}


class SupplierIn(BaseModel):
    legal_name: str = Field(min_length=2,max_length=240)
    trade_name: str | None = None
    supplier_type: SupplierType
    country_code: str = Field(min_length=2,max_length=3)
    website: str | None = None
    public_contact_url: str | None = None
    verification_tier: VerificationTier = 'LISTED'
    source_url: str | None = None
    source_date: str | None = None
    notes: str | None = Field(default=None,max_length=5000)


class ProductIn(BaseModel):
    supplier_id: str = Field(min_length=4,max_length=120)
    sku: str | None = Field(default=None,max_length=160)
    manufacturer: str | None = Field(default=None,max_length=240)
    brand: str | None = Field(default=None,max_length=200)
    name: str = Field(min_length=2,max_length=500)
    category: str = Field(min_length=2,max_length=240)
    description: str = Field(min_length=2,max_length=8000)
    specifications: dict = Field(default_factory=dict)
    hs_code: str | None = Field(default=None,max_length=32)
    country_of_origin: str | None = Field(default=None,max_length=3)
    moq: float | None = None
    unit: str | None = Field(default=None,max_length=80)
    price_type: PriceType = 'RFQ'
    indicative_price: float | None = None
    currency: str = Field(default='USD',min_length=3,max_length=3)
    incoterms: list[str] = Field(default_factory=list,max_length=20)
    lead_time_days: int | None = Field(default=None,ge=0,le=3650)
    production_capacity: str | None = Field(default=None,max_length=500)
    certifications: list[str] = Field(default_factory=list,max_length=100)
    image_urls: list[str] = Field(default_factory=list,max_length=20)
    media_rights_status: MediaRights = 'PENDING_REVIEW'
    source_url: str | None = None
    source_date: str | None = None
    verification_tier: VerificationTier = 'LISTED'
    published: bool = False


class RfqIn(BaseModel):
    product_id: str | None = Field(default=None,max_length=120)
    buyer_company: str = Field(min_length=2,max_length=240)
    contact_name: str = Field(min_length=2,max_length=160)
    email: str = Field(min_length=5,max_length=320)
    country_code: str = Field(min_length=2,max_length=3)
    product_need: str = Field(min_length=2,max_length=1000)
    specifications: str | None = Field(default=None,max_length=8000)
    quantity: float | None = None
    unit: str | None = Field(default=None,max_length=80)
    target_budget: float | None = None
    currency: str = Field(default='USD',min_length=3,max_length=3)
    destination_country: str = Field(min_length=2,max_length=3)
    preferred_incoterm: str | None = Field(default=None,max_length=32)
    target_delivery_date: str | None = None
    managed_trade_requested: bool = True


@app.get('/marketplace/health')
async def health():
    backend = persistent_backend_status()
    return {
        'status':'ok' if backend['configured'] else 'configuration_required',
        'service':'sahjony-llc-global-industrial-marketplace',
        'version':'1.0.0',
        'capital_model':'ZERO_OWN_INVENTORY',
        'buyer_checkout_default':False,
        'rfq_first':True,
        'supplier_media_rights_required':True,
        'verification_tiers':['LISTED','VERIFIED','FACTORY_VERIFIED','TRADE_READY','SAHJONY_MANAGED'],
        'fee_model':['SUPPLIER_COMMISSION','BUYER_SOURCING_FEE','MANAGED_TRADE_FEE'],
        'dual_compensation_requires_appropriate_disclosure':True,
        'persistence_configured':backend['configured'],
        'fail_closed':True,
    }


@app.post('/marketplace/suppliers')
async def add_supplier(payload: SupplierIn, x_role: str | None = Header(None,alias='X-Role'), authorization: str | None = Header(None,alias='Authorization'), x_employee_id: str | None = Header(None,alias='X-Employee-Id')):
    actor = identity(x_role,authorization,x_employee_id)
    supplier_id = f'sup_{secrets.token_urlsafe(10)}'
    row = {
        'supplier_id':supplier_id,
        'legal_name':payload.legal_name,
        'trade_name':payload.trade_name,
        'supplier_type':payload.supplier_type,
        'country_code':payload.country_code.upper(),
        'website':payload.website,
        'public_contact_url':payload.public_contact_url,
        'verification_tier':payload.verification_tier,
        'source_url':payload.source_url,
        'source_date':payload.source_date,
        'status':'RESEARCH' if payload.verification_tier=='LISTED' else 'QUALIFICATION',
        'notes':payload.notes,
        'created_by':actor['id'],
        'created_at':now(),
        'updated_at':now(),
    }
    await get_backend().insert('marketplace_suppliers',row)
    return {'supplier':row}


@app.post('/marketplace/products')
async def add_product(payload: ProductIn, x_role: str | None = Header(None,alias='X-Role'), authorization: str | None = Header(None,alias='Authorization'), x_employee_id: str | None = Header(None,alias='X-Employee-Id')):
    actor = identity(x_role,authorization,x_employee_id)
    if payload.published and payload.media_rights_status == 'PENDING_REVIEW':
        raise HTTPException(409,'Cannot publish product imagery until media rights are evidenced')
    product_id = f'prd_{secrets.token_urlsafe(10)}'
    row = {
        'product_id':product_id,'supplier_id':payload.supplier_id,'sku':payload.sku,
        'manufacturer':payload.manufacturer,'brand':payload.brand,'name':payload.name,
        'category':payload.category,'description':payload.description,'specifications':payload.specifications,
        'hs_code':payload.hs_code,'country_of_origin':(payload.country_of_origin or '').upper() or None,
        'moq':payload.moq,'unit':payload.unit,'price_type':payload.price_type,
        'indicative_price':payload.indicative_price,'currency':payload.currency.upper(),
        'incoterms':[x.upper() for x in payload.incoterms], 'lead_time_days':payload.lead_time_days,
        'production_capacity':payload.production_capacity,'certifications':payload.certifications,
        'image_urls':payload.image_urls,'media_rights_status':payload.media_rights_status,
        'source_url':payload.source_url,'source_date':payload.source_date,
        'verification_tier':payload.verification_tier,'published':payload.published,
        'availability_claim':'UNVERIFIED_UNLESS_QUOTED','inventory_owned_by_sahjony':False,
        'created_by':actor['id'],'created_at':now(),'updated_at':now(),
    }
    await get_backend().insert('marketplace_products',row)
    return {'product':row}


@app.get('/marketplace/products')
async def products(q: str | None = Query(default=None,max_length=200), category: str | None = Query(default=None,max_length=200), country: str | None = Query(default=None,max_length=3), limit: int = Query(default=50,ge=1,le=200)):
    backend = get_backend()
    rows = await backend.select('marketplace_products',params={'published':'eq.true','order':'updated_at.desc','limit':str(limit)}) or []
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in str(r.get('name','')).lower() or needle in str(r.get('description','')).lower() or needle in str(r.get('category','')).lower()]
    if category:
        rows = [r for r in rows if str(r.get('category','')).lower()==category.lower()]
    if country:
        rows = [r for r in rows if str(r.get('country_of_origin','')).upper()==country.upper()]
    public = []
    for r in rows:
        public.append({k:r.get(k) for k in ['product_id','supplier_id','sku','manufacturer','brand','name','category','description','specifications','hs_code','country_of_origin','moq','unit','price_type','indicative_price','currency','incoterms','lead_time_days','production_capacity','certifications','image_urls','media_rights_status','source_date','verification_tier','updated_at']})
    return {'products':public,'count':len(public),'pricing_notice':'Indicative prices are not executable quotations unless explicitly marked FIXED and still valid.'}


@app.get('/marketplace/products/{product_id}')
async def product_detail(product_id: str):
    rows = await get_backend().select('marketplace_products',params={'product_id':f'eq.{product_id}','published':'eq.true','limit':'1'}) or []
    if not rows:
        raise HTTPException(404,'Product not found')
    r=rows[0]
    return {'product':{k:r.get(k) for k in ['product_id','supplier_id','sku','manufacturer','brand','name','category','description','specifications','hs_code','country_of_origin','moq','unit','price_type','indicative_price','currency','incoterms','lead_time_days','production_capacity','certifications','image_urls','media_rights_status','source_date','verification_tier','updated_at']},'actions':['REQUEST_QUOTE','COMPARE_SUPPLIERS','ASK_SAHJONY_TO_SOURCE','MANAGED_TRADE']}


@app.post('/marketplace/rfqs')
async def create_rfq(payload: RfqIn):
    if '@' not in payload.email:
        raise HTTPException(422,'Valid email required')
    rfq_id=f'rfq_{secrets.token_urlsafe(10)}'
    ts=now()
    row={
        'rfq_id':rfq_id,'product_id':payload.product_id,'buyer_company':payload.buyer_company,
        'contact_name':payload.contact_name,'email':payload.email.strip().lower(),
        'country_code':payload.country_code.upper(),'product_need':payload.product_need,
        'specifications':payload.specifications,'quantity':payload.quantity,'unit':payload.unit,
        'target_budget':payload.target_budget,'currency':payload.currency.upper(),
        'destination_country':payload.destination_country.upper(),'preferred_incoterm':payload.preferred_incoterm,
        'target_delivery_date':payload.target_delivery_date,'managed_trade_requested':payload.managed_trade_requested,
        'source':'WEB','qualification_status':'PENDING','status':'NEW','revenue_priority':'UNRANKED',
        'inventory_owned_by_sahjony':False,'sa hjony_capital_required':False,
        'created_at':ts,'updated_at':ts,
    }
    row['sahjony_capital_required']=False
    await get_backend().insert('marketplace_rfqs',row)
    return {'rfq':row,'next_step':'SAHJONY LLC will qualify the requirement before supplier introductions or commercial commitments.','binding_commitment':False}
