from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from pricing_engine import PricingError, business_quote, consumer_quote, policy_snapshot

app = FastAPI(title='SAHJONY Owner Pricing Command API', version='1.0.0', docs_url=None, redoc_url=None)


def require_owner(authorization: str | None, x_role: str | None):
    if x_role != 'owner':
        raise HTTPException(403, 'Owner role required')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(authorization.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid owner credential')


class PricingPreviewIn(BaseModel):
    supplier_cost: float = Field(gt=0)
    international_freight: float = Field(default=0, ge=0)
    local_delivery: float = Field(default=0, ge=0)
    compliance_cost: float = Field(default=0, ge=0)
    payment_cost: float = Field(default=0, ge=0)
    handling_cost: float = Field(default=0, ge=0)
    support_cost: float = Field(default=0, ge=0)
    insurance_cost: float = Field(default=0, ge=0)
    duty_tax_cost: float = Field(default=0, ge=0)
    requested_margin_pct: float | None = Field(default=None, ge=0, lt=95)
    volume_discount_pct: float = Field(default=0, ge=0, le=30)


@app.get('/owner-pricing/health')
async def health():
    return {
        'status': 'ok',
        'service': 'sahjony-owner-pricing-command',
        'customer_price_isolation': True,
        'cost_basis_private': True,
        'owner_approval_required': True,
    }


@app.get('/owner-pricing/policies')
async def policies(authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    return policy_snapshot()


@app.post('/owner-pricing/preview/{audience}')
async def preview(audience: Literal['consumer','business'], p: PricingPreviewIn,
                  authorization: str | None = Header(None, alias='Authorization'), x_role: str | None = Header(None, alias='X-Role')):
    require_owner(authorization, x_role)
    payload = p.model_dump()
    try:
        if audience == 'consumer':
            payload.pop('volume_discount_pct', None)
            quote = consumer_quote(**payload)
        else:
            quote = business_quote(**payload)
    except PricingError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        'audience': quote['audience'],
        'customer_price': quote['customer_price'],
        'currency': quote['currency'],
        'quote_valid_hours': quote['quote_valid_hours'],
        'pricing_release': quote['pricing_release'],
        'margin_floor_passed': quote['margin_floor_passed'],
        'volume_pricing': quote['volume_pricing'],
        'internal': quote['internal'],
        'customer_safe_fields': ['customer_price','currency','quote_valid_hours'],
        'warning': 'Internal cost and margin fields are Owner-only and must never be exposed to customers.'
    }
