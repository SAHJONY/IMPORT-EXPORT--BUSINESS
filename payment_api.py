from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from payment_engine import PaymentError, payment_plan, policy_snapshot, reconcile
from physical_postgres import insert_row, select_rows, update_rows

app = FastAPI(title='SAHJONY Owner Payment Control API', version='1.2.0', docs_url=None, redoc_url=None)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_owner(authorization: str | None, x_role: str | None):
    if x_role != 'owner':
        raise HTTPException(403, 'Owner role required')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(authorization.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid owner credential')


async def append_event(case_id: str, event_type: str, *, amount: float | None = None, external_reference: str | None = None, owner_note: str | None = None):
    return await insert_row('trade_payment_events', {
        'event_id':f'pev_{secrets.token_urlsafe(10)}',
        'payment_case_id':case_id,
        'event_type':event_type,
        'amount':amount,
        'currency':'USD',
        'external_reference':external_reference,
        'owner_note':owner_note,
        'created_at':now(),
    })


async def get_case(case_id: str) -> dict:
    rows = await select_rows('trade_payment_ledger', filters={'payment_case_id':case_id}, limit=1)
    if not rows:
        raise HTTPException(404, 'Payment case not found')
    return rows[0]


class PaymentCaseIn(BaseModel):
    audience: Literal['INDIVIDUAL_CONSUMER','BUSINESS_CUSTOMER']
    customer_reference: str = Field(min_length=2, max_length=160)
    source_reference: str | None = Field(default=None, max_length=160)
    total_amount: float = Field(gt=0)
    deposit_amount: float = Field(default=0, ge=0)
    currency: Literal['USD'] = 'USD'
    quote_approved: bool = False
    compliance_cleared: bool = False
    payment_rail: Literal['ACH','BANK_WIRE','CARD_PROCESSOR','OTHER_APPROVED_USD_RAIL'] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class FundsIn(BaseModel):
    amount: float = Field(gt=0)
    currency: Literal['USD'] = 'USD'
    external_reference: str = Field(min_length=2, max_length=240)
    notes: str | None = Field(default=None, max_length=1200)


class ReleaseIn(BaseModel):
    owner_note: str = Field(min_length=2, max_length=2000)
    compliance_still_cleared: bool
    customer_funds_confirmed: bool


@app.get('/owner-payments/health')
async def health():
    return {
        'status':'ok',
        'service':'sahjony-owner-payment-control',
        'storage':'physical_neon_postgres',
        'audit_events':'append_only',
        'currency':'USD',
        'automatic_supplier_payout':False,
        'automatic_shipment_release':False,
        'supplier_and_shipment_release_separated':True,
        'owner_release_required':True,
    }


@app.get('/owner-payments/policies')
async def policies(authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    return policy_snapshot()


@app.post('/owner-payments/cases')
async def create_case(p: PaymentCaseIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    try:
        plan = payment_plan(**p.model_dump(exclude={'customer_reference','source_reference','payment_rail','notes'}))
    except PaymentError as exc:
        raise HTTPException(409, str(exc)) from exc
    case_id = f'pay_{secrets.token_urlsafe(9)}'
    ts = now()
    row = {
        'payment_case_id':case_id,
        'audience':p.audience,
        'customer_reference':p.customer_reference,
        'source_reference':p.source_reference,
        'currency':'USD',
        'total_amount':p.total_amount,
        'deposit_amount':p.deposit_amount,
        'customer_paid':0,
        'outstanding_balance':p.total_amount,
        'payment_status':plan['status'],
        'payment_rail':p.payment_rail,
        'quote_approved':p.quote_approved,
        'compliance_cleared':p.compliance_cleared,
        'payment_allowed':plan['payment_allowed'],
        'supplier_payout_allowed':False,
        'shipment_release_allowed':False,
        'owner_note':p.notes,
        'created_at':ts,
        'updated_at':ts,
    }
    await insert_row('trade_payment_ledger', row)
    await append_event(case_id, 'CASE_CREATED', amount=p.total_amount, owner_note=p.notes)
    return {'payment_case_id':case_id, **plan}


@app.get('/owner-payments/cases')
async def list_cases(authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    rows = await select_rows('trade_payment_ledger', order_by='created_at', descending=True, limit=300)
    return {'cases':rows}


@app.get('/owner-payments/cases/{case_id}/events')
async def list_case_events(case_id: str, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    await get_case(case_id)
    rows = await select_rows('trade_payment_events', filters={'payment_case_id':case_id}, order_by='created_at', descending=True, limit=500)
    return {'payment_case_id':case_id,'events':rows}


@app.post('/owner-payments/cases/{case_id}/confirm-funds')
async def confirm_funds(case_id: str, p: FundsIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    r = await get_case(case_id)
    if not r.get('payment_allowed'):
        raise HTTPException(409, 'Payment cannot be confirmed before quote and compliance clearance')
    paid = float(r.get('customer_paid') or 0) + p.amount
    total = float(r.get('total_amount') or 0)
    if paid > total:
        raise HTTPException(409, 'Confirmed customer funds exceed case total')
    status = 'PAID' if paid >= total else 'PARTIALLY_PAID'
    await update_rows('trade_payment_ledger', {
        'customer_paid':paid,
        'outstanding_balance':max(total-paid,0),
        'payment_status':status,
        'funds_external_reference':p.external_reference,
        'funds_note':p.notes,
        'supplier_payout_allowed':False,
        'shipment_release_allowed':False,
        'updated_at':now(),
    }, filters={'payment_case_id':case_id})
    await append_event(case_id, 'FUNDS_CONFIRMED', amount=p.amount, external_reference=p.external_reference, owner_note=p.notes)
    return {'payment_case_id':case_id,'currency':'USD','customer_paid':paid,'outstanding_balance':max(total-paid,0),'status':status,'supplier_payout_allowed':False,'shipment_release_allowed':False}


def validate_release(r: dict, p: ReleaseIn):
    if not p.compliance_still_cleared or not r.get('compliance_cleared'):
        raise HTTPException(409, 'Compliance clearance is required for release')
    if not p.customer_funds_confirmed or float(r.get('outstanding_balance') or 0) > 0:
        raise HTTPException(409, 'Full customer funds confirmation is required for release')


@app.post('/owner-payments/cases/{case_id}/authorize-supplier-payout')
async def authorize_supplier_payout(case_id: str, p: ReleaseIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    r = await get_case(case_id)
    validate_release(r, p)
    ts = now()
    await update_rows('trade_payment_ledger', {
        'supplier_payout_allowed':True,
        'supplier_payout_authorized_at':ts,
        'supplier_payout_owner_note':p.owner_note,
        'updated_at':ts,
    }, filters={'payment_case_id':case_id})
    await append_event(case_id, 'SUPPLIER_PAYOUT_AUTHORIZED', owner_note=p.owner_note)
    return {'payment_case_id':case_id,'currency':'USD','supplier_payout_allowed':True,'shipment_release_allowed':bool(r.get('shipment_release_allowed')),'owner_authorized':True}


@app.post('/owner-payments/cases/{case_id}/authorize-shipment-release')
async def authorize_shipment_release(case_id: str, p: ReleaseIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    r = await get_case(case_id)
    validate_release(r, p)
    ts = now()
    await update_rows('trade_payment_ledger', {
        'shipment_release_allowed':True,
        'shipment_release_authorized_at':ts,
        'shipment_release_owner_note':p.owner_note,
        'updated_at':ts,
    }, filters={'payment_case_id':case_id})
    await append_event(case_id, 'SHIPMENT_RELEASE_AUTHORIZED', owner_note=p.owner_note)
    return {'payment_case_id':case_id,'currency':'USD','supplier_payout_allowed':bool(r.get('supplier_payout_allowed')),'shipment_release_allowed':True,'owner_authorized':True}


@app.post('/owner-payments/cases/{case_id}/authorize-release')
async def deprecated_combined_release(case_id: str, p: ReleaseIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    raise HTTPException(409, 'Combined release is disabled. Authorize supplier payout and shipment release separately.')


@app.post('/owner-payments/reconcile')
async def reconciliation(payload: dict, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    payload['currency'] = 'USD'
    try:
        result = reconcile(**payload)
    except (PaymentError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return result
