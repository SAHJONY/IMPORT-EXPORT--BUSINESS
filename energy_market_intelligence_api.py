from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Energy Market Intelligence', version='1.1.0', docs_url=None, redoc_url=None)

BenchmarkName = Literal['BRENT','WTI','DUBAI','OMAN','MURBAN','WTI_MIDLAND','WCS','MAYA','OTHER']
AssetType = Literal['REFINERY','TERMINAL','STORAGE','PORT','PIPELINE','FPSO','OTHER']
VesselStatus = Literal['OBSERVED','IN_PORT','LOADING','SAILING','DISCHARGING','ANCHORED','UNKNOWN']
SanctionsRisk = Literal['CLEAR','REVIEW','HOLD','BLOCKED','UNKNOWN']


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


def freshness(ts: str | None, max_age_hours: int) -> str:
    if not ts:
        return 'UNKNOWN'
    try:
        seen = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - seen.astimezone(timezone.utc)).total_seconds() / 3600
        return 'FRESH' if age <= max_age_hours else 'STALE'
    except Exception:
        return 'UNKNOWN'


class BenchmarkIn(BaseModel):
    benchmark: BenchmarkName
    price: float = Field(gt=0)
    currency: str = Field(default='USD', min_length=3, max_length=12)
    unit: str = Field(default='BBL', min_length=2, max_length=40)
    assessment_time: str
    provider: str = Field(min_length=2, max_length=160)
    source_reference: str = Field(min_length=3, max_length=1500)
    confidence: int = Field(default=90, ge=0, le=100)


class AssetIn(BaseModel):
    asset_type: AssetType
    name: str = Field(min_length=2, max_length=240)
    operator: str | None = Field(default=None, max_length=240)
    country_code: str = Field(min_length=2, max_length=2)
    location: str | None = Field(default=None, max_length=300)
    capacity_bpd: float | None = Field(default=None, ge=0)
    storage_capacity_bbl: float | None = Field(default=None, ge=0)
    crude_grades: list[str] = Field(default_factory=list, max_length=40)
    source_reference: str = Field(min_length=3, max_length=1500)
    observed_at: str | None = None
    confidence: int = Field(default=70, ge=0, le=100)


class VesselIn(BaseModel):
    imo: str = Field(min_length=5, max_length=20)
    vessel_name: str = Field(min_length=2, max_length=160)
    status: VesselStatus = 'OBSERVED'
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    origin_port: str | None = Field(default=None, max_length=240)
    destination_port: str | None = Field(default=None, max_length=240)
    eta: str | None = None
    draught_m: float | None = Field(default=None, ge=0, le=40)
    cargo_grade: str | None = Field(default=None, max_length=160)
    cargo_bbl_estimate: float | None = Field(default=None, ge=0)
    provider: str = Field(min_length=2, max_length=160)
    source_reference: str = Field(min_length=3, max_length=1500)
    observed_at: str
    confidence: int = Field(default=70, ge=0, le=100)


class SanctionsSnapshotIn(BaseModel):
    subject_type: Literal['COUNTERPARTY','VESSEL','ASSET','DEAL']
    subject_id: str = Field(min_length=2, max_length=180)
    risk: SanctionsRisk
    provider: str = Field(min_length=2, max_length=160)
    source_reference: str = Field(min_length=3, max_length=1500)
    checked_at: str
    matched_programs: list[str] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=4000)


class MatchRunIn(BaseModel):
    deal_id: str | None = Field(default=None, max_length=180)
    minimum_score: int = Field(default=60, ge=0, le=100)
    max_results: int = Field(default=50, ge=1, le=200)


class MarketScanIn(BaseModel):
    objective: Literal['PRICE_MONITOR','REFINERY_DEMAND','SELLER_SUPPLY','VESSEL_FLOW','SANCTIONS_REFRESH','FULL_MARKET_SCAN']='FULL_MARKET_SCAN'
    countries: list[str] = Field(default_factory=list, max_length=40)
    grades: list[str] = Field(default_factory=list, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)


def provider_flags() -> dict:
    return {
        'price_feed_configured': bool(os.getenv('ENERGY_PRICE_FEED_API_KEY','').strip() or os.getenv('ENERGY_PRICE_FEED_URL','').strip()),
        'ais_feed_configured': bool(os.getenv('ENERGY_AIS_API_KEY','').strip() or os.getenv('ENERGY_AIS_FEED_URL','').strip()),
        'sanctions_feed_configured': bool(os.getenv('ENERGY_SANCTIONS_API_KEY','').strip() or os.getenv('ENERGY_SANCTIONS_FEED_URL','').strip()),
        'refinery_feed_configured': bool(os.getenv('ENERGY_REFINERY_API_KEY','').strip() or os.getenv('ENERGY_REFINERY_FEED_URL','').strip()),
    }


def grade_overlap(deal_grade: str, grades: list[str] | None) -> int:
    d = str(deal_grade or '').upper().strip()
    gs = {str(x).upper().strip() for x in (grades or [])}
    if not d or not gs:
        return 0
    if d in gs:
        return 30
    if d == 'BRENT-LINKED' and any('BRENT' in x or 'FORTIES' in x for x in gs):
        return 20
    return 0


def candidate_score(deal: dict, cp: dict) -> tuple[int, list[str]]:
    role = str(cp.get('role') or '').upper()
    side = str(deal.get('side') or '').upper()
    score = 10
    reasons = []
    if side in {'SELL','BROKER','MATCH'} and role in {'BUYER','REFINERY','TRADER'}:
        score += 24; reasons.append('buyer-side role fit')
    if side in {'BUY','BROKER','MATCH'} and role in {'SELLER','PRODUCER','TRADER','MANDATE'}:
        score += 24; reasons.append('seller-side role fit')
    go = grade_overlap(str(deal.get('crude_grade') or ''), cp.get('crude_grades'))
    score += go
    if go: reasons.append('crude grade overlap')
    if cp.get('status') not in {'DUPLICATE_REVIEW'}:
        score += 5
    if cp.get('kyb_status') == 'PASS':
        score += 10; reasons.append('KYB passed')
    if cp.get('screening_status') == 'PASS':
        score += 10; reasons.append('screening passed')
    if cp.get('bankability_status') == 'PASS':
        score += 8; reasons.append('bankability passed')
    evidence = int(cp.get('evidence_score') or 0)
    score += min(13, round(evidence * 0.13))
    if cp.get('country') and deal.get('destination_country') and str(cp.get('country')).lower() in str(deal.get('destination_country')).lower():
        score += 5; reasons.append('destination-market proximity')
    return min(100, score), reasons


@app.get('/energy-intelligence/health')
async def health():
    p = persistent_backend_status()
    return {
        'status': 'ok' if p['configured'] else 'configuration_required',
        'service': 'sahjony-energy-market-intelligence',
        'version': '1.1.0',
        'benchmark_ledger': True,
        'refinery_terminal_intelligence': True,
        'vessel_voyage_intelligence': True,
        'sanctions_snapshot_ledger': True,
        'commercial_opportunity_ledger': True,
        'commercial_opportunity_desks': ['CUBA_FUELS','GLOBAL_CRUDE'],
        'autonomous_counterparty_matching': True,
        'source_provenance_required': True,
        'freshness_controls': True,
        'providers': provider_flags(),
        'automatic_trade_execution': False,
        'automatic_compliance_clearance': False,
        'research_leads_have_binding_authority': False,
        'fail_closed': True,
        'persistence_provider': p['provider'],
    }


@app.post('/energy-intelligence/benchmarks')
async def add_benchmark(p: BenchmarkIn, authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); sid=f'enb_{secrets.token_urlsafe(12)}'; row={'snapshot_id':sid,**p.model_dump(),'created_at':now()}
    await get_backend().insert('energy_benchmark_snapshots',row); return {'snapshot':row}


@app.post('/energy-intelligence/assets')
async def add_asset(p: AssetIn, authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); aid=f'ena_{secrets.token_urlsafe(12)}'; row={'asset_id':aid,**p.model_dump(),'created_at':now(),'updated_at':now()}
    await get_backend().insert('energy_market_assets',row); return {'asset':row}


@app.post('/energy-intelligence/vessels')
async def add_vessel(p: VesselIn, authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); vid=f'env_{secrets.token_urlsafe(12)}'; row={'observation_id':vid,**p.model_dump(),'created_at':now()}
    await get_backend().insert('energy_vessel_observations',row); return {'observation':row,'freshness':freshness(p.observed_at,6)}


@app.post('/energy-intelligence/sanctions')
async def add_sanctions_snapshot(p: SanctionsSnapshotIn, authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); sid=f'ens_{secrets.token_urlsafe(12)}'; row={'snapshot_id':sid,**p.model_dump(),'created_at':now()}
    await get_backend().insert('energy_sanctions_snapshots',row)
    if p.subject_type == 'DEAL' and p.risk in {'HOLD','BLOCKED'}:
        await get_backend().patch('energy_deals',{'stage':'HOLD','release_allowed':False,'updated_at':now()},params={'deal_id':f'eq.{p.subject_id}'})
    return {'snapshot':row,'release_effect':'HOLD' if p.risk in {'HOLD','BLOCKED'} else 'REVIEW'}


@app.post('/energy-intelligence/market-scans')
async def create_market_scan(p: MarketScanIn, authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); jid=f'emi_{secrets.token_urlsafe(12)}'; flags=provider_flags(); ts=now()
    row={'job_id':jid,**p.model_dump(),'status':'QUEUED','providers':flags,'authority':'RESEARCH_AND_ANALYSIS_ONLY','created_at':ts,'updated_at':ts}
    await get_backend().insert('energy_intelligence_jobs',row); return {'job':row}


@app.get('/energy-intelligence/market-scans')
async def list_market_scans(authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); return {'jobs':await get_backend().select('energy_intelligence_jobs',params={'order':'updated_at.desc','limit':'500'}) or []}


@app.get('/energy-intelligence/commercial-opportunities')
async def commercial_opportunities(
    desk: Literal['CUBA_FUELS','GLOBAL_CRUDE'] | None = None,
    authorization: str|None=Header(None,alias='Authorization'),
):
    owner(authorization)
    params={'order':'updated_at.desc','limit':'1000'}
    if desk:
        params['desk']=f'eq.{desk}'
    rows=await get_backend().select('energy_research_leads',params=params) or []
    return {
        'opportunities': rows,
        'count': len(rows),
        'desk': desk or 'ALL',
        'authority': 'RESEARCH_AND_QUALIFICATION_ONLY',
        'automatic_release': False,
        'binding_authority': False,
    }


@app.post('/energy-intelligence/matches/run')
async def run_matches(p: MatchRunIn, authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); backend=get_backend()
    deal_params={'limit':'1000'}
    if p.deal_id: deal_params={'deal_id':f'eq.{p.deal_id}','limit':'1'}
    deals=await backend.select('energy_deals',params=deal_params) or []
    cps=await backend.select('energy_counterparties',params={'limit':'5000'}) or []
    out=[]; ts=now()
    for d in deals:
        if d.get('stage') in {'CLOSED','HOLD'}: continue
        for cp in cps:
            score,reasons=candidate_score(d,cp)
            if score < p.minimum_score: continue
            row={'match_id':f'enm_{secrets.token_urlsafe(12)}','deal_id':d.get('deal_id'),'counterparty_id':cp.get('counterparty_id'),'counterparty_name':cp.get('legal_name'),'counterparty_role':cp.get('role'),'score':score,'reasons':reasons,'status':'CANDIDATE','owner_selected':False,'created_at':ts,'updated_at':ts}
            await backend.insert('energy_deal_matches',row); out.append(row)
    out.sort(key=lambda x:x['score'],reverse=True)
    return {'matches':out[:p.max_results],'match_count':min(len(out),p.max_results),'authority':'RECOMMENDATION_ONLY'}


@app.get('/energy-intelligence/dashboard')
async def dashboard(authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); b=get_backend()
    benchmarks=await b.select('energy_benchmark_snapshots',params={'order':'assessment_time.desc','limit':'100'}) or []
    assets=await b.select('energy_market_assets',params={'order':'updated_at.desc','limit':'500'}) or []
    vessels=await b.select('energy_vessel_observations',params={'order':'observed_at.desc','limit':'500'}) or []
    sanctions=await b.select('energy_sanctions_snapshots',params={'order':'checked_at.desc','limit':'500'}) or []
    matches=await b.select('energy_deal_matches',params={'order':'score.desc','limit':'500'}) or []
    opportunities=await b.select('energy_research_leads',params={'order':'updated_at.desc','limit':'1000'}) or []
    latest={}
    for x in benchmarks:
        latest.setdefault(x.get('benchmark'),{**x,'freshness':freshness(x.get('assessment_time'),24)})
    cuba_fuels=sum(1 for x in opportunities if x.get('desk')=='CUBA_FUELS')
    global_crude=sum(1 for x in opportunities if x.get('desk')=='GLOBAL_CRUDE')
    qualification_pending=sum(1 for x in opportunities if x.get('verification_status') in {'QUALIFICATION_PENDING','DEADLINE_REVIEW'} or x.get('outreach_status')=='QUALIFICATION_SENT')
    return {
        'status':'ok','benchmarks':latest,'assets':assets,'vessels':[{**v,'freshness':freshness(v.get('observed_at'),6)} for v in vessels],
        'sanctions':[{**s,'freshness':freshness(s.get('checked_at'),24)} for s in sanctions],'matches':matches,
        'commercial_opportunities': opportunities,
        'metrics':{
            'benchmark_count':len(latest),'asset_count':len(assets),'vessel_observations':len(vessels),
            'sanctions_snapshots':len(sanctions),'match_candidates':len(matches),'commercial_opportunities':len(opportunities),
            'cuba_fuel_opportunities':cuba_fuels,'global_crude_opportunities':global_crude,'qualification_pending':qualification_pending,
        },
        'providers':provider_flags(),
        'commercial_opportunity_authority':'RESEARCH_AND_QUALIFICATION_ONLY',
    }
