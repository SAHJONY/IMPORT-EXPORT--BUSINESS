from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from payment_engine import PaymentError, payment_plan, policy_snapshot, reconcile
from physical_postgres import insert_row, select_rows, update_rows

app = FastAPI(title='SAHJONY Owner Payment Control API', version='1.1.0', docs_url=None, redoc_url=None)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_owner(authorization: str | None, x_role: str | None):
    if x_role != 'owner':
        raise HTTPException(403, 'Owner role required')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(authorization.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid owner credential')


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
        'currency':'USD',
        'automatic_supplier_payout':False,
        'automatic_shipment_release':False,
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
    return {'payment_case_id':case_id, **plan}


@app.get('/owner-payments/cases')
async def list_cases(authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    rows = await select_rows('trade_payment_ledger', order_by='created_at', descending=True, limit=300)
    return {'cases':rows}


@app.post('/owner-payments/cases/{case_id}/confirm-funds')
async def confirm_funds(case_id: str, p: FundsIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    rows = await select_rows('trade_payment_ledger', filters={'payment_case_id':case_id}, limit=1)
    if not rows:
        raise HTTPException(404, 'Payment case not found')
    r = rows[0]
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
    return {'payment_case_id':case_id,'currency':'USD','customer_paid':paid,'outstanding_balance':max(total-paid,0),'status':status,'supplier_payout_allowed':False,'shipment_release_allowed':False}


@app.post('/owner-payments/cases/{case_id}/authorize-release')
async def authorize_release(case_id: str, p: ReleaseIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    rows = await select_rows('trade_payment_ledger', filters={'payment_case_id':case_id}, limit=1)
    if not rows:
        raise HTTPException(404, 'Payment case not found')
    r = rows[0]
    if not p.compliance_still_cleared or not r.get('compliance_cleared'):
        raise HTTPException(409, 'Compliance clearance is required for release')
    if not p.customer_funds_confirmed or float(r.get('outstanding_balance') or 0) > 0:
        raise HTTPException(409, 'Full customer funds confirmation is required for release')
    await update_rows('trade_payment_ledger', {
        'supplier_payout_allowed':True,
        'shipment_release_allowed':True,
        'release_authorized_at':now(),
        'release_owner_note':p.owner_note,
        'updated_at':now(),
    }, filters={'payment_case_id':case_id})
    return {'payment_case_id':case_id,'currency':'USD','supplier_payout_allowed':True,'shipment_release_allowed':True,'owner_authorized':True}


@app.post('/owner-payments/reconcile')
async def reconciliation(payload: dict, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    payload['currency'] = 'USD'
    try:
        return reconcile(**payload)
    except (PaymentError, TypeError) as exc:
        raise HTTPException(409, str(exc)) from exc
