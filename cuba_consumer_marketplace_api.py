from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Cuba Consumer Marketplace', version='1.0.1', docs_url=None, redoc_url=None)

Category = Literal['ENERGY_FUELS','SOLAR_BACKUP','HOME_APPLIANCES','HOUSEHOLD_GOODS','ELECTRONICS_COMMUNICATIONS','FOOD_AGRICULTURE','HEALTH_MEDICAL','OTHER']
Status = Literal['RECEIVED','ELIGIBILITY_REVIEW','SOURCING','QUOTE_REVIEW','COMPLIANCE_REVIEW','PAYMENT_REVIEW','LOGISTICS_REVIEW','READY_FOR_CUSTOMER_DECISION','HOLD','CLOSED']


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def owner(authorization: str | None, x_role: str | None):
    if x_role != 'owner':
        raise HTTPException(403, 'Owner role required')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(authorization.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid owner credential')


class ConsumerRequestIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=254)
    preferred_language: Literal['es','en'] = 'es'
    province: str | None = Field(default=None, max_length=120)
    municipality: str | None = Field(default=None, max_length=120)
    delivery_address: str | None = Field(default=None, max_length=500)
    category: Category
    product_description: str = Field(min_length=3, max_length=1200)
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, max_length=40)
    intended_use: str = Field(min_length=3, max_length=1200)
    personal_or_family_use: bool = True
    budget_amount: float | None = Field(default=None, ge=0)
    budget_currency: str = Field(default='USD', min_length=3, max_length=3)
    notes: str | None = Field(default=None, max_length=2000)
    website: str | None = None


class OwnerReviewIn(BaseModel):
    status: Status
    owner_note: str = Field(min_length=2, max_length=2000)
    eligibility_route: Literal['SCP_CANDIDATE','CCD_CANDIDATE','AGR_CANDIDATE','BIS_LICENSE_REVIEW','OTHER_REVIEW','NOT_YET_CLASSIFIED','INELIGIBLE'] = 'NOT_YET_CLASSIFIED'
    quote_amount: float | None = Field(default=None, ge=0)
    quote_currency: str = Field(default='USD', min_length=3, max_length=3)
    customer_message: str | None = Field(default=None, max_length=2000)


@app.get('/consumer-marketplace/health')
async def health():
    return {
        'status':'ok',
        'service':'sahjony-cuba-consumer-marketplace',
        'version':'1.0.1',
        'audience':'INDIVIDUAL_CONSUMER_ONLY',
        'public_intake':True,
        'public_status_requires_secret_token':True,
        'automatic_legal_clearance':False,
        'automatic_payment_authority':False,
        'automatic_shipment_release':False,
        'default_status':'RECEIVED',
        'fail_closed':True,
    }


@app.post('/consumer-marketplace/requests')
async def create_request(p: ConsumerRequestIn):
    if p.website:
        raise HTTPException(400, 'Unable to accept request')
    if not p.phone and not p.email:
        raise HTTPException(422, 'Phone or email is required')
    if not p.personal_or_family_use:
        raise HTTPException(409, 'This platform accepts only personal or immediate-family use requests.')

    rid = f'cir_{secrets.token_urlsafe(9)}'
    status_token = secrets.token_urlsafe(24)
    ts = now()
    row = {
        'request_id':rid,
        'request_type':'INDIVIDUAL_CONSUMER',
        'country':'CU',
        'full_name':p.full_name.strip(),
        'phone':p.phone.strip() if p.phone else None,
        'email':p.email.strip().lower() if p.email else None,
        'preferred_language':p.preferred_language,
        'province':p.province,
        'municipality':p.municipality,
        'delivery_address':p.delivery_address,
        'category':p.category,
        'product_description':p.product_description,
        'quantity':p.quantity,
        'unit':p.unit,
        'intended_use':p.intended_use,
        'personal_or_family_use':True,
        'budget_amount':p.budget_amount,
        'budget_currency':p.budget_currency.upper(),
        'notes':p.notes,
        'status':'RECEIVED',
        'eligibility_route':'NOT_YET_CLASSIFIED',
        'release_allowed':False,
        'payment_allowed':False,
        'shipment_allowed':False,
        'status_token_hash':token_hash(status_token),
        'created_at':ts,
        'updated_at':ts,
    }
    await get_backend().insert('cuba_consumer_marketplace_requests', row)
    return {
        'request_id':rid,
        'status_token':status_token,
        'status':'RECEIVED',
        'message':'Solicitud recibida. SAHJONY revisará elegibilidad, abastecimiento, precio, cumplimiento, pago y logística antes de cualquier venta o envío.'
    }


@app.get('/consumer-marketplace/requests/{request_id}/status')
async def public_status(request_id: str, x_request_token: str | None = Header(None, alias='X-Request-Token')):
    if not x_request_token:
        raise HTTPException(401, 'Request status token required')
    rows = await get_backend().select('cuba_consumer_marketplace_requests', params={'request_id':f'eq.{request_id}','limit':'1'}) or []
    if not rows or not secrets.compare_digest(str(rows[0].get('status_token_hash') or ''), token_hash(x_request_token)):
        raise HTTPException(404, 'Request not found')
    r = rows[0]
    return {
        'request_id':r.get('request_id'),
        'status':r.get('status'),
        'category':r.get('category'),
        'product_description':r.get('product_description'),
        'eligibility_route':r.get('eligibility_route'),
        'quote_amount':r.get('quote_amount'),
        'quote_currency':r.get('quote_currency'),
        'customer_message':r.get('customer_message'),
        'updated_at':r.get('updated_at'),
        'payment_allowed':bool(r.get('payment_allowed')),
        'shipment_allowed':bool(r.get('shipment_allowed')),
    }


@app.get('/consumer-marketplace/owner/requests')
async def list_owner_requests(authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    owner(authorization, x_role)
    rows = await get_backend().select('cuba_consumer_marketplace_requests', params={'order':'created_at.desc','limit':'300'}) or []
    for r in rows:
        r.pop('status_token_hash', None)
    return {'requests':rows}


@app.patch('/consumer-marketplace/owner/requests/{request_id}')
async def review_request(request_id: str, p: OwnerReviewIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    owner(authorization, x_role)
    rows = await get_backend().select('cuba_consumer_marketplace_requests', params={'request_id':f'eq.{request_id}','limit':'1'}) or []
    if not rows:
        raise HTTPException(404, 'Request not found')
    if p.status == 'READY_FOR_CUSTOMER_DECISION' and p.eligibility_route in {'NOT_YET_CLASSIFIED','INELIGIBLE'}:
        raise HTTPException(409, 'A classified eligibility route is required before customer decision status')
    ts = now()
    patch = {
        'status':p.status,
        'owner_note':p.owner_note,
        'eligibility_route':p.eligibility_route,
        'quote_amount':p.quote_amount,
        'quote_currency':p.quote_currency.upper(),
        'customer_message':p.customer_message,
        'release_allowed':False,
        'payment_allowed':False,
        'shipment_allowed':False,
        'updated_at':ts,
    }
    await get_backend().patch('cuba_consumer_marketplace_requests', patch, params={'request_id':f'eq.{request_id}'})
    return {'request_id':request_id, 'status':p.status, 'eligibility_route':p.eligibility_route, 'payment_allowed':False, 'shipment_allowed':False}
