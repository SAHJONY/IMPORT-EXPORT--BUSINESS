from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Energy EIA Adapter', version='1.0.0', docs_url=None, redoc_url=None)

EIA_BASE = 'https://api.eia.gov/v2/'
ProfileType = Literal['PRICE', 'REFINERY', 'PETROLEUM_MARKET']


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def api_key() -> str:
    return os.getenv('EIA_API_KEY', '').strip() or os.getenv('ENERGY_EIA_API_KEY', '').strip() or os.getenv('ENERGY_PRICE_API_KEY', '').strip()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


def cron(auth: str | None) -> None:
    secret = os.getenv('CRON_SECRET', '').strip()
    if not secret:
        raise HTTPException(503, 'CRON_SECRET is not configured')
    if not auth or not secrets.compare_digest(auth, f'Bearer {secret}'):
        raise HTTPException(401, 'Invalid cron authorization')


def clean_route(route: str) -> str:
    value = route.strip().strip('/')
    if not value or not re.fullmatch(r'[A-Za-z0-9_./-]+', value):
        raise HTTPException(400, 'Invalid EIA API route')
    return value


class EIAProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    profile_type: ProfileType
    route: str = Field(min_length=1, max_length=500)
    frequency: str | None = Field(default=None, max_length=80)
    data_fields: list[str] = Field(default_factory=list, max_length=20)
    facets: dict[str, list[str]] = Field(default_factory=dict)
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    length: int = Field(default=5000, ge=1, le=5000)
    enabled: bool = True
    value_field: str | None = Field(default=None, max_length=120)
    benchmark_label: str | None = Field(default=None, max_length=120)
    unit_override: str | None = Field(default=None, max_length=80)
    currency: str = Field(default='USD', max_length=12)
    notes: str | None = Field(default=None, max_length=3000)


def query_params(profile: dict) -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = [('api_key', api_key()), ('offset', '0'), ('length', str(int(profile.get('length') or 5000)))]
    if profile.get('frequency'):
        params.append(('frequency', str(profile['frequency'])))
    for i, field in enumerate(profile.get('data_fields') or []):
        params.append((f'data[{i}]', str(field)))
    for facet, values in (profile.get('facets') or {}).items():
        for value in values:
            params.append((f'facets[{facet}][]', str(value)))
    if profile.get('start'):
        params.append(('start', str(profile['start'])))
    if profile.get('end'):
        params.append(('end', str(profile['end'])))
    params.extend([
        ('sort[0][column]', 'period'),
        ('sort[0][direction]', 'desc'),
    ])
    return params


async def fetch_json(url: str, params: list[tuple[str, str]]) -> tuple[dict, dict]:
    if not api_key():
        raise HTTPException(409, 'EIA API key is not configured')
    started = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url, params=params, headers={'User-Agent': 'SAHJONY-Energy-EIA/1.0 (+https://www.sahjony.com)', 'Accept': 'application/json'})
    body = response.content
    meta = {
        'source_url': str(response.url).split('api_key=')[0],
        'http_status': response.status_code,
        'sha256': hashlib.sha256(body).hexdigest(),
        'bytes': len(body),
        'latency_ms': round((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    }
    if response.status_code >= 400:
        raise HTTPException(502, {'provider': 'EIA Open Data', **meta})
    try:
        return response.json(), meta
    except Exception:
        raise HTTPException(502, 'EIA returned a non-JSON response')


async def sync_profile(profile: dict, trigger: str) -> dict:
    route = clean_route(str(profile.get('route') or ''))
    url = f'{EIA_BASE}{route}/data/'
    payload, meta = await fetch_json(url, query_params(profile))
    response = payload.get('response') or {}
    data = response.get('data') or []
    if not isinstance(data, list):
        raise HTTPException(502, 'Unexpected EIA response shape')

    backend = get_backend()
    sync_id = f'eia_{secrets.token_urlsafe(12)}'
    normalized = 0
    canonical = 0
    value_field = profile.get('value_field')
    profile_type = profile.get('profile_type')

    for item in data:
        if not isinstance(item, dict):
            continue
        observation = {
            'observation_id': f'eio_{secrets.token_urlsafe(12)}',
            'profile_id': profile.get('profile_id'),
            'profile_name': profile.get('name'),
            'profile_type': profile_type,
            'route': route,
            'period': item.get('period'),
            'raw': item,
            'provider': 'U.S. Energy Information Administration Open Data',
            'sync_id': sync_id,
            'source_sha256': meta['sha256'],
            'created_at': now(),
        }
        await backend.insert('energy_eia_observations', observation)
        normalized += 1

        if profile_type == 'PRICE' and value_field and item.get(value_field) not in (None, ''):
            try:
                price = float(item[value_field])
            except Exception:
                continue
            snapshot = {
                'snapshot_id': f'enb_{secrets.token_urlsafe(12)}',
                'benchmark': profile.get('benchmark_label') or profile.get('name'),
                'price': price,
                'currency': profile.get('currency') or 'USD',
                'unit': profile.get('unit_override') or item.get(f'{value_field}-units') or item.get('units') or 'UNKNOWN',
                'assessment_time': item.get('period') or now(),
                'provider': 'U.S. Energy Information Administration Open Data',
                'source_reference': f'{EIA_BASE}{route}/data/',
                'confidence': 95,
                'eia_profile_id': profile.get('profile_id'),
                'eia_sync_id': sync_id,
                'created_at': now(),
            }
            await backend.insert('energy_benchmark_snapshots', snapshot)
            canonical += 1

        if profile_type == 'REFINERY':
            asset = {
                'asset_id': f'ena_{secrets.token_urlsafe(12)}',
                'asset_type': 'REFINERY_DATA_OBSERVATION',
                'name': profile.get('name'),
                'country_code': 'US',
                'location': item.get('area-name') or item.get('state-name') or item.get('state') or item.get('area'),
                'source_reference': f'{EIA_BASE}{route}/data/',
                'observed_at': item.get('period') or now(),
                'confidence': 95,
                'provider': 'U.S. Energy Information Administration Open Data',
                'eia_profile_id': profile.get('profile_id'),
                'eia_sync_id': sync_id,
                'metrics': item,
                'created_at': now(),
                'updated_at': now(),
            }
            await backend.insert('energy_market_assets', asset)
            canonical += 1

    event = {
        'sync_id': sync_id,
        'profile_id': profile.get('profile_id'),
        'profile_name': profile.get('name'),
        'profile_type': profile_type,
        'trigger': trigger,
        'status': 'SUCCESS',
        'source': 'U.S. Energy Information Administration Open Data',
        'source_route': route,
        'records_received': len(data),
        'records_normalized': normalized,
        'canonical_records_created': canonical,
        'response_total': response.get('total'),
        **meta,
        'created_at': now(),
    }
    await backend.insert('energy_eia_syncs', event)
    return event


@app.get('/energy-eia/health')
async def health():
    p = persistent_backend_status()
    return {
        'status': 'ok' if p['configured'] else 'configuration_required',
        'service': 'sahjony-energy-eia-adapter',
        'provider': 'U.S. Energy Information Administration Open Data',
        'api_version': 'v2',
        'api_key_configured': bool(api_key()),
        'profile_driven': True,
        'price_intelligence': True,
        'refinery_intelligence': True,
        'petroleum_market_intelligence': True,
        'automatic_trade_authority': False,
        'fail_closed': True,
        'persistence_provider': p['provider'],
    }


@app.get('/energy-eia/discover')
async def discover(route: str = '', authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    clean = clean_route(route) if route else ''
    url = f'{EIA_BASE}{clean}/' if clean else EIA_BASE
    payload, meta = await fetch_json(url, [('api_key', api_key())])
    return {'provider': 'EIA Open Data', 'route': clean or '/', 'metadata': payload, 'provenance': meta}


@app.post('/energy-eia/profiles')
async def create_profile(payload: EIAProfileIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    route = clean_route(payload.route)
    profile_id = f'eia_profile_{secrets.token_urlsafe(10)}'
    row = {'profile_id': profile_id, **payload.model_dump(), 'route': route, 'created_at': now(), 'updated_at': now()}
    await get_backend().insert('energy_eia_profiles', row)
    return {'profile': row}


@app.get('/energy-eia/profiles')
async def profiles(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_eia_profiles', params={'order': 'updated_at.desc', 'limit': '500'}) or []
    return {'profiles': rows}


@app.post('/energy-eia/profiles/{profile_id}/sync')
async def owner_profile_sync(profile_id: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_eia_profiles', params={'profile_id': f'eq.{profile_id}', 'limit': '1'}) or []
    if not rows:
        raise HTTPException(404, 'EIA profile not found')
    if rows[0].get('enabled') is False:
        raise HTTPException(409, 'EIA profile is disabled')
    return await sync_profile(rows[0], 'OWNER_MANUAL')


@app.get('/energy-eia/cron-sync')
async def cron_sync(authorization: str | None = Header(None, alias='Authorization')):
    cron(authorization)
    if not api_key():
        return {'status': 'SKIPPED', 'reason': 'eia_api_key_not_configured', 'results': []}
    rows = await get_backend().select('energy_eia_profiles', params={'order': 'updated_at.desc', 'limit': '500'}) or []
    results = []
    for row in rows:
        if row.get('enabled') is False:
            continue
        try:
            results.append(await sync_profile(row, 'VERCEL_CRON'))
        except Exception as exc:
            results.append({'profile_id': row.get('profile_id'), 'status': 'FAILED', 'error': type(exc).__name__})
    return {'status': 'ok', 'profiles_processed': len(results), 'results': results}


@app.get('/energy-eia/syncs')
async def syncs(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_eia_syncs', params={'order': 'created_at.desc', 'limit': '500'}) or []
    return {'syncs': rows}
