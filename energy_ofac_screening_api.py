from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import secrets
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Energy OFAC Screening', version='1.0.0', docs_url=None, redoc_url=None)

OFAC_BASE = 'https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/'
OFAC_FILES = {
    'primary': 'SDN.CSV',
    'aliases': 'ALT.CSV',
    'addresses': 'ADD.CSV',
    'comments': 'SDN_COMMENTS.CSV',
}
USER_AGENT = 'SAHJONY-Energy-OFAC-Screening/1.0 (+https://www.sahjony.com)'


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def clean(value: Any) -> str | None:
    s = str(value or '').strip().strip('"')
    if not s or s == '-0-':
        return None
    return s


def norm_name(value: str | None) -> str:
    s = (value or '').upper()
    s = re.sub(r'[^A-Z0-9 ]+', ' ', s)
    return ' '.join(s.split())


def parse_programs(value: str | None) -> list[str]:
    if not value:
        return []
    raw = value.replace('][', '] [').replace(';', ' ')
    tokens = re.findall(r'\[([^]]+)\]', raw)
    if tokens:
        return [x.strip() for x in tokens if x.strip()]
    return [x.strip() for x in raw.split() if x.strip()]


def primary_row(fields: list[str]) -> dict:
    f = fields + [''] * 12
    return {
        'ofac_uid': clean(f[0]),
        'primary_name': clean(f[1]),
        'sdn_type': clean(f[2]),
        'programs': parse_programs(clean(f[3])),
        'title': clean(f[4]),
        'call_sign': clean(f[5]),
        'vessel_type': clean(f[6]),
        'tonnage': clean(f[7]),
        'gross_registered_tonnage': clean(f[8]),
        'vessel_flag': clean(f[9]),
        'vessel_owner': clean(f[10]),
        'remarks': clean(f[11]),
    }


def alias_row(fields: list[str]) -> dict:
    f = fields + [''] * 5
    return {
        'ofac_uid': clean(f[0]),
        'alias_num': clean(f[1]),
        'alias_type': clean(f[2]),
        'alias_name': clean(f[3]),
        'alias_remarks': clean(f[4]),
    }


def address_row(fields: list[str]) -> dict:
    f = fields + [''] * 8
    return {
        'ofac_uid': clean(f[0]),
        'address_num': clean(f[1]),
        'address': clean(f[2]),
        'city_state_province_postal': clean(f[3]),
        'country': clean(f[4]),
        'address_remarks': clean(f[5]),
        'raw_tail': [clean(x) for x in f[6:] if clean(x)],
    }


def comment_row(fields: list[str]) -> dict:
    f = fields + [''] * 2
    return {'ofac_uid': clean(f[0]), 'comments': clean(f[1])}


async def fetch_csv(client: httpx.AsyncClient, filename: str) -> tuple[list[list[str]], dict]:
    url = OFAC_BASE + filename
    response = await client.get(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/csv,text/plain,*/*'})
    response.raise_for_status()
    body = response.content
    text = body.decode('utf-8-sig', errors='replace')
    rows = list(csv.reader(io.StringIO(text)))
    return rows, {
        'filename': filename,
        'source_url': url,
        'http_status': response.status_code,
        'sha256': hashlib.sha256(body).hexdigest(),
        'bytes': len(body),
        'row_count': len(rows),
    }


async def sync_all(trigger: str) -> dict:
    backend = get_backend()
    sync_id = f'ofac_{secrets.token_urlsafe(12)}'
    started = datetime.now(timezone.utc)
    manifests = {}
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            primary_rows, manifests['primary'] = await fetch_csv(client, OFAC_FILES['primary'])
            alias_rows, manifests['aliases'] = await fetch_csv(client, OFAC_FILES['aliases'])
            address_rows, manifests['addresses'] = await fetch_csv(client, OFAC_FILES['addresses'])
            comment_rows, manifests['comments'] = await fetch_csv(client, OFAC_FILES['comments'])
    except Exception as exc:
        event = {
            'sync_id': sync_id, 'status': 'FAILED', 'trigger': trigger,
            'error': type(exc).__name__, 'files': manifests, 'created_at': now(),
        }
        await backend.insert('energy_ofac_syncs', event)
        raise HTTPException(502, event)

    primary = [primary_row(x) for x in primary_rows if x and clean(x[0])]
    aliases = [alias_row(x) for x in alias_rows if x and clean(x[0])]
    addresses = [address_row(x) for x in address_rows if x and clean(x[0])]
    comments = [comment_row(x) for x in comment_rows if x and clean(x[0])]

    alias_map: dict[str, list[dict]] = {}
    for row in aliases:
        alias_map.setdefault(str(row['ofac_uid']), []).append(row)
    address_map: dict[str, list[dict]] = {}
    for row in addresses:
        address_map.setdefault(str(row['ofac_uid']), []).append(row)
    comment_map = {str(x['ofac_uid']): x.get('comments') for x in comments}

    count = 0
    for row in primary:
        uid = str(row['ofac_uid'])
        joined = {
            'record_id': f'ofac:{uid}',
            **row,
            'normalized_primary_name': norm_name(row.get('primary_name')),
            'aliases': alias_map.get(uid, []),
            'addresses': address_map.get(uid, []),
            'overflow_comments': comment_map.get(uid),
            'source': 'U.S. Treasury OFAC Sanctions List Service',
            'source_series': ['SDN.CSV', 'ALT.CSV', 'ADD.CSV', 'SDN_COMMENTS.CSV'],
            'sync_id': sync_id,
            'synced_at': now(),
        }
        await backend.insert('energy_ofac_sdn_records', joined)
        count += 1

    finished = datetime.now(timezone.utc)
    event = {
        'sync_id': sync_id,
        'status': 'SUCCESS',
        'trigger': trigger,
        'primary_records': count,
        'alias_records': len(aliases),
        'address_records': len(addresses),
        'comment_records': len(comments),
        'files': manifests,
        'latency_ms': round((finished - started).total_seconds() * 1000),
        'complete_legacy_series': all(k in manifests for k in OFAC_FILES),
        'created_at': now(),
    }
    await backend.insert('energy_ofac_syncs', event)
    return event


class ScreenIn(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    country: str | None = Field(default=None, max_length=120)
    imo: str | None = Field(default=None, max_length=30)
    deal_id: str | None = Field(default=None, max_length=180)
    minimum_fuzzy_score: int = Field(default=88, ge=50, le=100)
    max_results: int = Field(default=20, ge=1, le=100)


def extract_imo(record: dict) -> list[str]:
    hay = ' '.join(str(record.get(k) or '') for k in ('remarks', 'overflow_comments', 'call_sign'))
    for a in record.get('aliases') or []:
        hay += ' ' + str(a.get('alias_remarks') or '')
    values = re.findall(r'\bIMO\s*[:#-]?\s*(\d{7})\b', hay, flags=re.I)
    return sorted(set(values))


def country_match(record: dict, country: str | None) -> bool:
    if not country:
        return True
    target = norm_name(country)
    for a in record.get('addresses') or []:
        if target and target in norm_name(a.get('country')):
            return True
    return False


@app.get('/energy-ofac/health')
async def health():
    p = persistent_backend_status()
    latest = []
    if p['configured']:
        latest = await get_backend().select('energy_ofac_syncs', params={'order': 'created_at.desc', 'limit': '1'}) or []
    row = latest[0] if latest else {}
    return {
        'status': 'ok' if p['configured'] else 'configuration_required',
        'service': 'sahjony-energy-ofac-screening',
        'official_source': 'U.S. Treasury OFAC Sanctions List Service',
        'complete_legacy_series_required': True,
        'files': list(OFAC_FILES.values()),
        'last_sync_status': row.get('status'),
        'last_sync_at': row.get('created_at'),
        'last_sync_complete': bool(row.get('complete_legacy_series')),
        'negative_result_is_compliance_clearance': False,
        'automatic_positive_match_hold': True,
        'automatic_compliance_clearance': False,
        'fail_closed': True,
        'persistence_provider': p['provider'],
    }


@app.post('/energy-ofac/sync')
async def owner_sync(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    return await sync_all('OWNER_MANUAL')


@app.get('/energy-ofac/cron-sync')
async def cron_sync(authorization: str | None = Header(None, alias='Authorization')):
    cron(authorization)
    return await sync_all('VERCEL_CRON')


@app.post('/energy-ofac/screen')
async def screen(payload: ScreenIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    backend = get_backend()
    rows = await backend.select('energy_ofac_sdn_records', params={'limit': '25000'}) or []
    if not rows:
        raise HTTPException(409, 'OFAC dataset has not been synchronized yet')

    q = norm_name(payload.name)
    q_imo = re.sub(r'\D', '', payload.imo or '')
    hits = []
    strongest = 'NO_MATCH'

    for row in rows:
        primary = norm_name(row.get('primary_name'))
        alias_names = [norm_name(x.get('alias_name')) for x in (row.get('aliases') or [])]
        names = [primary] + [x for x in alias_names if x]
        exact = q in names if q else False
        best = max([round(SequenceMatcher(None, q, n).ratio() * 100) for n in names if n] or [0])
        imos = extract_imo(row)
        imo_exact = bool(q_imo and q_imo in imos)
        if not exact and not imo_exact and best < payload.minimum_fuzzy_score:
            continue
        c_match = country_match(row, payload.country)
        match_type = 'IMO_EXACT' if imo_exact else ('NAME_EXACT' if exact else 'NAME_FUZZY')
        risk = 'HOLD' if (imo_exact or exact) else 'REVIEW'
        if risk == 'HOLD':
            strongest = 'HOLD'
        elif strongest != 'HOLD':
            strongest = 'REVIEW'
        hits.append({
            'ofac_uid': row.get('ofac_uid'),
            'primary_name': row.get('primary_name'),
            'sdn_type': row.get('sdn_type'),
            'programs': row.get('programs'),
            'match_type': match_type,
            'score': 100 if (exact or imo_exact) else best,
            'country_supports_match': c_match,
            'imos': imos,
            'aliases': [x.get('alias_name') for x in (row.get('aliases') or [])[:20]],
            'addresses': (row.get('addresses') or [])[:10],
            'risk': risk,
            'source': row.get('source'),
            'sync_id': row.get('sync_id'),
        })

    hits.sort(key=lambda x: (x['risk'] == 'HOLD', x['score'], x['country_supports_match']), reverse=True)
    hits = hits[:payload.max_results]
    screening_id = f'ofs_{secrets.token_urlsafe(12)}'
    event = {
        'screening_id': screening_id,
        'name': payload.name,
        'country': payload.country,
        'imo': payload.imo,
        'deal_id': payload.deal_id,
        'result': strongest,
        'match_count': len(hits),
        'matches': hits,
        'source': 'U.S. Treasury OFAC Sanctions List Service',
        'negative_result_is_clearance': False,
        'created_at': now(),
    }
    await backend.insert('energy_ofac_screenings', event)

    if payload.deal_id and strongest == 'HOLD':
        await backend.patch('energy_deals', {
            'stage': 'HOLD', 'release_allowed': False,
            'sanctions_status': 'HOLD', 'updated_at': now(),
        }, params={'deal_id': f'eq.{payload.deal_id}'})
        await backend.insert('energy_sanctions_snapshots', {
            'snapshot_id': f'ens_{secrets.token_urlsafe(12)}',
            'subject_type': 'DEAL', 'subject_id': payload.deal_id,
            'risk': 'HOLD', 'provider': 'U.S. Treasury OFAC SLS',
            'source_reference': OFAC_BASE,
            'checked_at': now(),
            'matched_programs': sorted({p for h in hits for p in (h.get('programs') or [])}),
            'notes': f'Official OFAC strong match screening {screening_id}; owner/compliance review required.',
            'created_at': now(),
        })

    return {
        'screening_id': screening_id,
        'result': strongest,
        'matches': hits,
        'release_effect': 'HOLD' if strongest == 'HOLD' else 'NO_AUTOMATIC_RELEASE',
        'compliance_clearance': False,
        'note': 'A negative or fuzzy-search result is not legal or compliance clearance; owner/compliance review remains required.',
    }


@app.get('/energy-ofac/screenings')
async def screenings(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_ofac_screenings', params={'order': 'created_at.desc', 'limit': '500'}) or []
    return {'screenings': rows}
