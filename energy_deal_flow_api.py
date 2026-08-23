from __future__ import annotations

import math
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status
from energy_crude_oil_api import economics

app = FastAPI(title='SAHJONY Energy Deal Flow Engine', version='1.0.0', docs_url=None, redoc_url=None)

RequirementStatus = Literal['OPEN','PAUSED','MATCHED','CLOSED','HOLD']
OfferStatus = Literal['OPEN','PAUSED','MATCHED','EXPIRED','CLOSED','HOLD']


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


def norm(value: str | None) -> str:
    return ' '.join(re.sub(r'[^A-Z0-9]+', ' ', (value or '').upper()).split())


def same_text(a: str | None, b: str | None) -> bool:
    return bool(a and b and norm(a) == norm(b))


def incoterm_family(value: str | None) -> str | None:
    v = norm(value)
    if not v:
        return None
    for code in ('FOB','CIF','CFR','DES','DAP','DDP','EXW','FCA'):
        if code in v:
            return code
    return v[:20]


def overlap_ratio(required: float, available: float) -> float:
    if required <= 0 or available <= 0:
        return 0.0
    return min(required, available) / max(required, available)


class BuyerRequirementIn(BaseModel):
    buyer_counterparty_id: str | None = Field(default=None, max_length=180)
    buyer_legal_name: str = Field(min_length=2, max_length=240)
    buyer_country: str = Field(min_length=2, max_length=120)
    crude_grade: str = Field(min_length=2, max_length=120)
    quantity_bbl: float = Field(gt=0, le=1_000_000_000)
    minimum_quantity_bbl: float | None = Field(default=None, gt=0, le=1_000_000_000)
    maximum_quantity_bbl: float | None = Field(default=None, gt=0, le=1_000_000_000)
    api_gravity_min: float | None = Field(default=None, ge=5, le=60)
    api_gravity_max: float | None = Field(default=None, ge=5, le=60)
    sulfur_pct_max: float | None = Field(default=None, ge=0, le=10)
    destination_country: str | None = Field(default=None, max_length=120)
    discharge_port: str | None = Field(default=None, max_length=240)
    incoterm: str | None = Field(default=None, max_length=30)
    pricing_basis: str | None = Field(default=None, max_length=500)
    maximum_price_per_bbl: float | None = Field(default=None, ge=0)
    maximum_differential_per_bbl: float | None = None
    currency: str = Field(default='USD', min_length=3, max_length=12)
    payment_instrument: str | None = Field(default=None, max_length=300)
    loading_window: str | None = Field(default=None, max_length=240)
    term: Literal['SPOT','TERM','TRIAL_PLUS_TERM'] = 'SPOT'
    monthly_cargo_count: int | None = Field(default=None, ge=1, le=100)
    evidence_urls: list[str] = Field(default_factory=list, max_length=30)
    source_reference: str | None = Field(default=None, max_length=1200)
    raw_requirement_text: str | None = Field(default=None, max_length=16000)
    notes: str | None = Field(default=None, max_length=5000)


class SellerOfferIn(BaseModel):
    seller_counterparty_id: str | None = Field(default=None, max_length=180)
    seller_legal_name: str = Field(min_length=2, max_length=240)
    seller_country: str = Field(min_length=2, max_length=120)
    crude_grade: str = Field(min_length=2, max_length=120)
    quantity_bbl: float = Field(gt=0, le=1_000_000_000)
    minimum_quantity_bbl: float | None = Field(default=None, gt=0, le=1_000_000_000)
    api_gravity: float | None = Field(default=None, ge=5, le=60)
    sulfur_pct: float | None = Field(default=None, ge=0, le=10)
    origin_country: str | None = Field(default=None, max_length=120)
    load_port: str | None = Field(default=None, max_length=240)
    incoterm: str | None = Field(default=None, max_length=30)
    pricing_basis: str | None = Field(default=None, max_length=500)
    price_per_bbl: float | None = Field(default=None, ge=0)
    differential_per_bbl: float | None = None
    currency: str = Field(default='USD', min_length=3, max_length=12)
    payment_instrument: str | None = Field(default=None, max_length=300)
    loading_window: str | None = Field(default=None, max_length=240)
    term: Literal['SPOT','TERM','TRIAL_PLUS_TERM'] = 'SPOT'
    allocation_reference: str | None = Field(default=None, max_length=1200)
    mandate_reference: str | None = Field(default=None, max_length=1200)
    terminal_reference: str | None = Field(default=None, max_length=1200)
    evidence_urls: list[str] = Field(default_factory=list, max_length=30)
    source_reference: str | None = Field(default=None, max_length=1200)
    raw_offer_text: str | None = Field(default=None, max_length=16000)
    notes: str | None = Field(default=None, max_length=5000)


class MatchRunIn(BaseModel):
    requirement_id: str | None = Field(default=None, max_length=180)
    minimum_score: int = Field(default=55, ge=0, le=100)
    max_results: int = Field(default=50, ge=1, le=250)


class PromoteMatchIn(BaseModel):
    sahjony_fee_per_bbl: float | None = Field(default=None, ge=0)
    sahjony_fee_flat: float | None = Field(default=None, ge=0)
    owner_note: str | None = Field(default=None, max_length=5000)


async def audit(event: str, summary: str, payload: dict | None = None) -> None:
    await get_backend().insert('energy_audit_events', {
        'event_id': f'ena_{secrets.token_urlsafe(12)}',
        'actor_role': 'owner', 'actor_id': 'owner', 'event_type': event,
        'summary': summary, 'payload': payload or {}, 'created_at': now(),
    })


async def get_counterparty(counterparty_id: str | None) -> dict | None:
    if not counterparty_id:
        return None
    rows = await get_backend().select('energy_counterparties', params={'counterparty_id': f'eq.{counterparty_id}', 'limit': '1'}) or []
    return rows[0] if rows else None


def counterparty_gate(counterparty: dict | None) -> dict:
    if not counterparty:
        return {'known': False, 'score': 0, 'blocking': False, 'reason': 'counterparty_not_linked'}
    screening = str(counterparty.get('screening_status') or 'PENDING').upper()
    kyb = str(counterparty.get('kyb_status') or 'PENDING').upper()
    bank = str(counterparty.get('bankability_status') or 'PENDING').upper()
    blocking = screening in {'HOLD','BLOCKED','FAIL'} or kyb in {'HOLD','BLOCKED','FAIL'} or bank in {'BLOCKED','FAIL'}
    score = 0
    score += 5 if kyb in {'PASS','VERIFIED','APPROVED'} else 0
    score += 5 if screening in {'PASS','CLEAR','REVIEWED'} else 0
    score += 5 if bank in {'PASS','VERIFIED','APPROVED'} else 0
    return {'known': True, 'score': score, 'blocking': blocking, 'kyb': kyb, 'screening': screening, 'bankability': bank}


def match_score(req: dict, offer: dict, buyer_gate: dict, seller_gate: dict) -> dict:
    reasons: list[str] = []
    blockers: list[str] = []
    score = 0.0

    grade_exact = same_text(req.get('crude_grade'), offer.get('crude_grade'))
    if grade_exact:
        score += 30; reasons.append('grade_exact')
    else:
        blockers.append('grade_mismatch')

    qty_fit = overlap_ratio(float(req.get('quantity_bbl') or 0), float(offer.get('quantity_bbl') or 0))
    score += 15 * qty_fit
    if qty_fit >= .8: reasons.append('quantity_strong_fit')
    elif qty_fit < .4: blockers.append('quantity_weak_fit')

    r_inc = incoterm_family(req.get('incoterm')); o_inc = incoterm_family(offer.get('incoterm'))
    if r_inc and o_inc:
        if r_inc == o_inc: score += 10; reasons.append('incoterm_match')
        else: blockers.append('incoterm_mismatch')
    else:
        score += 3; reasons.append('incoterm_incomplete')

    if same_text(req.get('currency'), offer.get('currency')):
        score += 5; reasons.append('currency_match')
    else:
        blockers.append('currency_mismatch')

    r_term = str(req.get('term') or '').upper(); o_term = str(offer.get('term') or '').upper()
    if r_term and o_term and r_term == o_term:
        score += 5; reasons.append('term_match')

    api = offer.get('api_gravity')
    if api is not None:
        if req.get('api_gravity_min') is not None and float(api) < float(req['api_gravity_min']): blockers.append('api_below_requirement')
        elif req.get('api_gravity_max') is not None and float(api) > float(req['api_gravity_max']): blockers.append('api_above_requirement')
        else: score += 5; reasons.append('api_fit')

    sulfur = offer.get('sulfur_pct')
    if sulfur is not None and req.get('sulfur_pct_max') is not None:
        if float(sulfur) <= float(req['sulfur_pct_max']): score += 5; reasons.append('sulfur_fit')
        else: blockers.append('sulfur_exceeds_requirement')

    price = offer.get('price_per_bbl')
    max_price = req.get('maximum_price_per_bbl')
    if price is not None and max_price is not None:
        if float(price) <= float(max_price):
            score += 10; reasons.append('price_within_ceiling')
        else:
            over = float(price) - float(max_price)
            blockers.append(f'price_above_ceiling:{over:.2f}')

    diff = offer.get('differential_per_bbl'); max_diff = req.get('maximum_differential_per_bbl')
    if diff is not None and max_diff is not None:
        if float(diff) <= float(max_diff): score += 5; reasons.append('differential_fit')
        else: blockers.append('differential_above_ceiling')

    score += buyer_gate.get('score', 0) + seller_gate.get('score', 0)
    if buyer_gate.get('blocking'): blockers.append('buyer_governance_block')
    if seller_gate.get('blocking'): blockers.append('seller_governance_block')

    hard_block = any(x in blockers for x in ('grade_mismatch','currency_mismatch','api_below_requirement','api_above_requirement','sulfur_exceeds_requirement','buyer_governance_block','seller_governance_block'))
    final = max(0, min(100, round(score)))
    recommendation = 'BLOCKED' if hard_block else ('STRONG_MATCH' if final >= 80 else ('REVIEW_MATCH' if final >= 60 else 'WEAK_MATCH'))
    return {'score': final, 'recommendation': recommendation, 'reasons': reasons, 'blockers': blockers, 'hard_block': hard_block}


@app.get('/energy-deal-flow/health')
async def health():
    p = persistent_backend_status()
    return {
        'status': 'ok' if p['configured'] else 'configuration_required',
        'service': 'sahjony-energy-deal-flow-engine',
        'buyer_requirement_ingestion': True,
        'seller_offer_ingestion': True,
        'autonomous_matching_v2': True,
        'owner_match_promotion_required': True,
        'automatic_contract_execution': False,
        'automatic_payment_authority': False,
        'automatic_compliance_clearance': False,
        'automatic_cargo_release': False,
        'fail_closed': True,
        'persistence_provider': p['provider'],
    }


@app.post('/energy-deal-flow/requirements')
async def create_requirement(payload: BuyerRequirementIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rid = f'ebr_{secrets.token_urlsafe(12)}'; ts = now()
    row = {'requirement_id': rid, **payload.model_dump(), 'status': 'OPEN', 'created_at': ts, 'updated_at': ts}
    await get_backend().insert('energy_buyer_requirements', row)
    await audit('buyer_requirement_created', f'Buyer requirement created: {payload.crude_grade} / {payload.quantity_bbl:,.0f} bbl', {'requirement_id': rid})
    return {'requirement': row}


@app.get('/energy-deal-flow/requirements')
async def list_requirements(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_buyer_requirements', params={'order': 'updated_at.desc', 'limit': '1000'}) or []
    return {'requirements': rows}


@app.post('/energy-deal-flow/offers')
async def create_offer(payload: SellerOfferIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    oid = f'eso_{secrets.token_urlsafe(12)}'; ts = now()
    flags = []
    if not payload.allocation_reference: flags.append('ALLOCATION_NOT_EVIDENCED')
    if not payload.mandate_reference: flags.append('MANDATE_NOT_EVIDENCED')
    if not payload.terminal_reference: flags.append('TERMINAL_NOT_EVIDENCED')
    row = {'offer_id': oid, **payload.model_dump(), 'status': 'OPEN', 'preliminary_risk_flags': flags, 'created_at': ts, 'updated_at': ts}
    await get_backend().insert('energy_seller_offers', row)
    await audit('seller_offer_created', f'Seller offer created: {payload.crude_grade} / {payload.quantity_bbl:,.0f} bbl', {'offer_id': oid, 'risk_flags': flags})
    return {'offer': row}


@app.get('/energy-deal-flow/offers')
async def list_offers(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_seller_offers', params={'order': 'updated_at.desc', 'limit': '1000'}) or []
    return {'offers': rows}


@app.post('/energy-deal-flow/match-runs')
async def run_matches(payload: MatchRunIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    backend = get_backend()
    rparams = {'status': 'eq.OPEN', 'limit': '1000'}
    if payload.requirement_id:
        rparams['requirement_id'] = f'eq.{payload.requirement_id}'
    requirements = await backend.select('energy_buyer_requirements', params=rparams) or []
    offers = await backend.select('energy_seller_offers', params={'status': 'eq.OPEN', 'limit': '2000'}) or []
    run_id = f'emr_{secrets.token_urlsafe(12)}'; created = []
    cp_cache: dict[str, dict | None] = {}
    async def cp(cid: str | None):
        if not cid: return None
        if cid not in cp_cache: cp_cache[cid] = await get_counterparty(cid)
        return cp_cache[cid]
    for req in requirements:
        buyer_gate = counterparty_gate(await cp(req.get('buyer_counterparty_id')))
        for offer in offers:
            seller_gate = counterparty_gate(await cp(offer.get('seller_counterparty_id')))
            result = match_score(req, offer, buyer_gate, seller_gate)
            if result['score'] < payload.minimum_score and result['recommendation'] != 'BLOCKED':
                continue
            mid = f'emm_{secrets.token_urlsafe(12)}'; ts = now()
            row = {
                'match_id': mid, 'run_id': run_id,
                'requirement_id': req['requirement_id'], 'offer_id': offer['offer_id'],
                'buyer_counterparty_id': req.get('buyer_counterparty_id'), 'seller_counterparty_id': offer.get('seller_counterparty_id'),
                'crude_grade': req.get('crude_grade'), 'quantity_bbl': min(float(req.get('quantity_bbl') or 0), float(offer.get('quantity_bbl') or 0)),
                **result, 'status': 'CANDIDATE', 'owner_promoted': False, 'deal_id': None, 'created_at': ts, 'updated_at': ts,
            }
            await backend.insert('energy_commercial_matches', row); created.append(row)
    created.sort(key=lambda x: (x['recommendation'] != 'BLOCKED', x['score']), reverse=True)
    created = created[:payload.max_results]
    await backend.insert('energy_match_runs', {'run_id': run_id, 'requirement_count': len(requirements), 'offer_count': len(offers), 'candidate_count': len(created), 'created_at': now()})
    return {'run_id': run_id, 'requirements_evaluated': len(requirements), 'offers_evaluated': len(offers), 'matches': created, 'authority': 'ADVISORY_MATCHING_ONLY'}


@app.get('/energy-deal-flow/matches')
async def list_matches(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_commercial_matches', params={'order': 'created_at.desc', 'limit': '2000'}) or []
    return {'matches': rows}


@app.post('/energy-deal-flow/matches/{match_id}/promote')
async def promote_match(match_id: str, payload: PromoteMatchIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    backend = get_backend()
    matches = await backend.select('energy_commercial_matches', params={'match_id': f'eq.{match_id}', 'limit': '1'}) or []
    if not matches: raise HTTPException(404, 'Energy commercial match not found')
    m = matches[0]
    if m.get('recommendation') == 'BLOCKED' or m.get('hard_block') is True:
        raise HTTPException(409, 'Blocked match cannot be promoted')
    if m.get('deal_id'):
        return {'status': 'already_promoted', 'deal_id': m['deal_id'], 'match': m}
    reqs = await backend.select('energy_buyer_requirements', params={'requirement_id': f"eq.{m['requirement_id']}", 'limit': '1'}) or []
    offers = await backend.select('energy_seller_offers', params={'offer_id': f"eq.{m['offer_id']}", 'limit': '1'}) or []
    if not reqs or not offers: raise HTTPException(409, 'Match source objects are missing')
    req, offer = reqs[0], offers[0]
    did = f'end_{secrets.token_urlsafe(12)}'; ts = now()
    quantity = min(float(req.get('quantity_bbl') or 0), float(offer.get('quantity_bbl') or 0))
    deal = {
        'deal_id': did, 'side': 'BROKER',
        'buyer_counterparty_id': req.get('buyer_counterparty_id'), 'seller_counterparty_id': offer.get('seller_counterparty_id'),
        'crude_grade': req.get('crude_grade'), 'api_gravity': offer.get('api_gravity'), 'sulfur_pct': offer.get('sulfur_pct'),
        'quantity_bbl': quantity, 'term': req.get('term') or offer.get('term') or 'SPOT',
        'origin_country': offer.get('origin_country') or offer.get('seller_country'), 'destination_country': req.get('destination_country') or req.get('buyer_country'),
        'load_port': offer.get('load_port'), 'discharge_port': req.get('discharge_port'),
        'incoterm': req.get('incoterm') or offer.get('incoterm'), 'pricing_basis': offer.get('pricing_basis') or req.get('pricing_basis'),
        'differential_per_bbl': offer.get('differential_per_bbl'), 'seller_price_per_bbl': offer.get('price_per_bbl'),
        'buyer_price_per_bbl': req.get('maximum_price_per_bbl'), 'sahjony_fee_per_bbl': payload.sahjony_fee_per_bbl,
        'sahjony_fee_flat': payload.sahjony_fee_flat, 'currency': offer.get('currency') or req.get('currency') or 'USD',
        'payment_instrument': req.get('payment_instrument') or offer.get('payment_instrument'),
        'loading_window': req.get('loading_window') or offer.get('loading_window'),
        'source_reference': f"match:{match_id}", 'notes': payload.owner_note,
        'stage': 'LEAD', 'risk_score': 0, 'risk_flags': list(offer.get('preliminary_risk_flags') or []),
        'release_allowed': False, 'owner_approved': False, 'created_by': 'owner', 'created_at': ts, 'updated_at': ts,
        'commercial_match_id': match_id, 'buyer_requirement_id': req['requirement_id'], 'seller_offer_id': offer['offer_id'],
    }
    deal['economics'] = economics(deal)
    await backend.insert('energy_deals', deal)
    await backend.patch('energy_commercial_matches', {'owner_promoted': True, 'status': 'PROMOTED', 'deal_id': did, 'updated_at': ts}, params={'match_id': f'eq.{match_id}'})
    await backend.patch('energy_buyer_requirements', {'status': 'MATCHED', 'updated_at': ts}, params={'requirement_id': f"eq.{req['requirement_id']}"})
    await backend.patch('energy_seller_offers', {'status': 'MATCHED', 'updated_at': ts}, params={'offer_id': f"eq.{offer['offer_id']}"})
    job_id = f'edj_{secrets.token_urlsafe(12)}'
    job = {
        'job_id': job_id, 'deal_id': did, 'match_id': match_id, 'status': 'QUEUED', 'objective': 'FULL_DEAL_ROOM_ORCHESTRATION',
        'authority': 'ADVISORY_AND_PREPARATION_ONLY',
        'next_actions': [
            'VERIFY_BUYER_ENTITY_AND_BANKABILITY','VERIFY_SELLER_ENTITY_AND_MANDATE','SYNC_AND_SCREEN_SANCTIONS',
            'VERIFY_PRODUCT_AND_ALLOCATION','VERIFY_TERMINAL_AND_LOGISTICS','VALIDATE_COMMERCIAL_TERMS',
            'PREPARE_OWNER_DECISION_PACKET'
        ],
        'automatic_contract_execution': False, 'automatic_payment_authority': False,
        'automatic_compliance_clearance': False, 'automatic_cargo_release': False,
        'created_at': ts, 'updated_at': ts,
    }
    await backend.insert('energy_deal_room_agent_jobs', job)
    await audit('commercial_match_promoted', f'Owner promoted crude match into deal room {did}', {'match_id': match_id, 'deal_id': did, 'job_id': job_id})
    return {'status': 'promoted', 'deal': deal, 'deal_room_agent_job': job}


@app.get('/energy-deal-flow/deal-room-jobs')
async def deal_room_jobs(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_deal_room_agent_jobs', params={'order': 'updated_at.desc', 'limit': '1000'}) or []
    return {'jobs': rows}
