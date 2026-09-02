from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Competition Intelligence OS', version='1.0.0', docs_url=None, redoc_url=None)
ORG = 'org_sahjony_global_trade'
SourceType = Literal['COMPETITOR_PUBLIC_OFFER','MARKETPLACE_PUBLIC_OFFER','DISTRIBUTOR_PUBLIC_OFFER','MANUFACTURER_PUBLIC_OFFER','PUBLIC_TENDER','TRADE_DATA_REFERENCE','OTHER_PUBLIC_SOURCE']


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid owner credential')


def _cron(auth: str | None) -> None:
    secret = os.getenv('CRON_SECRET', '').strip()
    if not secret:
        raise HTTPException(503, 'CRON_SECRET is not configured')
    if auth != f'Bearer {secret}':
        raise HTTPException(403, 'Invalid cron credential')


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or '').lower() or None
    except Exception:
        return None


def _num(v: Any) -> float | None:
    try:
        if v is None or v == '':
            return None
        return float(v)
    except Exception:
        return None


def _tokens(text: str) -> set[str]:
    import re
    words = re.findall(r'[a-z0-9]+', (text or '').lower())
    stop = {'and','the','for','with','from','of','to','in','de','la','el','los','las','para','con','por','y'}
    return {w for w in words if len(w) >= 3 and w not in stop}


class ObservationIn(BaseModel):
    source_type: SourceType
    source_url: str = Field(min_length=8, max_length=2000)
    source_name: str = Field(min_length=2, max_length=240)
    competitor_name: str | None = Field(default=None, max_length=240)
    product: str = Field(min_length=2, max_length=1000)
    brand: str | None = Field(default=None, max_length=240)
    specification: str | None = Field(default=None, max_length=3000)
    origin_country: str | None = Field(default=None, max_length=3)
    destination_country: str | None = Field(default='CU', max_length=3)
    price: float | None = Field(default=None, ge=0)
    currency: str = Field(default='USD', min_length=3, max_length=3)
    unit: str | None = Field(default=None, max_length=80)
    incoterm: str | None = Field(default=None, max_length=40)
    moq: float | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)
    quality_tier: str | None = Field(default=None, max_length=120)
    public_supplier_name: str | None = Field(default=None, max_length=240)
    public_customer_segment: str | None = Field(default=None, max_length=240)
    observed_at: str | None = None
    valid_until: str | None = None
    notes: str | None = Field(default=None, max_length=4000)


async def _observations(limit: int = 5000) -> list[dict[str, Any]]:
    return await get_backend().select('competition_price_observations', params={'organization_id':f'eq.{ORG}','order':'observed_at.desc','limit':str(limit)}) or []


async def _supplier_candidates(limit: int = 5000) -> list[dict[str, Any]]:
    return await get_backend().select('global_supplier_candidates', params={'order':'updated_at.desc','limit':str(limit)}) or []


async def _buyer_prospects(limit: int = 5000) -> list[dict[str, Any]]:
    return await get_backend().select('external_trade_prospects', params={'organization_id':f'eq.{ORG}','order':'updated_at.desc','limit':str(limit)}) or []


async def _customer_intakes(limit: int = 5000) -> list[dict[str, Any]]:
    return await get_backend().select('customer_trade_intakes', params={'order':'updated_at.desc','limit':str(limit)}) or []


def _supplier_price(row: dict[str, Any]) -> float | None:
    landed = _num(row.get('landed_cost_estimate'))
    return landed if landed is not None else _num(row.get('unit_cost'))


def _buyer_need(row: dict[str, Any]) -> str:
    return ' '.join(str(row.get(k) or '') for k in ('product_need','product','product_description','product_category','commodity','buyer_requirement','notes'))


def _supplier_offer(row: dict[str, Any]) -> str:
    return ' '.join(str(row.get(k) or '') for k in ('product_match','product','product_description','source_reference','supplier_name'))


def _match_score(need: str, offer: str) -> int:
    a, b = _tokens(need), _tokens(offer)
    if not a or not b:
        return 0
    overlap = len(a & b)
    return min(100, int(100 * overlap / max(1, min(len(a), len(b)))))


@app.get('/crm/competition-intelligence/health')
async def health():
    p = persistent_backend_status()
    return {
        'status':'ok' if p.get('configured') else 'configuration_required',
        'service':'sofia-competition-price-deal-scanner',
        'public_sources_only':True,
        'competitive_price_benchmarking':True,
        'supplier_source_discovery':True,
        'customer_segment_discovery':True,
        'deal_supplier_matching':True,
        'quality_and_terms_comparison':True,
        'binding_price_commitment':False,
        'private_counterparty_misappropriation':False,
        'canonical_backend':'supabase',
    }


@app.post('/crm/competition-intelligence/observations')
async def add_observation(payload: ObservationIn, authorization: str | None = Header(None, alias='Authorization')):
    _owner(authorization)
    host = _host(payload.source_url)
    if not host:
        raise HTTPException(422, 'A valid public source URL is required')
    ts = payload.observed_at or now()
    oid = 'cpi_' + hashlib.sha256(f'{payload.source_url}|{payload.product}|{payload.price}|{ts}'.encode()).hexdigest()[:24]
    row = {
        'observation_id':oid,'organization_id':ORG,**payload.model_dump(),
        'currency':payload.currency.upper(),'source_host':host,'observed_at':ts,
        'evidence_class':'PUBLIC_COMPETITIVE_INTELLIGENCE','binding_quote':False,
        'created_at':now(),'updated_at':now(),
    }
    existing = await get_backend().select('competition_price_observations', params={'observation_id':f'eq.{oid}','limit':'1'}) or []
    if existing:
        await get_backend().patch('competition_price_observations', row, params={'observation_id':f'eq.{oid}'})
        status='updated'
    else:
        await get_backend().insert('competition_price_observations', row)
        status='created'
    return {'status':status,'observation':row}


@app.get('/crm/competition-intelligence/benchmark')
async def benchmark(
    product: str = Query(..., min_length=2, max_length=500),
    destination_country: str = Query('CU', min_length=2, max_length=3),
    authorization: str | None = Header(None, alias='Authorization'),
):
    _owner(authorization)
    obs = await _observations()
    pt = _tokens(product)
    matches=[]
    for r in obs:
        if str(r.get('destination_country') or 'CU').upper() != destination_country.upper():
            continue
        score=_match_score(product, str(r.get('product') or ''))
        if score < 25:
            continue
        matches.append({**r,'product_match_score':score})
    matches.sort(key=lambda r:(-(r.get('product_match_score') or 0), _num(r.get('price')) if _num(r.get('price')) is not None else 10**18))
    priced=[_num(r.get('price')) for r in matches if _num(r.get('price')) is not None and str(r.get('currency') or '').upper()=='USD']
    priced=[x for x in priced if x is not None]
    stats={}
    if priced:
        s=sorted(priced); n=len(s)
        stats={'count':n,'low_usd':s[0],'median_usd':s[n//2] if n%2 else round((s[n//2-1]+s[n//2])/2,4),'high_usd':s[-1]}
    return {'status':'ok','product':product,'destination_country':destination_country.upper(),'market_stats':stats,'observations':matches[:100],'binding_quote':False}


async def refresh(limit: int = 1000) -> dict[str, Any]:
    obs = await _observations()
    suppliers = await _supplier_candidates()
    buyers = (await _customer_intakes()) + (await _buyer_prospects())
    results=[]; ts=now()
    for b in buyers[:limit]:
        need=_buyer_need(b)
        if not _tokens(need):
            continue
        destination=str(b.get('destination_country') or b.get('buyer_country') or b.get('country') or 'CU').upper()[:3]
        comp=[]
        for o in obs:
            score=_match_score(need, str(o.get('product') or ''))
            if score >= 30 and str(o.get('destination_country') or destination).upper() == destination:
                comp.append((score,o))
        comp.sort(key=lambda x:(-x[0], _num(x[1].get('price')) if _num(x[1].get('price')) is not None else 10**18))
        supplier_matches=[]
        for s in suppliers:
            score=_match_score(need,_supplier_offer(s))
            if score < 30:
                continue
            supplier_matches.append((score,s))
        supplier_matches.sort(key=lambda x:(-x[0], _supplier_price(x[1]) if _supplier_price(x[1]) is not None else 10**18))
        best_comp=comp[0][1] if comp else None
        best_supplier=supplier_matches[0][1] if supplier_matches else None
        market_price=_num(best_comp.get('price')) if best_comp else None
        supplier_cost=_supplier_price(best_supplier) if best_supplier else None
        room=None
        if market_price is not None and supplier_cost is not None and market_price>0:
            room=round(market_price-supplier_cost,4)
        score=min(100, (_match_score(need,_supplier_offer(best_supplier)) if best_supplier else 0) + (15 if market_price is not None else 0) + (10 if supplier_cost is not None else 0))
        bid=str(b.get('intake_id') or b.get('prospect_id') or b.get('lead_id') or hashlib.sha256(need.encode()).hexdigest()[:16])
        mid='cpm_'+hashlib.sha256(f'{bid}|{best_supplier.get("global_candidate_id") if best_supplier else "none"}|{best_comp.get("observation_id") if best_comp else "none"}'.encode()).hexdigest()[:24]
        next_action='Obtain/verify supplier quote and customer quantity/specification before presenting price.'
        if market_price is not None and supplier_cost is not None:
            next_action='Model a customer offer below comparable public market price while preserving SAHJONY fee, freight, compliance and contingency.'
        row={
            'match_id':mid,'organization_id':ORG,'buyer_or_lead_id':bid,'buyer_need':need[:2000],'destination_country':destination,
            'best_supplier_candidate_id':best_supplier.get('global_candidate_id') if best_supplier else None,
            'best_supplier_name':best_supplier.get('supplier_name') if best_supplier else None,
            'supplier_country':best_supplier.get('supplier_country') if best_supplier else None,
            'supplier_reference_cost':supplier_cost,
            'competition_observation_id':best_comp.get('observation_id') if best_comp else None,
            'competition_name':best_comp.get('competitor_name') if best_comp else None,
            'competition_source_host':best_comp.get('source_host') if best_comp else None,
            'competition_reference_price':market_price,
            'competition_currency':best_comp.get('currency') if best_comp else None,
            'public_supplier_source':best_comp.get('public_supplier_name') if best_comp else None,
            'public_customer_segment':best_comp.get('public_customer_segment') if best_comp else None,
            'gross_price_room_reference':room,'match_score':score,'status':'RESEARCH_MATCH',
            'binding_quote':False,'qualified_demand_inferred':False,'fee_protected':False,
            'next_best_action':next_action,'updated_at':ts,'created_at':ts,
        }
        existing=await get_backend().select('competition_deal_matches', params={'match_id':f'eq.{mid}','limit':'1'}) or []
        if existing:
            row.pop('created_at',None)
            await get_backend().patch('competition_deal_matches', row, params={'match_id':f'eq.{mid}'})
        else:
            await get_backend().insert('competition_deal_matches', row)
        results.append(row)
    results.sort(key=lambda r:(r.get('match_score') or 0, r.get('gross_price_room_reference') or -10**18), reverse=True)
    return {'status':'ok','agent':'SOFIA','matches_refreshed':len(results),'top_matches':results[:100],'rules':{'public_competitive_intelligence_only':True,'no_binding_price_commitment':True,'no_qualified_demand_inference':True,'protect_sahjony_fee_before_introduction':True}}


@app.post('/crm/competition-intelligence/refresh')
async def refresh_owner(limit: int = Query(1000, ge=1, le=5000), authorization: str | None = Header(None, alias='Authorization')):
    _owner(authorization)
    return await refresh(limit)


@app.get('/crm/competition-intelligence/matches')
async def matches(limit: int = Query(200, ge=1, le=1000), authorization: str | None = Header(None, alias='Authorization')):
    _owner(authorization)
    rows=await get_backend().select('competition_deal_matches', params={'organization_id':f'eq.{ORG}','order':'match_score.desc,updated_at.desc','limit':str(limit)}) or []
    return {'status':'ok','count':len(rows),'matches':rows}


@app.get('/crm/competition-intelligence/cron')
async def cron(authorization: str | None = Header(None, alias='Authorization')):
    _cron(authorization)
    return await refresh(2000)
