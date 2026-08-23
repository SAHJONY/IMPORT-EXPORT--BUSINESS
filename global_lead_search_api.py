from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from country_crm_api import COUNTRIES, DEFAULT_DEPARTMENTS, country_code
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Global Lead Search', version='1.0.0', docs_url=None, redoc_url=None)

LeadType = Literal['IMPORT_NEED','EXPORT_OFFER','SUPPLIER','BUYER','DISTRIBUTOR','PARTNER','OTHER']

LANGUAGE = {
    'CU':'es','US':'en','MX':'es','DO':'es','PA':'es','CO':'es','BR':'pt','CL':'es','PE':'es',
    'CR':'es','GT':'es','CA':'en','ES':'es','GB':'en','DE':'de','NL':'nl','TR':'tr','AE':'en',
    'IN':'en','VN':'vi','CN':'zh',
}

REGION = {
    'CU':'Caribbean','US':'North America','MX':'North America','DO':'Caribbean','PA':'Central America',
    'CO':'South America','BR':'South America','CL':'South America','PE':'South America','CR':'Central America',
    'GT':'Central America','CA':'North America','ES':'Europe','GB':'Europe','DE':'Europe','NL':'Europe',
    'TR':'Europe / West Asia','AE':'Middle East','IN':'South Asia','VN':'Southeast Asia','CN':'East Asia',
}

SECTOR_PRIORITIES = {
    'CU':['food & beverage','construction materials','hospitality supplies','industrial equipment','agriculture inputs','consumer goods'],
    'US':['importers','distributors','wholesalers','retail procurement','industrial buyers','exporters'],
    'MX':['industrial manufacturing','auto supply','food & beverage','construction','packaging','consumer goods'],
    'DO':['hospitality','food & beverage','construction','retail distribution','industrial supplies'],
    'PA':['logistics','distribution','construction','hospitality','consumer goods'],
    'CO':['food & beverage','textiles','construction','industrial supplies','consumer goods'],
    'BR':['agriculture','food','industrial manufacturing','chemicals','construction','consumer goods'],
    'CL':['mining supply','food','industrial equipment','construction','retail distribution'],
    'PE':['mining supply','agriculture','food','construction','industrial equipment'],
    'CR':['medical devices','electronics','food','hospitality','distribution'],
    'GT':['textiles','food','construction','agriculture','distribution'],
    'CA':['food','industrial supply','consumer goods','construction','distribution'],
    'ES':['food','industrial equipment','consumer goods','hospitality','distribution'],
    'GB':['importers','wholesalers','food','consumer goods','industrial procurement'],
    'DE':['industrial machinery','automotive','chemicals','electronics','distribution'],
    'NL':['logistics','distribution','food','agriculture','industrial supply'],
    'TR':['textiles','machinery','construction materials','food','consumer goods'],
    'AE':['re-export','hospitality','construction','food','luxury retail','industrial procurement'],
    'IN':['industrial manufacturing','textiles','pharma inputs','food','engineering products'],
    'VN':['electronics','furniture','textiles','food','industrial manufacturing'],
    'CN':['manufacturing','electronics','machinery','packaging','consumer goods','industrial components'],
}

SOURCE_CLASSES = [
    'official business registries and chambers',
    'company websites and public contact pages',
    'trade associations and industry directories',
    'trade fairs and exhibitor directories',
    'importer/distributor directories',
    'manufacturer/exporter directories',
    'public procurement and commercial opportunity notices',
    'professional networks and public business profiles',
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(authorization.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


def department_config(code: str) -> dict:
    c = country_code(code)
    if c == 'UN':
        raise HTTPException(400, 'A recognized country code or country name is required')
    return {
        'country_code': c,
        'country_name': COUNTRIES.get(c, c),
        'region': REGION.get(c, 'Global'),
        'primary_language': LANGUAGE.get(c, 'en'),
        'cuba_dedicated_department': c == 'CU',
        'sector_priorities': SECTOR_PRIORITIES.get(c, ['importers','distributors','buyers','suppliers']),
        'target_lead_types': ['IMPORT_NEED','BUYER','DISTRIBUTOR','SUPPLIER','EXPORT_OFFER','PARTNER'],
        'source_classes': SOURCE_CLASSES,
        'routing': f'country-crm:{c}',
        'outbound_authority': 'DRAFT_AND_QUALIFY_ONLY',
        'binding_commitments': 'OWNER_APPROVAL_REQUIRED',
    }


class SearchJobIn(BaseModel):
    country: str = Field(min_length=2, max_length=80)
    sectors: list[str] = Field(default_factory=list, max_length=20)
    lead_types: list[LeadType] = Field(default_factory=list, max_length=7)
    target_count: int = Field(default=25, ge=1, le=500)
    search_notes: str | None = Field(default=None, max_length=3000)


class CandidateIn(BaseModel):
    job_id: str | None = Field(default=None, max_length=160)
    country: str = Field(min_length=2, max_length=80)
    business_name: str = Field(min_length=2, max_length=240)
    contact_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=80)
    city_region: str | None = Field(default=None, max_length=160)
    website: str | None = Field(default=None, max_length=1200)
    lead_type: LeadType = 'OTHER'
    product_need_or_offer: str = Field(min_length=3, max_length=1800)
    estimated_deal_value: float | None = Field(default=None, ge=0)
    currency: str = Field(default='USD', min_length=3, max_length=3)
    source_url: str = Field(min_length=8, max_length=1200)
    source_description: str | None = Field(default=None, max_length=800)
    evidence_urls: list[str] = Field(default_factory=list, max_length=8)
    confidence: int = Field(default=60, ge=0, le=100)


def fingerprint(p: CandidateIn, code: str) -> str:
    basis = '|'.join([
        p.business_name.strip().lower(),
        (p.email or '').strip().lower(),
        (p.phone or '').strip().lower(),
        (p.website or '').strip().lower(),
        code,
    ])
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


def score(p: CandidateIn) -> int:
    value = 25
    if p.email or p.phone: value += 15
    if p.website: value += 8
    if p.contact_name: value += 7
    if p.source_url: value += 10
    if p.evidence_urls: value += min(10, len(p.evidence_urls) * 3)
    if p.lead_type != 'OTHER': value += 8
    if len(p.product_need_or_offer.strip()) >= 40: value += 7
    if p.estimated_deal_value: value += 5
    value += round(max(0, min(100, p.confidence)) * 0.05)
    return min(100, value)


def priority(value: int) -> str:
    if value >= 75: return 'HIGH'
    if value >= 55: return 'MEDIUM'
    return 'STANDARD'


@app.get('/lead-search/health')
async def health():
    persistence = persistent_backend_status()
    return {
        'status': 'ok' if persistence['configured'] else 'configuration_required',
        'service': 'global-country-lead-search',
        'country_routing': True,
        'country_ai_briefs': True,
        'deduplication': True,
        'automatic_scoring': True,
        'cuba_department_preserved': True,
        'default_country_departments': DEFAULT_DEPARTMENTS,
        'persistence_provider': persistence['provider'],
        'autonomous_binding_outreach': False,
    }


@app.get('/lead-search/countries')
async def countries(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    return {'countries': [department_config(c) for c in DEFAULT_DEPARTMENTS]}


@app.get('/lead-search/countries/{code}')
async def country_brief(code: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    return department_config(code)


@app.post('/lead-search/jobs')
async def create_job(p: SearchJobIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    backend = get_backend()
    config = department_config(p.country)
    job_id = f'gls_{secrets.token_urlsafe(10)}'
    sectors = [x.strip() for x in p.sectors if x.strip()] or config['sector_priorities']
    lead_types = p.lead_types or config['target_lead_types']
    row = {
        'job_id': job_id,
        'country_code': config['country_code'],
        'country_name': config['country_name'],
        'primary_language': config['primary_language'],
        'sectors': sectors,
        'lead_types': lead_types,
        'target_count': p.target_count,
        'search_notes': p.search_notes,
        'source_classes': config['source_classes'],
        'status': 'RESEARCH_QUEUED',
        'candidate_count': 0,
        'accepted_count': 0,
        'routing_department': config['routing'],
        'authority': 'RESEARCH_AND_QUALIFICATION_ONLY',
        'created_at': now(),
        'updated_at': now(),
    }
    await backend.insert('global_lead_search_jobs', row)
    return {'job': row, 'country_agent_brief': config}


@app.get('/lead-search/jobs')
async def list_jobs(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('global_lead_search_jobs', params={'order':'updated_at.desc','limit':'500'}) or []
    return {'jobs': rows}


@app.post('/lead-search/candidates')
async def ingest_candidate(p: CandidateIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    backend = get_backend()
    code = department_config(p.country)['country_code']
    fp = fingerprint(p, code)
    existing = await backend.select('lead_scout_leads', params={'fingerprint': f'eq.{fp}', 'limit': '1'}) or []
    points = score(p)
    duplicate_of = existing[0].get('lead_id') if existing else None
    lead_id = f'lsl_{secrets.token_urlsafe(10)}'
    row = {
        'lead_id': lead_id,
        'fingerprint': fp,
        'scout_name': 'SAHJONY Country AI Lead Agent',
        'scout_code': f'AI-{code}',
        'scout_contact': None,
        'business_name': p.business_name.strip(),
        'contact_name': (p.contact_name or '').strip() or None,
        'email': (p.email or '').strip().lower() or None,
        'phone': (p.phone or '').strip() or None,
        'country': code,
        'city_region': (p.city_region or '').strip() or None,
        'deal_side': 'OTHER',
        'lead_type': p.lead_type,
        'product_need_or_offer': p.product_need_or_offer.strip(),
        'estimated_deal_value': p.estimated_deal_value,
        'currency': p.currency.upper(),
        'source_url': p.source_url.strip(),
        'source_description': (p.source_description or '').strip() or None,
        'evidence_urls': p.evidence_urls,
        'notes': f'Country AI lead-search candidate. Job: {p.job_id or "unassigned"}. Confidence: {p.confidence}/100.',
        'consent_to_business_contact': False,
        'opportunity_score': points,
        'qualification_priority': priority(points),
        'status': 'DUPLICATE_REVIEW' if duplicate_of else 'NEW',
        'duplicate_candidate': bool(duplicate_of),
        'duplicate_of_lead_id': duplicate_of,
        'referral_credit_status': 'NOT_APPLICABLE',
        'commission_status': 'NOT_APPLICABLE',
        'country_department': code,
        'lead_search_job_id': p.job_id,
        'created_at': now(),
        'updated_at': now(),
    }
    await backend.insert('lead_scout_leads', row)
    await backend.insert('lead_scout_audit', {
        'event_id': f'lsa_{secrets.token_urlsafe(10)}',
        'lead_id': lead_id,
        'event_type': 'country_ai_candidate_ingested',
        'summary': f'Country AI lead candidate routed to {COUNTRIES.get(code, code)} CRM department',
        'payload': {'country_code': code, 'job_id': p.job_id, 'score': points, 'confidence': p.confidence, 'duplicate_candidate': bool(duplicate_of)},
        'created_at': now(),
    })
    if p.job_id:
        jobs = await backend.select('global_lead_search_jobs', params={'job_id': f'eq.{p.job_id}', 'limit':'1'}) or []
        if jobs:
            current = jobs[0]
            await backend.patch('global_lead_search_jobs', {
                'candidate_count': int(current.get('candidate_count') or 0) + 1,
                'accepted_count': int(current.get('accepted_count') or 0) + (0 if duplicate_of else 1),
                'status': 'CANDIDATES_FOUND',
                'updated_at': now(),
            }, params={'job_id': f'eq.{p.job_id}'})
    return {
        'lead_id': lead_id,
        'country_department': code,
        'country_name': COUNTRIES.get(code, code),
        'opportunity_score': points,
        'qualification_priority': priority(points),
        'duplicate_candidate': bool(duplicate_of),
        'routing': f'/owner/crm-countries?country={code}',
    }
