from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, ValidationError

from auth import verify_owner_token
from country_crm_api import COUNTRIES, DEFAULT_DEPARTMENTS, country_code
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Global Lead Search', version='1.1.1', docs_url=None, redoc_url=None)

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


async def _persist_candidate(p: CandidateIn) -> dict:
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
                'status': 'RESEARCH_RUNNING',
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


def _candidate_schema() -> dict:
    nullable_string = {'type': ['string', 'null']}
    nullable_number = {'type': ['number', 'null'], 'minimum': 0}
    return {
        'type': 'object',
        'properties': {
            'candidates': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'business_name': {'type': 'string'},
                        'contact_name': nullable_string,
                        'email': nullable_string,
                        'phone': nullable_string,
                        'city_region': nullable_string,
                        'website': nullable_string,
                        'lead_type': {'type': 'string', 'enum': ['IMPORT_NEED','EXPORT_OFFER','SUPPLIER','BUYER','DISTRIBUTOR','PARTNER','OTHER']},
                        'product_need_or_offer': {'type': 'string'},
                        'estimated_deal_value': nullable_number,
                        'currency': {'type': 'string'},
                        'source_url': {'type': 'string'},
                        'source_description': nullable_string,
                        'evidence_urls': {'type': 'array', 'items': {'type': 'string'}},
                        'confidence': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                    },
                    'required': ['business_name','contact_name','email','phone','city_region','website','lead_type','product_need_or_offer','estimated_deal_value','currency','source_url','source_description','evidence_urls','confidence'],
                    'additionalProperties': False,
                },
            }
        },
        'required': ['candidates'],
        'additionalProperties': False,
    }


def _extract_output_text(payload: dict) -> str:
    if isinstance(payload.get('output_text'), str):
        return payload['output_text']
    chunks: list[str] = []
    for item in payload.get('output') or []:
        if not isinstance(item, dict) or item.get('type') != 'message':
            continue
        for content in item.get('content') or []:
            if isinstance(content, dict) and content.get('type') in {'output_text', 'text'} and isinstance(content.get('text'), str):
                chunks.append(content['text'])
    return '\n'.join(chunks).strip()


async def _research_with_openai(job: dict, remaining: int) -> list[CandidateIn]:
    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('OPENAI_API_KEY is not configured')
    batch_size = max(1, min(remaining, 25))
    code = str(job.get('country_code') or '')
    cuba_rules = ''
    if code == 'CU':
        cuba_rules = (
            'CUBA-SPECIFIC RULE: research only independently owned Cuban private-sector businesses/MIPYMES or self-employed commercial businesses. '
            'Do not characterize state-owned enterprises, military-linked entities, sanctioned parties, or restricted parties as eligible leads. '
            'Research is informational only; do not advise sanctions evasion or execute outreach/transactions. Use public evidence and flag uncertainty by lowering confidence.'
        )
    prompt = f'''You are the SAHJONY Global Trade lead-research agent. Use web search to find up to {batch_size} REAL, current commercial organizations in {job.get('country_name')} ({code}) that fit these sectors: {', '.join(job.get('sectors') or [])}. Target lead types: {', '.join(job.get('lead_types') or [])}. Search notes: {job.get('search_notes') or 'none'}.

Rules:
- Every candidate must be grounded in public web evidence. Never invent a business, URL, person, email, phone, need, product, or deal value.
- Prefer primary sources (company website/contact page, chamber/registry, trade association, exhibitor directory, public procurement notice). Use directories only when they identify a real business.
- source_url must be a URL actually supporting the candidate. evidence_urls should contain up to 5 additional supporting URLs.
- Only include email/phone/contact_name if visible in the public evidence. Otherwise return null.
- product_need_or_offer must state the evidence-backed commercial relevance and must not pretend a purchase intent exists unless the source establishes it.
- estimated_deal_value must be null unless a public source supports a value.
- confidence 80+ requires strong primary-source evidence; lower it for secondary/ambiguous evidence.
- Exclude obvious duplicates and businesses without enough evidence to identify them.
- This agent researches and qualifies only. It cannot make offers, promises, binding commitments, or send outreach.
{cuba_rules}
Return only the requested structured candidate data.'''
    request_payload = {
        'model': os.getenv('OPENAI_FAST_MODEL', '').strip() or os.getenv('OPENAI_PRIMARY_MODEL', '').strip() or 'gpt-5.6-sol',
        'input': prompt,
        'tools': [{'type': 'web_search'}],
        'tool_choice': 'auto',
        'include': ['web_search_call.action.sources'],
        'text': {
            'format': {
                'type': 'json_schema',
                'name': 'global_trade_lead_research',
                'strict': True,
                'schema': _candidate_schema(),
            }
        },
        'max_output_tokens': 12000,
        'store': False,
    }
    timeout = httpx.Timeout(90.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            'https://api.openai.com/v1/responses',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json=request_payload,
        )
    if response.status_code >= 400:
        detail = response.text[:1200]
        raise RuntimeError(f'OpenAI research request failed ({response.status_code}): {detail}')
    raw_text = _extract_output_text(response.json())
    if not raw_text:
        raise RuntimeError('OpenAI research returned no structured output')
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError('OpenAI research returned invalid JSON') from exc
    candidates: list[CandidateIn] = []
    for raw in parsed.get('candidates') or []:
        if len(candidates) >= batch_size:
            break
        raw['job_id'] = job.get('job_id')
        raw['country'] = code
        try:
            candidates.append(CandidateIn.model_validate(raw))
        except ValidationError:
            continue
    return candidates


@app.get('/lead-search/health')
async def health():
    persistence = persistent_backend_status()
    openai_configured = bool(os.getenv('OPENAI_API_KEY', '').strip())
    return {
        'status': 'ok' if persistence['configured'] and openai_configured else 'configuration_required',
        'service': 'global-country-lead-search',
        'version': '1.1.1',
        'country_routing': True,
        'country_ai_briefs': True,
        'deduplication': True,
        'automatic_scoring': True,
        'autonomous_research_runner': True,
        'openai_web_research_configured': openai_configured,
        'cuba_department_preserved': True,
        'cuba_private_sector_research_guardrail': True,
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
    return {'job': row, 'country_agent_brief': config, 'next_action': f'/lead-search/jobs/{job_id}/run'}


@app.get('/lead-search/jobs')
async def list_jobs(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('global_lead_search_jobs', params={'order':'updated_at.desc','limit':'500'}) or []
    return {'jobs': rows}


@app.post('/lead-search/jobs/{job_id}/run')
async def run_job(job_id: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    backend = get_backend()
    jobs = await backend.select('global_lead_search_jobs', params={'job_id': f'eq.{job_id}', 'limit':'1'}) or []
    if not jobs:
        raise HTTPException(404, 'Lead research job not found')
    job = jobs[0]
    target = int(job.get('target_count') or 0)
    accepted_before = int(job.get('accepted_count') or 0)
    remaining = max(0, target - accepted_before)
    if remaining <= 0:
        await backend.patch('global_lead_search_jobs', {'status':'RESEARCH_COMPLETED','updated_at':now()}, params={'job_id':f'eq.{job_id}'})
        return {'job_id': job_id, 'status':'RESEARCH_COMPLETED', 'candidate_count':int(job.get('candidate_count') or 0), 'accepted_count':accepted_before, 'target_count':target, 'inserted':0, 'duplicates':0}
    await backend.patch('global_lead_search_jobs', {'status':'RESEARCH_RUNNING','updated_at':now()}, params={'job_id':f'eq.{job_id}'})
    try:
        candidates = await _research_with_openai(job, remaining)
        inserted = 0
        duplicates = 0
        for candidate in candidates:
            result = await _persist_candidate(candidate)
            if result['duplicate_candidate']:
                duplicates += 1
            else:
                inserted += 1
        refreshed_rows = await backend.select('global_lead_search_jobs', params={'job_id': f'eq.{job_id}', 'limit':'1'}) or []
        refreshed = refreshed_rows[0] if refreshed_rows else job
        accepted = int(refreshed.get('accepted_count') or 0)
        candidates_total = int(refreshed.get('candidate_count') or 0)
        final_status = 'RESEARCH_COMPLETED' if accepted >= target else ('RESEARCH_PARTIAL' if candidates else 'RESEARCH_NO_RESULTS')
        await backend.patch('global_lead_search_jobs', {'status':final_status,'updated_at':now()}, params={'job_id':f'eq.{job_id}'})
        return {'job_id': job_id, 'status':final_status, 'candidate_count':candidates_total, 'accepted_count':accepted, 'target_count':target, 'inserted':inserted, 'duplicates':duplicates}
    except Exception as exc:
        await backend.patch('global_lead_search_jobs', {'status':'RESEARCH_FAILED','updated_at':now()}, params={'job_id':f'eq.{job_id}'})
        raise HTTPException(502, f'Lead research execution failed: {type(exc).__name__}: {str(exc)[:500]}') from exc


@app.post('/lead-search/candidates')
async def ingest_candidate(p: CandidateIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    return await _persist_candidate(p)
