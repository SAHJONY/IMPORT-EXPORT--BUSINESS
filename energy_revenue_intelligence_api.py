from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Energy Revenue Intelligence', version='1.0.0', docs_url=None, redoc_url=None)

STAGE_PROBABILITY = {
    'LEAD': 0.08,
    'ENTITY_REVIEW': 0.14,
    'MANDATE_REVIEW': 0.20,
    'PRODUCT_REVIEW': 0.28,
    'COMMERCIAL_FIT': 0.38,
    'COMPLIANCE_REVIEW': 0.48,
    'BANKABILITY_REVIEW': 0.58,
    'LOGISTICS_REVIEW': 0.68,
    'OWNER_REVIEW': 0.78,
    'READY_FOR_TRANSACTION': 0.88,
    'HOLD': 0.02,
    'CLOSED': 1.0,
}

NEXT_ACTION = {
    'LEAD': 'Verify counterparties and open entity review',
    'ENTITY_REVIEW': 'Complete legal entity, beneficial ownership, and corporate-contact evidence',
    'MANDATE_REVIEW': 'Verify mandate/authority chain and source relationship',
    'PRODUCT_REVIEW': 'Verify grade, specifications, quantity, allocation, and delivery basis',
    'COMMERCIAL_FIT': 'Validate pricing basis, differential, fees, and executable commercial terms',
    'COMPLIANCE_REVIEW': 'Complete sanctions, origin/destination, end-use, and restricted-party review',
    'BANKABILITY_REVIEW': 'Verify buyer bankability and payment-instrument feasibility',
    'LOGISTICS_REVIEW': 'Verify load/discharge plan, terminal, vessel, inspection, and timing',
    'OWNER_REVIEW': 'Prepare owner decision packet and unresolved-risk summary',
    'READY_FOR_TRANSACTION': 'Maintain freshness and await owner-controlled execution steps',
    'HOLD': 'Resolve hold reason before any commercial progression',
    'CLOSED': 'Reconcile actual outcome, fees, documents, and audit evidence',
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


def f(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def projected_fee(deal: dict) -> float:
    economics = deal.get('economics') if isinstance(deal.get('economics'), dict) else {}
    if economics.get('projected_sahjony_fee') is not None:
        return f(economics.get('projected_sahjony_fee'))
    qty = f(deal.get('quantity_bbl'))
    return f(deal.get('sahjony_fee_flat')) + qty * f(deal.get('sahjony_fee_per_bbl'))


def gross_spread_value(deal: dict) -> float | None:
    economics = deal.get('economics') if isinstance(deal.get('economics'), dict) else {}
    if economics.get('gross_spread_value') is not None:
        return f(economics.get('gross_spread_value'))
    seller = deal.get('seller_price_per_bbl')
    buyer = deal.get('buyer_price_per_bbl')
    if seller is None or buyer is None:
        return None
    return (f(buyer) - f(seller)) * f(deal.get('quantity_bbl'))


def adjusted_probability(deal: dict, verified_count: int, job_statuses: list[str]) -> float:
    stage = str(deal.get('stage') or 'LEAD').upper()
    base = STAGE_PROBABILITY.get(stage, 0.08)
    risk = min(100.0, max(0.0, f(deal.get('risk_score'))))
    evidence_bonus = min(0.08, verified_count * 0.008)
    job_bonus = 0.02 if any(x in {'COMPLETED','READY'} for x in job_statuses) else 0.0
    if deal.get('owner_approved') is True:
        base += 0.04
    if deal.get('release_allowed') is True:
        base += 0.03
    probability = (base + evidence_bonus + job_bonus) * (1 - min(0.80, risk / 125.0))
    if stage == 'HOLD':
        probability = min(probability, 0.02)
    return round(max(0.0, min(1.0, probability)), 4)


def confidence_label(prob: float) -> str:
    if prob >= 0.75: return 'HIGH'
    if prob >= 0.45: return 'MEDIUM'
    if prob >= 0.20: return 'LOW'
    return 'VERY_LOW'


async def portfolio_rows() -> tuple[list[dict], dict[str, list[dict]], dict[str, list[dict]]]:
    backend = get_backend()
    deals = await backend.select('energy_deals', params={'order':'updated_at.desc','limit':'2000'}) or []
    evidence = await backend.select('energy_deal_evidence', params={'order':'created_at.desc','limit':'5000'}) or []
    jobs = await backend.select('energy_agent_jobs', params={'order':'updated_at.desc','limit':'5000'}) or []
    evidence_by: dict[str, list[dict]] = defaultdict(list)
    jobs_by: dict[str, list[dict]] = defaultdict(list)
    for row in evidence:
        if row.get('deal_id'): evidence_by[str(row['deal_id'])].append(row)
    for row in jobs:
        if row.get('deal_id'): jobs_by[str(row['deal_id'])].append(row)
    return deals, evidence_by, jobs_by


def enrich(deal: dict, evidence_rows: list[dict], job_rows: list[dict]) -> dict:
    verified = [x for x in evidence_rows if x.get('verified') is True]
    job_statuses = [str(x.get('status') or '').upper() for x in job_rows]
    p = adjusted_probability(deal, len(verified), job_statuses)
    fee = projected_fee(deal)
    weighted = fee * p
    qty = f(deal.get('quantity_bbl'))
    risk = f(deal.get('risk_score'))
    stage = str(deal.get('stage') or 'LEAD').upper()
    urgency = 1.0
    if stage in {'OWNER_REVIEW','READY_FOR_TRANSACTION'}: urgency = 1.25
    elif stage in {'COMPLIANCE_REVIEW','BANKABILITY_REVIEW','LOGISTICS_REVIEW'}: urgency = 1.15
    elif stage == 'HOLD': urgency = 0.35
    priority = weighted * urgency * (1 - min(0.75, risk / 140.0))
    return {
        'deal_id': deal.get('deal_id'),
        'stage': stage,
        'crude_grade': deal.get('crude_grade'),
        'quantity_bbl': qty,
        'origin_country': deal.get('origin_country'),
        'destination_country': deal.get('destination_country'),
        'buyer_counterparty_id': deal.get('buyer_counterparty_id'),
        'seller_counterparty_id': deal.get('seller_counterparty_id'),
        'projected_sahjony_fee': round(fee, 2),
        'gross_spread_value': gross_spread_value(deal),
        'execution_probability': p,
        'confidence': confidence_label(p),
        'probability_weighted_revenue': round(weighted, 2),
        'risk_score': risk,
        'risk_flags': deal.get('risk_flags') or [],
        'verified_evidence_count': len(verified),
        'agent_job_count': len(job_rows),
        'active_agent_jobs': sum(1 for x in job_statuses if x not in {'COMPLETED','CANCELLED','FAILED'}),
        'owner_approved': deal.get('owner_approved') is True,
        'release_allowed': deal.get('release_allowed') is True,
        'next_action': NEXT_ACTION.get(stage, 'Review current deal state'),
        'priority_score': round(priority, 2),
        'currency': deal.get('currency') or 'USD',
        'updated_at': deal.get('updated_at'),
        'profit_guaranteed': False,
    }


@app.get('/energy-revenue/health')
async def health():
    p = persistent_backend_status()
    return {
        'status': 'ok' if p['configured'] else 'configuration_required',
        'service': 'sahjony-energy-revenue-intelligence',
        'probability_weighted_pipeline': True,
        'deal_prioritization': True,
        'portfolio_by_grade_country': True,
        'next_action_engine': True,
        'projected_values_are_not_realized_revenue': True,
        'automatic_trade_authority': False,
        'fail_closed': True,
        'persistence_provider': p['provider'],
    }


@app.get('/energy-revenue/portfolio')
async def portfolio(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    deals, evidence_by, jobs_by = await portfolio_rows()
    rows = [enrich(d, evidence_by.get(str(d.get('deal_id')), []), jobs_by.get(str(d.get('deal_id')), [])) for d in deals]
    rows.sort(key=lambda x: x['priority_score'], reverse=True)
    active = [x for x in rows if x['stage'] != 'CLOSED']
    total_projected = sum(x['projected_sahjony_fee'] for x in active)
    weighted = sum(x['probability_weighted_revenue'] for x in active)
    barrels = sum(x['quantity_bbl'] for x in active)
    return {
        'as_of': now(),
        'summary': {
            'active_deals': len(active),
            'total_active_barrels': round(barrels, 2),
            'projected_sahjony_fees': round(total_projected, 2),
            'probability_weighted_revenue': round(weighted, 2),
            'ready_for_transaction': sum(1 for x in active if x['stage'] == 'READY_FOR_TRANSACTION'),
            'on_hold': sum(1 for x in active if x['stage'] == 'HOLD'),
            'owner_review': sum(1 for x in active if x['stage'] == 'OWNER_REVIEW'),
        },
        'deals': rows,
        'note': 'Projected and probability-weighted amounts are planning metrics only. Revenue is realized only after a completed, reconciled transaction and collected fee.',
    }


@app.get('/energy-revenue/breakdown')
async def breakdown(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    deals, evidence_by, jobs_by = await portfolio_rows()
    rows = [enrich(d, evidence_by.get(str(d.get('deal_id')), []), jobs_by.get(str(d.get('deal_id')), [])) for d in deals if str(d.get('stage') or '').upper() != 'CLOSED']
    by_grade: dict[str, dict] = {}
    by_origin: dict[str, dict] = {}
    by_destination: dict[str, dict] = {}
    def add(bucket: dict[str, dict], key: str, row: dict):
        v = bucket.setdefault(key or 'UNKNOWN', {'deals':0,'barrels':0.0,'projected_fees':0.0,'weighted_revenue':0.0})
        v['deals'] += 1; v['barrels'] += row['quantity_bbl']; v['projected_fees'] += row['projected_sahjony_fee']; v['weighted_revenue'] += row['probability_weighted_revenue']
    for row in rows:
        add(by_grade, str(row.get('crude_grade') or 'UNKNOWN'), row)
        add(by_origin, str(row.get('origin_country') or 'UNKNOWN'), row)
        add(by_destination, str(row.get('destination_country') or 'UNKNOWN'), row)
    def finish(bucket: dict[str, dict]):
        return [{'key':k, **{n: round(v,2) if isinstance(v,float) else v for n,v in value.items()}} for k,value in sorted(bucket.items(), key=lambda item:item[1]['weighted_revenue'], reverse=True)]
    return {'as_of':now(),'by_grade':finish(by_grade),'by_origin_country':finish(by_origin),'by_destination_country':finish(by_destination)}


@app.get('/energy-revenue/priority-queue')
async def priority_queue(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    deals, evidence_by, jobs_by = await portfolio_rows()
    rows = [enrich(d, evidence_by.get(str(d.get('deal_id')), []), jobs_by.get(str(d.get('deal_id')), [])) for d in deals if str(d.get('stage') or '').upper() != 'CLOSED']
    rows.sort(key=lambda x: x['priority_score'], reverse=True)
    return {
        'queue': rows[:100],
        'ranking_basis': ['probability_weighted_revenue','stage_urgency','risk_penalty','evidence_progress','agent_progress'],
        'automatic_execution': False,
    }
