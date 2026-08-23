from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Energy Provider Hub', version='1.1.0', docs_url=None, redoc_url=None)

ProviderKind = Literal['PRICE','AIS','SANCTIONS','REFINERY']

PROVIDERS = {
    'PRICE': {
        'label': 'Crude pricing / benchmarks',
        'provider_env': 'ENERGY_PRICE_PROVIDER', 'url_env': 'ENERGY_PRICE_API_URL', 'key_env': 'ENERGY_PRICE_API_KEY',
        'auth_env': 'ENERGY_PRICE_AUTH_MODE', 'header_env': 'ENERGY_PRICE_AUTH_HEADER', 'query_env': 'ENERGY_PRICE_AUTH_QUERY',
        'path_env': 'ENERGY_PRICE_SYNC_PATH', 'sync_query_env': 'ENERGY_PRICE_SYNC_QUERY_JSON',
        'required_for': ['benchmark freshness','commercial plausibility','spread analysis'],
    },
    'AIS': {
        'label': 'AIS / vessel intelligence',
        'provider_env': 'ENERGY_AIS_PROVIDER', 'url_env': 'ENERGY_AIS_API_URL', 'key_env': 'ENERGY_AIS_API_KEY',
        'auth_env': 'ENERGY_AIS_AUTH_MODE', 'header_env': 'ENERGY_AIS_AUTH_HEADER', 'query_env': 'ENERGY_AIS_AUTH_QUERY',
        'path_env': 'ENERGY_AIS_SYNC_PATH', 'sync_query_env': 'ENERGY_AIS_SYNC_QUERY_JSON',
        'required_for': ['vessel verification','voyage evidence','ETA intelligence'],
    },
    'SANCTIONS': {
        'label': 'Sanctions / restricted-party intelligence',
        'provider_env': 'ENERGY_SANCTIONS_PROVIDER', 'url_env': 'ENERGY_SANCTIONS_API_URL', 'key_env': 'ENERGY_SANCTIONS_API_KEY',
        'auth_env': 'ENERGY_SANCTIONS_AUTH_MODE', 'header_env': 'ENERGY_SANCTIONS_AUTH_HEADER', 'query_env': 'ENERGY_SANCTIONS_AUTH_QUERY',
        'path_env': 'ENERGY_SANCTIONS_SYNC_PATH', 'sync_query_env': 'ENERGY_SANCTIONS_SYNC_QUERY_JSON',
        'required_for': ['counterparty screening','vessel screening','transaction holds'],
    },
    'REFINERY': {
        'label': 'Refinery / terminal intelligence',
        'provider_env': 'ENERGY_REFINERY_PROVIDER', 'url_env': 'ENERGY_REFINERY_API_URL', 'key_env': 'ENERGY_REFINERY_API_KEY',
        'auth_env': 'ENERGY_REFINERY_AUTH_MODE', 'header_env': 'ENERGY_REFINERY_AUTH_HEADER', 'query_env': 'ENERGY_REFINERY_AUTH_QUERY',
        'path_env': 'ENERGY_REFINERY_SYNC_PATH', 'sync_query_env': 'ENERGY_REFINERY_SYNC_QUERY_JSON',
        'required_for': ['refinery validation','capacity intelligence','terminal verification'],
    },
}


def now() -> str: return datetime.now(timezone.utc).isoformat()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '): raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()): raise HTTPException(403, 'Invalid or expired owner session')


def cron_identity(auth: str | None) -> None:
    secret = os.getenv('CRON_SECRET', '').strip()
    if not secret: raise HTTPException(503, 'CRON_SECRET is not configured')
    if not auth or not secrets.compare_digest(auth, f'Bearer {secret}'):
        raise HTTPException(401, 'Invalid cron authorization')


def json_env(name: str) -> dict:
    raw = os.getenv(name, '').strip()
    if not raw: return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def provider_config(kind: str) -> dict:
    k = kind.strip().upper()
    if k not in PROVIDERS: raise HTTPException(404, 'Unknown Energy provider kind')
    spec = PROVIDERS[k]
    name = os.getenv(spec['provider_env'], '').strip(); url = os.getenv(spec['url_env'], '').strip(); key = os.getenv(spec['key_env'], '').strip()
    auth_mode = os.getenv(spec['auth_env'], 'bearer').strip().lower() or 'bearer'
    auth_header = os.getenv(spec['header_env'], 'Authorization').strip() or 'Authorization'
    auth_query = os.getenv(spec['query_env'], 'api_key').strip() or 'api_key'
    sync_path = os.getenv(spec['path_env'], '').strip()
    sync_query = json_env(spec['sync_query_env'])
    configured = bool(name and url); credential_configured = bool(key) or auth_mode == 'none'
    return {
        'kind': k, 'label': spec['label'], 'provider': name or None, 'configured': configured,
        'credential_configured': credential_configured, 'ready_for_test': configured and credential_configured,
        'auth_mode': auth_mode, 'required_for': spec['required_for'], 'scheduled_sync_path_configured': bool(sync_path),
        '_url': url, '_key': key, '_auth_header': auth_header, '_auth_query': auth_query,
        '_sync_path': sync_path, '_sync_query': sync_query,
    }


def public_config(c: dict) -> dict: return {k: v for k, v in c.items() if not k.startswith('_')}


def request_parts(c: dict) -> tuple[dict, dict]:
    headers = {'User-Agent': 'SAHJONY-Energy-Provider-Hub/1.1', 'Accept': 'application/json,text/plain,*/*'}; params = {}; mode = c['auth_mode']; key = c['_key']
    if mode == 'bearer' and key: headers[c['_auth_header']] = f'Bearer {key}' if c['_auth_header'].lower() == 'authorization' else key
    elif mode == 'header' and key: headers[c['_auth_header']] = key
    elif mode == 'query' and key: params[c['_auth_query']] = key
    elif mode not in {'none','bearer','header','query'}: raise HTTPException(409, f'Unsupported auth mode: {mode}')
    return headers, params


class SyncIn(BaseModel):
    path_suffix: str | None = Field(default=None, max_length=500)
    query: dict[str, str | int | float | bool] = Field(default_factory=dict)
    persist_sample: bool = False


async def latest_runs() -> dict[str, dict]:
    rows = await get_backend().select('energy_provider_sync_runs', params={'order':'created_at.desc','limit':'200'}) or []; latest = {}
    for row in rows:
        kind = row.get('provider_kind')
        if kind and kind not in latest: latest[kind] = row
    return latest


async def perform_sync(kind: str, payload: SyncIn, trigger: str) -> dict:
    c = provider_config(kind)
    if not c['configured']: return {'provider_kind':kind,'status':'SKIPPED','reason':'provider_not_configured'}
    if not c['credential_configured']: return {'provider_kind':kind,'status':'SKIPPED','reason':'credential_not_configured'}
    headers, auth_params = request_parts(c); params = {**auth_params, **payload.query}; url = c['_url'].rstrip('/')
    if payload.path_suffix: url += '/' + payload.path_suffix.lstrip('/')
    run_id = f'epr_{secrets.token_urlsafe(12)}'; started = datetime.now(timezone.utc)
    status='FAILED'; http_status=None; content_hash=None; content_bytes=0; content_type=None; sample=None; error=None
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client: r = await client.get(url, headers=headers, params=params)
        http_status=r.status_code; content_type=r.headers.get('content-type'); body=r.content; content_bytes=len(body); content_hash=hashlib.sha256(body).hexdigest()
        if r.status_code >= 400: error=f'Provider returned HTTP {r.status_code}'
        else:
            status='SUCCESS'
            if payload.persist_sample:
                text=r.text[:4000]
                try:
                    parsed=json.loads(text); sample=parsed if isinstance(parsed,(dict,list)) else {'value':parsed}
                except Exception: sample={'text':text}
    except Exception as exc: error=type(exc).__name__
    latency_ms=round((datetime.now(timezone.utc)-started).total_seconds()*1000)
    row={'run_id':run_id,'provider_kind':kind,'provider_name':c['provider'],'status':status,'trigger':trigger,'http_status':http_status,'content_type':content_type,'content_sha256':content_hash,'content_bytes':content_bytes,'latency_ms':latency_ms,'sample':sample,'error':error,'created_at':now()}
    await get_backend().insert('energy_provider_sync_runs',row)
    return row


@app.get('/energy-providers/health')
async def health():
    p=persistent_backend_status(); configs=[provider_config(k) for k in PROVIDERS]; configured=sum(1 for c in configs if c['ready_for_test'])
    return {'status':'ok' if p['configured'] else 'configuration_required','service':'sahjony-energy-provider-hub','provider_slots':4,'configured_slots':configured,'all_feeds_connected':configured==4,'pricing_connected':provider_config('PRICE')['ready_for_test'],'ais_connected':provider_config('AIS')['ready_for_test'],'sanctions_connected':provider_config('SANCTIONS')['ready_for_test'],'refinery_connected':provider_config('REFINERY')['ready_for_test'],'cron_secret_configured':bool(os.getenv('CRON_SECRET','').strip()),'secrets_exposed':False,'automatic_trade_authority':False,'fail_closed':True,'persistence_provider':p['provider']}


@app.get('/energy-providers')
async def providers(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization); latest=await latest_runs(); rows=[]
    for kind in PROVIDERS:
        c=public_config(provider_config(kind)); run=latest.get(kind)
        c['last_sync']=None if not run else {'status':run.get('status'),'trigger':run.get('trigger'),'http_status':run.get('http_status'),'content_sha256':run.get('content_sha256'),'content_bytes':run.get('content_bytes'),'created_at':run.get('created_at'),'latency_ms':run.get('latency_ms')}; rows.append(c)
    return {'providers':rows,'authority':'CONNECTIVITY_AND_INGESTION_ONLY'}


@app.post('/energy-providers/{kind}/sync')
async def sync_provider(kind: ProviderKind, payload: SyncIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization); row=await perform_sync(kind,payload,'OWNER_MANUAL')
    if row['status']=='SKIPPED': raise HTTPException(409,row)
    if row['status']!='SUCCESS': raise HTTPException(502,{'provider_kind':kind,'status':row['status'],'http_status':row.get('http_status'),'error':row.get('error'),'run_id':row.get('run_id')})
    return {'run_id':row['run_id'],'provider_kind':kind,'provider':row['provider_name'],'status':'SUCCESS','http_status':row['http_status'],'content_sha256':row['content_sha256'],'content_bytes':row['content_bytes'],'latency_ms':row['latency_ms'],'data_persisted':bool(payload.persist_sample),'note':'Connectivity does not authorize commercial reliance, compliance clearance, trading, payment, or shipment release.'}


@app.get('/energy-providers/cron-sync-all')
async def cron_sync_all(authorization: str | None = Header(None, alias='Authorization')):
    cron_identity(authorization); results=[]
    for kind in PROVIDERS:
        c=provider_config(kind)
        payload=SyncIn(path_suffix=c['_sync_path'] or None,query=c['_sync_query'],persist_sample=False)
        results.append(await perform_sync(kind,payload,'VERCEL_CRON'))
    success=sum(1 for r in results if r.get('status')=='SUCCESS'); failed=sum(1 for r in results if r.get('status')=='FAILED')
    return {'status':'ok' if failed==0 else 'degraded','service':'energy-provider-autosync','successful':success,'failed':failed,'skipped':len(results)-success-failed,'results':[{k:v for k,v in r.items() if k not in {'sample'}} for r in results],'automatic_trade_authority':False}


@app.get('/energy-providers/sync-runs')
async def sync_runs(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization); rows=await get_backend().select('energy_provider_sync_runs',params={'order':'created_at.desc','limit':'500'}) or []; return {'runs':rows}
