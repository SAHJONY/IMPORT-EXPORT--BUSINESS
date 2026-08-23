from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Lead Scout Intake', version='1.0.0', docs_url=None, redoc_url=None)

DealSide = Literal['BUYER','SELLER','BOTH','REFERRAL','OTHER']
LeadType = Literal['IMPORT_NEED','EXPORT_OFFER','SUPPLIER','BUYER','DISTRIBUTOR','PARTNER','OTHER']
PUBLIC_WINDOW: dict[str, list[float]] = {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(value: str | None) -> str:
    return ' '.join((value or '').strip().lower().split())


def enforce_public_limit(request: Request) -> None:
    ip = request.client.host if request.client else 'unknown'
    ts = time.time()
    window = PUBLIC_WINDOW.setdefault(ip, [])
    window[:] = [x for x in window if ts - x < 60]
    if len(window) >= 12:
        raise HTTPException(429, 'Too many lead submissions. Please try again shortly.')
    window.append(ts)


class LeadScoutIn(BaseModel):
    scout_name: str = Field(min_length=2, max_length=160)
    scout_code: str | None = Field(default=None, max_length=80)
    scout_contact: str | None = Field(default=None, max_length=240)
    business_name: str = Field(min_length=2, max_length=240)
    contact_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=80)
    country: str = Field(min_length=2, max_length=80)
    city_region: str | None = Field(default=None, max_length=160)
    deal_side: DealSide = 'OTHER'
    lead_type: LeadType = 'OTHER'
    product_need_or_offer: str = Field(min_length=3, max_length=1800)
    estimated_deal_value: float | None = Field(default=None, ge=0)
    currency: str = Field(default='USD', min_length=3, max_length=3)
    source_url: str | None = Field(default=None, max_length=1200)
    source_description: str | None = Field(default=None, max_length=600)
    evidence_urls: list[str] = Field(default_factory=list, max_length=8)
    notes: str | None = Field(default=None, max_length=2000)
    consent_to_business_contact: bool = False

    @field_validator('email')
    @classmethod
    def email_format(cls, value: str | None):
        if not value:
            return None
        v = value.strip().lower()
        if '@' not in v or v.startswith('@') or v.endswith('@'):
            raise ValueError('Valid email required')
        return v

    @field_validator('currency')
    @classmethod
    def currency_upper(cls, value: str):
        return value.strip().upper()


def opportunity_score(p: LeadScoutIn) -> int:
    score = 20
    if p.email or p.phone: score += 15
    if p.contact_name: score += 8
    if p.source_url: score += 12
    if p.evidence_urls: score += min(10, len(p.evidence_urls) * 3)
    if p.estimated_deal_value and p.estimated_deal_value >= 10000: score += 12
    elif p.estimated_deal_value: score += 6
    if p.lead_type != 'OTHER': score += 8
    if p.deal_side != 'OTHER': score += 5
    if len(p.product_need_or_offer.strip()) >= 40: score += 8
    if p.country.strip(): score += 2
    return min(score, 100)


def priority(score: int) -> str:
    if score >= 75: return 'HIGH'
    if score >= 55: return 'MEDIUM'
    return 'STANDARD'


def fingerprint(p: LeadScoutIn) -> str:
    basis = '|'.join([
        normalize(p.business_name), normalize(p.email), normalize(p.phone), normalize(p.source_url), normalize(p.country)
    ])
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


@app.get('/lead-scout/health')
async def health():
    return {
        'status': 'ok',
        'service': 'lead-scout-intake',
        'public_submission': True,
        'public_listing': False,
        'owner_access_exposed': False,
        'duplicate_detection': True,
        'automatic_scoring': True,
        'referral_credit': 'tracked_pending_validation',
    }


@app.post('/lead-scout/leads')
async def submit_lead(p: LeadScoutIn, request: Request):
    enforce_public_limit(request)
    backend = get_backend()
    fp = fingerprint(p)
    existing = await backend.select('lead_scout_leads', params={'fingerprint': f'eq.{fp}', 'limit': '1'}) or []
    score = opportunity_score(p)
    lead_id = f'lsl_{secrets.token_urlsafe(10)}'
    duplicate_of = existing[0].get('lead_id') if existing else None
    row = {
        'lead_id': lead_id,
        'fingerprint': fp,
        'scout_name': p.scout_name.strip(),
        'scout_code': (p.scout_code or '').strip() or None,
        'scout_contact': (p.scout_contact or '').strip() or None,
        'business_name': p.business_name.strip(),
        'contact_name': (p.contact_name or '').strip() or None,
        'email': p.email,
        'phone': (p.phone or '').strip() or None,
        'country': p.country.strip(),
        'city_region': (p.city_region or '').strip() or None,
        'deal_side': p.deal_side,
        'lead_type': p.lead_type,
        'product_need_or_offer': p.product_need_or_offer.strip(),
        'estimated_deal_value': p.estimated_deal_value,
        'currency': p.currency,
        'source_url': (p.source_url or '').strip() or None,
        'source_description': (p.source_description or '').strip() or None,
        'evidence_urls': p.evidence_urls,
        'notes': (p.notes or '').strip() or None,
        'consent_to_business_contact': p.consent_to_business_contact,
        'opportunity_score': score,
        'qualification_priority': priority(score),
        'status': 'DUPLICATE_REVIEW' if duplicate_of else 'NEW',
        'duplicate_candidate': bool(duplicate_of),
        'duplicate_of_lead_id': duplicate_of,
        'referral_credit_status': 'PENDING_VALIDATION',
        'commission_status': 'NOT_EARNED',
        'created_at': now(),
        'updated_at': now(),
    }
    await backend.insert('lead_scout_leads', row)
    await backend.insert('lead_scout_audit', {
        'event_id': f'lsa_{secrets.token_urlsafe(10)}',
        'lead_id': lead_id,
        'event_type': 'lead_submitted',
        'summary': 'Public scout submitted a business opportunity',
        'payload': {'score': score, 'priority': priority(score), 'duplicate_candidate': bool(duplicate_of)},
        'created_at': now(),
    })
    return {
        'lead_id': lead_id,
        'status': row['status'],
        'opportunity_score': score,
        'qualification_priority': row['qualification_priority'],
        'duplicate_candidate': bool(duplicate_of),
        'referral_credit_status': row['referral_credit_status'],
        'message': 'Lead received for SAHJONY qualification. Submission does not create a commission, contract, trade approval or payment obligation.',
    }
