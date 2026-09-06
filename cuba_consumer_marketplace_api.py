from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Cuba Consumer Marketplace', version='1.2.0', docs_url=None, redoc_url=None)

Category = Literal['ENERGY_FUELS','SOLAR_BACKUP','HOME_APPLIANCES','HOUSEHOLD_GOODS','ELECTRONICS_COMMUNICATIONS','FOOD_AGRICULTURE','HEALTH_MEDICAL','OTHER']
Status = Literal['RECEIVED','ELIGIBILITY_REVIEW','SOURCING','QUOTE_REVIEW','COMPLIANCE_REVIEW','PAYMENT_REVIEW','LOGISTICS_REVIEW','READY_FOR_CUSTOMER_DECISION','HOLD','CLOSED']
Currency = Literal['USD']
ShippingOption = Literal['SAHJONY_ARRANGED','CUSTOMER_ARRANGED','CONSOLIDATED']
TransportMode = Literal['SEA','AIR','BEST_AVAILABLE']


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
    budget_currency: Currency = 'USD'
    notes: str | None = Field(default=None, max_length=2000)
    shipping_option: ShippingOption = 'SAHJONY_ARRANGED'
    transport_mode: TransportMode = 'SEA'
    customer_pays_shipping: bool = True
    consolidation_ok: bool = True
    website: str | None = None




def request_notes(p: ConsumerRequestIn) -> str:
    parts = [
        p.notes.strip() if p.notes else '',
        'ORDER_MODE=INDIVIDUAL',
        f'SHIPPING_OPTION={p.shipping_option}',
        f'TRANSPORT_MODE={p.transport_mode}',
        'AIR_DG_REVIEW_REQUIRED=TRUE' if p.transport_mode in {'AIR','BEST_AVAILABLE'} else 'AIR_DG_REVIEW_REQUIRED=FALSE',
        'SHIPPING_PAYER=CUSTOMER',
        f'CONSOLIDATION_OK={str(bool(p.consolidation_ok)).upper()}',
        'SHIPPING_QUOTED_SEPARATELY=TRUE',
    ]
    return '\n'.join(x for x in parts if x)[:2000]

class OwnerReviewIn(BaseModel):
    status: Status
    owner_note: str = Field(min_length=2, max_length=2000)
    eligibility_route: Literal['SCP_CANDIDATE','CCD_CANDIDATE','AGR_CANDIDATE','BIS_LICENSE_REVIEW','OTHER_REVIEW','NOT_YET_CLASSIFIED','INELIGIBLE'] = 'NOT_YET_CLASSIFIED'
    quote_amount: float | None = Field(default=None, ge=0)
    quote_currency: Currency = 'USD'
    customer_message: str | None = Field(default=None, max_length=2000)


@app.get('/consumer-marketplace/health')
async def health():
    return {
        'status':'ok',
        'service':'sahjony-cuba-consumer-marketplace',
        'version':'1.2.0',
        'audience':'INDIVIDUAL_CONSUMER_ONLY',
        'transaction_currency':'USD',
        'public_intake':True,
        'public_status_requires_secret_token':True,
        'automatic_legal_clearance':False,
        'automatic_payment_authority':False,
        'automatic_shipment_release':False,
        'default_status':'RECEIVED',
        'individual_orders_enabled':True, 'air_shipping_enabled':True, 'sea_shipping_enabled':True,
        'customer_paid_shipping_enabled':True,
        'shipping_quote_separate':True,
        'shipping_options':['SAHJONY_ARRANGED','CUSTOMER_ARRANGED','CONSOLIDATED'],
        'inventory_purchase_before_customer_funds':False,
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
    if not p.customer_pays_shipping:
        raise HTTPException(409, 'Individual orders require the customer to accept the shipping cost separately from the product price.')

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
        'budget_currency':'USD',
        'notes':request_notes(p),
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
        'currency':'USD',
        'order_mode':'INDIVIDUAL',
        'shipping_option':p.shipping_option,
        'transport_mode':p.transport_mode,
        'customer_pays_shipping':True,
        'shipping_quote_separate':True,
        'consolidation_ok':bool(p.consolidation_ok),
        'message':'Solicitud recibida. El producto y el envío se cotizan por separado en USD; el cliente acepta el costo del transporte antes de la compra.'
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
        'quote_currency':'USD',
        'customer_message':r.get('customer_message'),
        'updated_at':r.get('updated_at'),
        'payment_allowed':bool(r.get('payment_allowed')),
        'shipment_allowed':bool(r.get('shipment_allowed')),
        'order_mode':'INDIVIDUAL',
        'customer_pays_shipping':True,
        'shipping_quote_separate':True,
    }


@app.get('/consumer-marketplace/owner/requests')
async def list_owner_requests(authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    owner(authorization, x_role)
    rows = await get_backend().select('cuba_consumer_marketplace_requests', params={'order':'created_at.desc','limit':'300'}) or []
    for r in rows:
        r.pop('status_token_hash', None)
        r['budget_currency'] = 'USD'
        if r.get('quote_amount') is not None:
            r['quote_currency'] = 'USD'
    return {'requests':rows, 'transaction_currency':'USD', 'order_mode':'INDIVIDUAL', 'customer_pays_shipping':True, 'shipping_quote_separate':True}


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
        'quote_currency':'USD',
        'customer_message':p.customer_message,
        'release_allowed':False,
        'payment_allowed':False,
        'shipment_allowed':False,
        'updated_at':ts,
    }
    await get_backend().patch('cuba_consumer_marketplace_requests', patch, params={'request_id':f'eq.{request_id}'})
    return {'request_id':request_id, 'status':p.status, 'eligibility_route':p.eligibility_route, 'quote_currency':'USD', 'payment_allowed':False, 'shipment_allowed':False}
