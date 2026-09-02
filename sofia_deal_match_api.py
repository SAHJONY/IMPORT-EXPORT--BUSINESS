from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY SOFIA Deal Supplier Match OS', version='1.0.0', docs_url=None, redoc_url=None)
ORG = 'org_sahjony_global_trade'


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm(value: Any) -> str:
    return ' '.join(str(value or '').lower().replace('/', ' ').replace('-', ' ').split())


def tokens(value: Any) -> set[str]:
    stop = {'and','or','the','de','del','la','el','los','las','para','with','for','y','en','a','of','to'}
    return {x for x in norm(value).split() if len(x) >= 3 and x not in stop}


def similarity(a: Any, b: Any) -> int:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0
    overlap = len(ta & tb)
    return round(100 * overlap / max(1, min(len(ta), len(tb))))


def owner_or_cron(auth: str | None) -> str:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    supplied = auth.removeprefix('Bearer ').strip()
    cron = os.getenv('CRON_SECRET', '').strip()
    if cron and supplied == cron:
        return 'vercel_cron'
    if verify_owner_token(supplied):
        return 'owner'
    raise HTTPException(403, 'Invalid credential')


def demand_text(row: dict[str, Any]) -> str:
    return ' '.join(str(row.get(k) or '') for k in (
        'product_need','product','product_description','product_category','requested_product',
        'need','requirements','notes','primary_activity','activity'
    ))


def candidate_text(row: dict[str, Any]) -> str:
    return ' '.join(str(row.get(k) or '') for k in ('product_match','product_description','supplier_name','source_reference'))


def money(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        return float(value)
    except Exception:
        return None


def score_match(demand: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    product_score = similarity(demand_text(demand), candidate_text(candidate))
    destination = str(demand.get('destination_country') or demand.get('buyer_country') or demand.get('country') or '').upper()
    origin = str(candidate.get('supplier_country') or '').upper()
    quote = candidate.get('source_evidence') or {}
    if not isinstance(quote, dict): quote = {}
    sq = quote.get('supplier_quote') or {}
    if not isinstance(sq, dict): sq = {}
    verified_quote = sq.get('verified') is True
    controls_ready = str(candidate.get('corridor_status') or '').upper() == 'READY'
    base = product_score
    base += 15 if verified_quote else 0
    base += 10 if controls_ready else 0
    base += 5 if candidate.get('unit_cost') else 0
    base += 5 if candidate.get('lead_time_days') is not None else 0
    base = min(100, base)

    target = money(demand.get('target_budget') or demand.get('target_unit_price') or demand.get('budget'))
    supplier_cost = money(candidate.get('landed_cost_estimate') or candidate.get('unit_cost'))
    spread = None
    spread_pct = None
    if target is not None and supplier_cost is not None and target > supplier_cost:
        spread = round(target - supplier_cost, 4)
        spread_pct = round(100 * spread / target, 2)

    blockers = []
    if product_score < 25: blockers.append('LOW_PRODUCT_MATCH')
    if not verified_quote: blockers.append('SUPPLIER_QUOTE_NOT_OWNER_VERIFIED')
    if not controls_ready: blockers.append('SUPPLIER_CORRIDOR_NOT_READY')
    if not destination: blockers.append('DESTINATION_NOT_CONFIRMED')
    return {
        'match_score': base,
        'product_similarity': product_score,
        'supplier_quote_verified': verified_quote,
        'supplier_controls_ready': controls_ready,
        'supplier_origin': origin or None,
        'destination': destination or None,
        'reference_spread_per_unit': spread,
        'reference_spread_pct': spread_pct,
        'blockers': blockers,
        'commercial_status': 'MATCH_CANDIDATE' if product_score >= 25 else 'RESEARCH_ONLY',
        'binding': False,
    }


async def load_demands(limit: int) -> list[dict[str, Any]]:
    b = get_backend()
    intakes = await b.select('customer_trade_intakes', params={'order':'updated_at.desc','limit':str(limit)}) or []
    prospects = await b.select('external_trade_prospects', params={'organization_id':f'eq.{ORG}','order':'updated_at.desc','limit':str(limit)}) or []
    out = []
    for r in intakes:
        row = dict(r); row['_demand_source'] = 'customer_trade_intakes'; row['_demand_id'] = r.get('intake_id') or r.get('trade_intake_id') or r.get('id'); out.append(row)
    for r in prospects:
        stage = str(r.get('qualification_stage') or '').upper()
        warm = bool(r.get('buyer_contacted')) or stage in {'QUALIFIED','RFQ','REQUESTED_QUOTE','OPPORTUNITY','BUYER_VERIFIED'}
        if not warm: continue
        row = dict(r); row['_demand_source'] = 'external_trade_prospects'; row['_demand_id'] = r.get('prospect_id'); out.append(row)
    return out[:limit]


async def load_candidates() -> list[dict[str, Any]]:
    return await get_backend().select('global_supplier_candidates', params={'order':'updated_at.desc','limit':'5000'}) or []


async def run_refresh(limit: int = 1000) -> dict[str, Any]:
    b = get_backend(); ts = now()
    demands = await load_demands(limit)
    candidates = await load_candidates()
    written = 0; actionable = 0
    for d in demands:
        ranked = []
        for c in candidates:
            s = score_match(d, c)
            if s['product_similarity'] <= 0: continue
            ranked.append((s['match_score'], c, s))
        ranked.sort(key=lambda x: x[0], reverse=True)
        for _, c, s in ranked[:5]:
            did = str(d.get('_demand_id') or '')
            cid = str(c.get('global_candidate_id') or '')
            key = hashlib.sha256(f'{d.get("_demand_source")}|{did}|{cid}'.encode()).hexdigest()[:32]
            row = {
                'match_id':f'dsm_{key}', 'organization_id':ORG,
                'demand_source':d.get('_demand_source'), 'demand_id':did,
                'buyer_company':d.get('buyer_company') or d.get('business_name') or d.get('company_name'),
                'product_need':demand_text(d)[:1800],
                'supplier_candidate_id':cid, 'supplier_name':c.get('supplier_name'), 'supplier_country':c.get('supplier_country'),
                **s, 'agent':'SOFIA', 'last_refreshed_at':ts, 'updated_at':ts,
                'next_best_action':'Verify buyer requirement and supplier quote/controls, then prepare protected non-binding commercial comparison.' if s['match_score'] >= 50 else 'Continue supplier research and improve product/specification match.',
                'fee_protection_required':True, 'sahjony_own_capital_target_usd':0,
            }
            existing = await b.select('deal_supplier_matches', params={'match_id':f'eq.dsm_{key}','limit':'1'}) or []
            if existing:
                await b.patch('deal_supplier_matches', row, params={'match_id':f'eq.dsm_{key}'})
            else:
                row['created_at'] = ts
                await b.insert('deal_supplier_matches', row)
            written += 1
            if s['match_score'] >= 50: actionable += 1
    return {
        'status':'ok','agent':'SOFIA','demands_scanned':len(demands),'supplier_candidates_scanned':len(candidates),
        'matches_written':written,'actionable_match_candidates':actionable,
        'policy':'research and non-binding matching only; no automatic supplier disclosure, contract, payment, compliance clearance, or revenue recognition',
        'cash_collected_remains_primary_revenue_metric':True,
    }


@app.get('/crm/sofia-deal-match/health')
async def health():
    p = persistent_backend_status()
    return {'status':'ok' if p.get('configured') else 'configuration_required','service':'sofia-deal-supplier-match-os','version':'1.0.0','canonical_backend':'supabase','daily_refresh_ready':True,'zero_own_capital_target':True,'fee_protection_required':True,'binding_actions_allowed':False}


@app.get('/crm/sofia-deal-match')
async def list_matches(authorization: str | None = Header(None, alias='Authorization'), limit: int = Query(200, ge=1, le=1000)):
    owner_or_cron(authorization)
    rows = await get_backend().select('deal_supplier_matches', params={'order':'match_score.desc,updated_at.desc','limit':str(limit)}) or []
    return {'status':'ok','count':len(rows),'matches':rows}


@app.post('/crm/sofia-deal-match/refresh')
async def refresh(authorization: str | None = Header(None, alias='Authorization'), limit: int = Query(1000, ge=1, le=5000)):
    actor = owner_or_cron(authorization)
    result = await run_refresh(limit)
    return {**result,'triggered_by':actor}


@app.get('/crm/sofia-deal-match/cron')
async def cron(authorization: str | None = Header(None, alias='Authorization')):
    actor = owner_or_cron(authorization)
    result = await run_refresh(1500)
    return {**result,'triggered_by':actor,'schedule':'daily'}
