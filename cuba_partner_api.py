from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from physical_postgres import insert_row, select_rows, update_rows

app = FastAPI(title='SAHJONY Cuba Partner Program', version='1.1.0', docs_url=None, redoc_url=None)

PartnerStatus = Literal['APPLIED','UNDER_REVIEW','APPROVED','HOLD','REJECTED','SUSPENDED']
ReferralStatus = Literal['SUBMITTED','QUALIFYING','ACTIVE','CLOSED_WON','CLOSED_LOST','HOLD']
CommissionStatus = Literal['NOT_EARNED','PENDING_REVIEW','APPROVED','PAYMENT_HOLD','PAID','VOID']


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def require_owner(authorization: str | None, x_role: str | None):
    if x_role != 'owner':
        raise HTTPException(403, 'Owner role required')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(authorization.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid owner credential')


class PartnerApplicationIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=254)
    province: str | None = Field(default=None, max_length=120)
    municipality: str | None = Field(default=None, max_length=120)
    preferred_language: Literal['es','en'] = 'es'
    experience: str | None = Field(default=None, max_length=1600)
    network_description: str | None = Field(default=None, max_length=1600)
    payment_method_note: str | None = Field(default=None, max_length=1200)
    accepts_terms: bool
    website: str | None = None


class ReferralIn(BaseModel):
    partner_id: str = Field(min_length=4, max_length=80)
    referral_token: str = Field(min_length=8, max_length=240)
    prospect_name: str = Field(min_length=2, max_length=160)
    prospect_phone: str | None = Field(default=None, max_length=80)
    prospect_email: str | None = Field(default=None, max_length=254)
    opportunity_type: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=3, max_length=2000)
    estimated_value_usd: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1600)


class OwnerPartnerReviewIn(BaseModel):
    status: PartnerStatus
    owner_note: str = Field(min_length=2, max_length=2000)


class OwnerReferralReviewIn(BaseModel):
    referral_status: ReferralStatus
    commission_status: CommissionStatus
    commission_amount_usd: float | None = Field(default=None, ge=0)
    owner_note: str = Field(min_length=2, max_length=2000)


@app.get('/cuba-partners-api/health')
async def health():
    return {
        'status':'ok',
        'service':'sahjony-cuba-partner-program',
        'storage':'physical_neon_postgres',
        'currency':'USD',
        'automatic_commission_payout':False,
        'owner_approval_required':True,
        'partner_sees_business_platform':False,
        'partner_sees_consumer_platform':False,
    }


@app.post('/cuba-partners-api/apply')
async def apply(p: PartnerApplicationIn):
    if p.website:
        raise HTTPException(400, 'Unable to accept application')
    if not p.phone and not p.email:
        raise HTTPException(422, 'Phone or email is required')
    if not p.accepts_terms:
        raise HTTPException(422, 'Program terms must be accepted')
    partner_id = f'cpr_{secrets.token_urlsafe(8)}'
    referral_token = secrets.token_urlsafe(24)
    ts = now()
    row = {
        'partner_id':partner_id,
        'full_name':p.full_name.strip(),
        'phone':p.phone.strip() if p.phone else None,
        'email':p.email.strip().lower() if p.email else None,
        'province':p.province,
        'municipality':p.municipality,
        'preferred_language':p.preferred_language,
        'experience':p.experience,
        'network_description':p.network_description,
        'payment_method_note':p.payment_method_note,
        'status':'APPLIED',
        'referral_token_hash':token_hash(referral_token),
        'automatic_commission_payout':False,
        'created_at':ts,
        'updated_at':ts,
    }
    await insert_row('cuba_partner_accounts', row)
    return {
        'partner_id':partner_id,
        'referral_token':referral_token,
        'status':'APPLIED',
        'currency':'USD',
        'message':'Solicitud recibida. La aprobación del programa y cualquier comisión requieren revisión de SAHJONY.'
    }


@app.post('/cuba-partners-api/referrals')
async def submit_referral(p: ReferralIn):
    partners = await select_rows('cuba_partner_accounts', filters={'partner_id':p.partner_id}, limit=1)
    if not partners:
        raise HTTPException(404, 'Partner not found')
    partner = partners[0]
    if not secrets.compare_digest(str(partner.get('referral_token_hash') or ''), token_hash(p.referral_token)):
        raise HTTPException(404, 'Partner not found')
    if partner.get('status') != 'APPROVED':
        raise HTTPException(409, 'Partner must be approved before submitting referrals')
    if not p.prospect_phone and not p.prospect_email:
        raise HTTPException(422, 'Prospect phone or email is required')
    referral_id = f'ref_{secrets.token_urlsafe(8)}'
    ts = now()
    row = {
        'referral_id':referral_id,
        'partner_id':p.partner_id,
        'prospect_name':p.prospect_name.strip(),
        'prospect_phone':p.prospect_phone.strip() if p.prospect_phone else None,
        'prospect_email':p.prospect_email.strip().lower() if p.prospect_email else None,
        'opportunity_type':p.opportunity_type,
        'description':p.description,
        'estimated_value_usd':p.estimated_value_usd,
        'notes':p.notes,
        'referral_status':'SUBMITTED',
        'commission_status':'NOT_EARNED',
        'commission_amount_usd':None,
        'currency':'USD',
        'created_at':ts,
        'updated_at':ts,
    }
    await insert_row('cuba_partner_referrals', row)
    return {'referral_id':referral_id,'status':'SUBMITTED','commission_status':'NOT_EARNED','currency':'USD'}


@app.get('/cuba-partners-api/status/{partner_id}')
async def partner_status(partner_id: str, x_partner_token: str | None = Header(None, alias='X-Partner-Token')):
    if not x_partner_token:
        raise HTTPException(401, 'Partner token required')
    rows = await select_rows('cuba_partner_accounts', filters={'partner_id':partner_id}, limit=1)
    if not rows or not secrets.compare_digest(str(rows[0].get('referral_token_hash') or ''), token_hash(x_partner_token)):
        raise HTTPException(404, 'Partner not found')
    referrals = await select_rows('cuba_partner_referrals', filters={'partner_id':partner_id}, order_by='created_at', descending=True, limit=100)
    safe_referrals=[]
    for r in referrals:
        safe_referrals.append({
            'referral_id':r.get('referral_id'),
            'opportunity_type':r.get('opportunity_type'),
            'referral_status':r.get('referral_status'),
            'commission_status':r.get('commission_status'),
            'commission_amount_usd':r.get('commission_amount_usd'),
            'currency':'USD',
            'updated_at':r.get('updated_at'),
        })
    return {'partner_id':partner_id,'status':rows[0].get('status'),'currency':'USD','referrals':safe_referrals}


@app.get('/cuba-partners-api/owner/partners')
async def owner_partners(authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    rows = await select_rows('cuba_partner_accounts', order_by='created_at', descending=True, limit=300)
    for r in rows:
        r.pop('referral_token_hash', None)
    return {'partners':rows}


@app.patch('/cuba-partners-api/owner/partners/{partner_id}')
async def owner_review_partner(partner_id: str, p: OwnerPartnerReviewIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    updated = await update_rows('cuba_partner_accounts', {'status':p.status,'owner_note':p.owner_note,'updated_at':now()}, filters={'partner_id':partner_id})
    if not updated:
        raise HTTPException(404, 'Partner not found')
    return {'partner_id':partner_id,'status':p.status}


@app.get('/cuba-partners-api/owner/referrals')
async def owner_referrals(authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    rows = await select_rows('cuba_partner_referrals', order_by='created_at', descending=True, limit=500)
    return {'referrals':rows}


@app.patch('/cuba-partners-api/owner/referrals/{referral_id}')
async def owner_review_referral(referral_id: str, p: OwnerReferralReviewIn, authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    if p.commission_status in {'APPROVED','PAID'} and p.referral_status != 'CLOSED_WON':
        raise HTTPException(409, 'Commission cannot be approved before a closed-won referral')
    if p.commission_status == 'PAID':
        raise HTTPException(409, 'Commission payout must be recorded through the governed payment workflow')
    patch = {
        'referral_status':p.referral_status,
        'commission_status':p.commission_status,
        'commission_amount_usd':p.commission_amount_usd,
        'owner_note':p.owner_note,
        'updated_at':now(),
    }
    updated = await update_rows('cuba_partner_referrals', patch, filters={'referral_id':referral_id})
    if not updated:
        raise HTTPException(404, 'Referral not found')
    return {'referral_id':referral_id,'referral_status':p.referral_status,'commission_status':p.commission_status,'currency':'USD'}
