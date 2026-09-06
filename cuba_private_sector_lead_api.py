from __future__ import annotations

import os, secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Cuba Private Sector Acquisition', version='1.1.0', docs_url=None, redoc_url=None)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def employee_token() -> str:
    token = os.getenv('EMPLOYEE_TOKEN', '').strip()
    if not token:
        raise HTTPException(503, 'Employee access not configured')
    return token


def internal_identity(role: str | None, authorization: str | None, employee_id: str | None):
    if role not in {'owner', 'employee'}:
        raise HTTPException(400, 'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    token = authorization.removeprefix('Bearer ').strip()
    if role == 'owner':
        if not verify_owner_token(token):
            raise HTTPException(403, 'Invalid owner credential')
        return {'role': 'owner', 'id': 'owner'}
    if not secrets.compare_digest(token, employee_token()):
        raise HTTPException(403, 'Invalid employee credential')
    return {'role': 'employee', 'id': (employee_id or 'staff')[:160]}


ShippingOption = Literal['SAHJONY_ARRANGED','CUSTOMER_ARRANGED','CONSOLIDATED']
OrderMode = Literal['SMALL_ORDER','LCL_CONSOLIDATED','FCL']


class PublicLeadIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=240)
    contact_name: str = Field(min_length=2, max_length=160)
    contact_method: Literal['EMAIL', 'WHATSAPP', 'PHONE', 'OTHER']
    email: str | None = Field(default=None, max_length=254)
    phone_whatsapp: str | None = Field(default=None, max_length=80)
    province: str | None = Field(default=None, max_length=120)
    municipality: str | None = Field(default=None, max_length=120)
    employee_count: int | None = Field(default=None, ge=0, le=10000)
    business_activity: str | None = Field(default=None, max_length=500)
    product_need: str = Field(min_length=3, max_length=1200)
    specifications: str | None = Field(default=None, max_length=4000)
    quantity: float | None = Field(default=None, gt=0)
    target_budget: float | None = Field(default=None, gt=0)
    currency: str = Field(default='USD', min_length=3, max_length=3)
    target_delivery_date: str | None = Field(default=None, max_length=40)
    preferred_origin_countries: list[str] = Field(default_factory=list, max_length=20)
    accepts_global_sourcing: bool = True
    payment_preference: str | None = Field(default=None, max_length=240)
    order_mode: OrderMode = 'SMALL_ORDER'
    shipping_option: ShippingOption = 'SAHJONY_ARRANGED'
    customer_pays_shipping: bool = True
    consolidation_ok: bool = True
    notes: str | None = Field(default=None, max_length=3000)
    consent_to_business_contact: bool
    website: str | None = Field(default=None, max_length=1)

    @model_validator(mode='after')
    def validate_contact(self):
        if not self.consent_to_business_contact:
            raise ValueError('Business-contact consent is required')
        if self.website:
            raise ValueError('Invalid submission')
        if self.contact_method == 'EMAIL':
            if not self.email or '@' not in self.email or self.email.startswith('@') or self.email.endswith('@'):
                raise ValueError('A valid email is required for EMAIL contact method')
        if self.contact_method in {'WHATSAPP', 'PHONE'} and not self.phone_whatsapp:
            raise ValueError('Phone/WhatsApp is required for this contact method')
        self.currency = self.currency.upper()
        self.preferred_origin_countries = [x.strip().upper()[:2] for x in self.preferred_origin_countries if x.strip()]
        if not self.customer_pays_shipping:
            raise ValueError('Private-business orders require customer acceptance of separately quoted shipping costs')
        return self


class PromoteIn(BaseModel):
    private_business_id: str | None = None
    assigned_employee_id: str | None = None


@app.get('/cuba-private-sector/health')
async def health():
    return {'status': 'ok', 'service': 'cuba-private-sector-acquisition', 'version':'1.1.0', 'public_intake': True, 'small_orders_enabled':True, 'lcl_consolidation_enabled':True, 'fcl_enabled':True, 'customer_paid_shipping_enabled':True, 'shipping_quote_separate':True, 'default_business_readiness':'BUSINESS_REVIEW_REQUIRED', 'auto_authorization': False, 'auto_eligibility': False, 'fail_closed': True}


@app.post('/cuba-private-sector/leads')
async def create_public_lead(payload: PublicLeadIn):
    lead_id = f'cpsl_{secrets.token_urlsafe(10)}'
    ts = now()
    row = payload.model_dump(exclude={'website','order_mode','shipping_option','customer_pays_shipping','consolidation_ok'})
    logistics_note = '\n'.join([
        (payload.notes or '').strip(),
        f'ORDER_MODE={payload.order_mode}',
        f'SHIPPING_OPTION={payload.shipping_option}',
        'SHIPPING_PAYER=CUSTOMER',
        'SHIPPING_QUOTED_SEPARATELY=TRUE',
        f'CONSOLIDATION_OK={str(bool(payload.consolidation_ok)).upper()}',
        'BUSINESS_READINESS=BUSINESS_REVIEW_REQUIRED',
    ]).strip()[:3000]
    row['notes'] = logistics_note
    row.update({'lead_id': lead_id, 'source': 'CUBA_PRIVATE_SECTOR_PORTAL', 'status': 'NEW', 'compliance_status': 'NOT_REVIEWED', 'managed_request_id': None, 'assigned_employee_id': None, 'submitted_at': ts, 'updated_at': ts})
    try:
        await get_backend().insert('cuba_private_sector_leads', row)
    except Exception as exc:
        raise HTTPException(503, 'Lead intake is not available until the production schema is applied') from exc
    return {'lead_id': lead_id, 'status': 'NEW', 'business_readiness':'BUSINESS_REVIEW_REQUIRED', 'order_mode':payload.order_mode, 'shipping_option':payload.shipping_option, 'customer_pays_shipping':True, 'shipping_quote_separate':True, 'message': 'Solicitud recibida. SAHJONY revisará la empresa, el producto, la ruta de pago y los requisitos aplicables antes de presentar opciones de suministro.', 'important': 'El envío o la compra no quedan autorizados por esta solicitud. Cada operación requiere revisión específica.'}


@app.get('/cuba-private-sector/leads')
async def list_leads(x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = internal_identity(x_role, authorization, x_employee_id)
    params = {'order': 'submitted_at.desc', 'limit': '250'}
    if actor['role'] == 'employee':
        params['assigned_employee_id'] = f'eq.{actor["id"]}'
    return {'leads': await get_backend().select('cuba_private_sector_leads', params=params) or []}


@app.post('/cuba-private-sector/leads/{lead_id}/promote')
async def promote_lead(lead_id: str, payload: PromoteIn, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = internal_identity(x_role, authorization, x_employee_id)
    rows = await get_backend().select('cuba_private_sector_leads', params={'lead_id': f'eq.{lead_id}', 'limit': '1'}) or []
    if not rows:
        raise HTTPException(404, 'Lead not found')
    lead = rows[0]
    if lead.get('managed_request_id'):
        return {'lead_id': lead_id, 'managed_request_id': lead['managed_request_id'], 'status': lead.get('status')}
    assigned = payload.assigned_employee_id or (actor['id'] if actor['role'] == 'employee' else None)
    request_id = f'mtr_{secrets.token_urlsafe(10)}'
    ts = now()
    managed = {'request_id': request_id, 'requester_type': 'PRIVATE_BUSINESS', 'requester_ref': lead_id, 'private_business_id': payload.private_business_id, 'employee_id': assigned, 'product_need': lead.get('product_need'), 'specifications': lead.get('specifications'), 'quantity': lead.get('quantity'), 'target_budget': lead.get('target_budget'), 'currency': lead.get('currency') or 'USD', 'destination_country': 'CU', 'target_delivery_date': lead.get('target_delivery_date'), 'status': 'INTAKE', 'assigned_owner_id': 'owner', 'assigned_employee_id': assigned, 'created_at': ts, 'updated_at': ts}
    await get_backend().insert('managed_trade_requests', managed)
    await get_backend().patch('cuba_private_sector_leads', {'status': 'KYB_REQUIRED', 'managed_request_id': request_id, 'assigned_employee_id': assigned, 'updated_at': ts}, params={'lead_id': f'eq.{lead_id}'})
    return {'lead_id': lead_id, 'managed_request_id': request_id, 'status': 'KYB_REQUIRED', 'next_step': 'Verify Cuban private-sector eligibility and transaction-specific product/payment authorization before supplier commitment.'}
