from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Energy Provider Ingestion', version='1.0.0', docs_url=None, redoc_url=None)

ProviderKind = Literal['PRICE','AIS','SANCTIONS','REFINERY']

REQUIRED_FIELDS = {
    'PRICE': ['benchmark','price','assessment_time'],
    'AIS': ['imo','vessel_name','observed_at'],
    'SANCTIONS': ['subject_type','subject_id','risk','checked_at'],
    'REFINERY': ['asset_type','name','country_code'],
}

DEST_TABLE = {
    'PRICE': 'energy_benchmark_snapshots',
    'AIS': 'energy_vessel_observations',
    'SANCTIONS': 'energy_sanctions_snapshots',
    'REFINERY': 'energy_market_assets',
}

ID_FIELD = {
    'PRICE': 'snapshot_id',
    'AIS': 'observation_id',
    'SANCTIONS': 'snapshot_id',
    'REFINERY': 'asset_id',
}

ID_PREFIX = {'PRICE':'enb','AIS':'env','SANCTIONS':'ens','REFINERY':'ena'}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


def dig(value: Any, path: str | None) -> Any:
    if path in (None, '', '$'):
        return value
    cur = value
    for part in str(path).strip('.').split('.'):
        if not part:
            continue
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            i = int(part)
            cur = cur[i] if i < len(cur) else None
        else:
            return None
    return cur


def records_at(payload: Any, path: str | None) -> list[Any]:
    value = dig(payload, path)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def mapped_value(record: Any, spec: Any) -> Any:
    if isinstance(spec, str):
        return dig(record, spec)
    if isinstance(spec, dict):
        if 'literal' in spec:
            return spec.get('literal')
        value = dig(record, spec.get('path'))
        if value in (None, '') and 'default' in spec:
            value = spec.get('default')
        transform = str(spec.get('transform') or '').lower()
        if transform == 'upper' and value is not None:
            value = str(value).upper()
        elif transform == 'lower' and value is not None:
            value = str(value).lower()
        elif transform == 'float' and value not in (None, ''):
            try: value = float(value)
            except Exception: value = None
        elif transform == 'int' and value not in (None, ''):
            try: value = int(float(value))
            except Exception: value = None
        return value
    return spec


class MappingIn(BaseModel):
    provider_name: str = Field(min_length=1, max_length=160)
    record_path: str | None = Field(default=None, max_length=500)
    field_map: dict[str, Any]
    enabled: bool = True
    max_records_per_sync: int = Field(default=1000, ge=1, le=5000)
    notes: str | None = Field(default=None, max_length=3000)


async def get_mapping(kind: str, provider_name: str) -> dict | None:
    rows = await get_backend().select('energy_provider_mappings', params={'provider_kind':f'eq.{kind}','provider_name':f'eq.{provider_name}','limit':'20'}) or []
    enabled = [r for r in rows if r.get('enabled') is True]
    return enabled[0] if enabled else None


async def normalize_and_persist(kind: str, provider_name: str, source_reference: str, payload: Any, sync_run_id: str | None = None) -> dict:
    kind = kind.upper()
    mapping = await get_mapping(kind, provider_name)
    if not mapping:
        return {'status':'NO_MAPPING','provider_kind':kind,'provider_name':provider_name,'normalized':0,'rejected':0}
    rows = records_at(payload, mapping.get('record_path'))[:int(mapping.get('max_records_per_sync') or 1000)]
    normalized = 0; rejected = 0; errors = []
    backend = get_backend()
    for idx, record in enumerate(rows):
        out = {}
        for dest, spec in (mapping.get('field_map') or {}).items():
            out[dest] = mapped_value(record, spec)
        missing = [f for f in REQUIRED_FIELDS[kind] if out.get(f) in (None, '')]
        if missing:
            rejected += 1
            errors.append({'index':idx,'missing':missing})
            continue
        out[ID_FIELD[kind]] = f"{ID_PREFIX[kind]}_{secrets.token_urlsafe(12)}"
        out['provider'] = out.get('provider') or provider_name
        out['source_reference'] = out.get('source_reference') or source_reference
        out['provider_sync_run_id'] = sync_run_id
        out['normalized_by'] = 'SAHJONY Energy Provider Ingestion'
        out['created_at'] = now()
        if kind == 'REFINERY':
            out.setdefault('updated_at', now())
        await backend.insert(DEST_TABLE[kind], out)
        normalized += 1
        if kind == 'SANCTIONS' and str(out.get('subject_type')).upper() == 'DEAL' and str(out.get('risk')).upper() in {'HOLD','BLOCKED'}:
            await backend.patch('energy_deals', {'stage':'HOLD','release_allowed':False,'updated_at':now()}, params={'deal_id':f"eq.{out.get('subject_id')}"})
    event = {
        'event_id': f'enp_{secrets.token_urlsafe(12)}', 'provider_kind':kind, 'provider_name':provider_name,
        'sync_run_id':sync_run_id, 'normalized_count':normalized, 'rejected_count':rejected,
        'sample_errors':errors[:25], 'created_at':now(),
    }
    await backend.insert('energy_provider_ingestion_events', event)
    return {'status':'SUCCESS' if normalized else 'NO_VALID_RECORDS','provider_kind':kind,'provider_name':provider_name,'normalized':normalized,'rejected':rejected,'sample_errors':errors[:25]}


@app.get('/energy-ingestion/health')
async def health():
    p = persistent_backend_status()
    return {
        'status':'ok' if p['configured'] else 'configuration_required',
        'service':'sahjony-energy-provider-ingestion',
        'provider_neutral':True,
        'canonical_intelligence_ledger':True,
        'mapping_profiles_durable':p['configured'],
        'raw_payload_required_to_persist':False,
        'automatic_trade_authority':False,
        'fail_closed':True,
        'persistence_provider':p['provider'],
    }


@app.post('/energy-ingestion/mappings/{kind}')
async def upsert_mapping(kind: ProviderKind, p: MappingIn, authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); ts=now()
    mapping_id=f"{kind}:{p.provider_name.strip().lower()}"
    row={'mapping_id':mapping_id,'provider_kind':kind,'provider_name':p.provider_name.strip(),**p.model_dump(exclude={'provider_name'}),'updated_at':ts,'created_at':ts}
    await get_backend().insert('energy_provider_mappings',row)
    return {'mapping':row,'required_fields':REQUIRED_FIELDS[kind]}


@app.get('/energy-ingestion/mappings')
async def list_mappings(authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization)
    rows=await get_backend().select('energy_provider_mappings',params={'order':'updated_at.desc','limit':'200'}) or []
    return {'mappings':rows,'required_fields':REQUIRED_FIELDS}


@app.get('/energy-ingestion/events')
async def events(authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization)
    rows=await get_backend().select('energy_provider_ingestion_events',params={'order':'created_at.desc','limit':'500'}) or []
    return {'events':rows}
