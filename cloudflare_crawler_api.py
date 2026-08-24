from __future__ import annotations

import ipaddress
import os
import socket
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Cloudflare Research Crawler', version='1.0.0', docs_url=None, redoc_url=None)

CrawlFormat = Literal['markdown', 'html', 'json']


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    token = authorization.removeprefix('Bearer ').strip()
    if not verify_owner_token(token):
        raise HTTPException(403, 'Invalid or expired owner session')


def _config() -> tuple[str, str]:
    account_id = os.getenv('CLOUDFLARE_ACCOUNT_ID', '').strip()
    api_token = os.getenv('CLOUDFLARE_API_TOKEN', '').strip()
    if not account_id or not api_token:
        raise HTTPException(503, 'Cloudflare Browser Rendering is not configured')
    return account_id, api_token


def _api_base(account_id: str) -> str:
    return f'https://api.cloudflare.com/client/v4/accounts/{account_id}/browser-rendering/crawl'


def _public_http_url(value: str) -> str:
    raw = value.strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise HTTPException(400, 'Crawler URL must be a public http(s) URL')
    if parsed.username or parsed.password:
        raise HTTPException(400, 'Embedded URL credentials are not allowed')
    host = parsed.hostname.lower().rstrip('.')
    if host in {'localhost', 'localhost.localdomain'} or host.endswith('.local'):
        raise HTTPException(400, 'Private/local targets are not allowed')
    try:
        literal = ipaddress.ip_address(host)
        if not literal.is_global:
            raise HTTPException(400, 'Private/reserved targets are not allowed')
    except ValueError:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise HTTPException(400, 'Target hostname cannot be resolved') from exc
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                continue
            if not ip.is_global:
                raise HTTPException(400, 'Target resolves to a private/reserved address')
    return raw


class CrawlStartIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    limit: int = Field(default=30, ge=1, le=100)
    depth: int = Field(default=2, ge=0, le=4)
    formats: list[CrawlFormat] = Field(default_factory=lambda: ['markdown'], min_length=1, max_length=3)
    render: bool = False
    include_subdomains: bool = False
    include_patterns: list[str] = Field(default_factory=list, max_length=20)
    exclude_patterns: list[str] = Field(default_factory=list, max_length=20)


async def _request(method: str, url: str, *, json_payload: dict | None = None) -> dict:
    _account_id, token = _config()
    timeout = httpx.Timeout(35.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            method,
            url,
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json=json_payload,
        )
    if response.status_code >= 400:
        detail = response.text[:800]
        raise HTTPException(502, f'Cloudflare crawler request failed ({response.status_code}): {detail}')
    payload = response.json()
    if not payload.get('success', False):
        raise HTTPException(502, 'Cloudflare crawler returned an unsuccessful response')
    return payload


async def _audit(event_type: str, summary: str, payload: dict) -> None:
    try:
        await get_backend().insert('lead_scout_audit', {
            'event_id': f'cfa_{os.urandom(9).hex()}',
            'lead_id': payload.get('lead_id'),
            'event_type': event_type,
            'summary': summary,
            'payload': payload,
            'created_at': now(),
        })
    except Exception:
        # Crawler availability must not depend on optional audit-table availability.
        pass


@app.get('/crawler/health')
async def health():
    account_id = bool(os.getenv('CLOUDFLARE_ACCOUNT_ID', '').strip())
    api_token = bool(os.getenv('CLOUDFLARE_API_TOKEN', '').strip())
    configured = account_id and api_token
    return {
        'status': 'ok' if configured else 'configuration_required',
        'service': 'cloudflare-browser-rendering-crawler',
        'version': '1.0.0',
        'configured': configured,
        'account_id_configured': account_id,
        'api_token_configured': api_token,
        'credential_values_exposed': False,
        'public_http_targets_only': True,
        'embedded_credentials_allowed': False,
        'private_network_targets_allowed': False,
        'robots_and_site_guidance': 'ENFORCED_BY_CLOUDFLARE_CRAWL_DEFAULTS',
        'captcha_bypass': False,
        'max_page_limit': 100,
        'max_depth': 4,
        'autonomous_binding_outreach': False,
    }


@app.post('/crawler/jobs')
async def start_crawl(p: CrawlStartIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    account_id, _token = _config()
    target = _public_http_url(p.url)
    payload: dict = {
        'url': target,
        'crawlPurposes': ['search'],
        'limit': p.limit,
        'depth': p.depth,
        'formats': list(dict.fromkeys(p.formats)),
        'render': p.render,
        'source': 'all',
        'options': {
            'includeExternalLinks': False,
            'includeSubdomains': p.include_subdomains,
        },
    }
    if p.include_patterns:
        payload['options']['includePatterns'] = p.include_patterns
    if p.exclude_patterns:
        payload['options']['excludePatterns'] = p.exclude_patterns
    response = await _request('POST', _api_base(account_id), json_payload=payload)
    job_id = str(response.get('result') or '')
    if not job_id:
        raise HTTPException(502, 'Cloudflare crawler did not return a job id')
    await _audit('cloudflare_crawl_started', 'Cloudflare evidence crawl started', {
        'crawl_job_id': job_id,
        'url': target,
        'limit': p.limit,
        'depth': p.depth,
        'render': p.render,
    })
    return {
        'job_id': job_id,
        'status': 'QUEUED',
        'url': target,
        'limit': p.limit,
        'depth': p.depth,
        'formats': payload['formats'],
        'render': p.render,
        'authority': 'RESEARCH_AND_EVIDENCE_ONLY',
    }


@app.get('/crawler/jobs/{job_id}')
async def crawl_result(
    job_id: str,
    authorization: str | None = Header(None, alias='Authorization'),
    cursor: str | None = Query(default=None, max_length=500),
):
    owner(authorization)
    account_id, _token = _config()
    url = f'{_api_base(account_id)}/{job_id}'
    if cursor:
        url += f'?cursor={cursor}'
    response = await _request('GET', url)
    result = response.get('result') or {}
    records = result.get('records') or []
    safe_records = []
    for record in records[:100]:
        if not isinstance(record, dict):
            continue
        safe_records.append({
            'status': record.get('status'),
            'url': record.get('url'),
            'metadata': record.get('metadata'),
            'markdown': record.get('markdown'),
            'html': record.get('html'),
            'json': record.get('json'),
        })
    return {
        'job_id': result.get('id') or job_id,
        'status': result.get('status'),
        'total': result.get('total'),
        'finished': result.get('finished'),
        'skipped': result.get('skipped'),
        'browser_seconds_used': result.get('browserSecondsUsed'),
        'cursor': result.get('cursor'),
        'records': safe_records,
    }


@app.delete('/crawler/jobs/{job_id}')
async def cancel_crawl(job_id: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    account_id, _token = _config()
    response = await _request('DELETE', f'{_api_base(account_id)}/{job_id}')
    await _audit('cloudflare_crawl_cancelled', 'Cloudflare evidence crawl cancelled', {'crawl_job_id': job_id})
    return {'job_id': job_id, 'status': 'CANCEL_REQUESTED', 'result': response.get('result')}


@app.post('/crawler/leads/{lead_id}/verify')
async def verify_lead_site(lead_id: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('lead_scout_leads', params={'lead_id': f'eq.{lead_id}', 'limit': '1'}) or []
    if not rows:
        raise HTTPException(404, 'Lead not found')
    lead = rows[0]
    target = str(lead.get('website') or lead.get('source_url') or '').strip()
    if not target:
        raise HTTPException(409, 'Lead has no website or source URL to crawl')
    target = _public_http_url(target)
    account_id, _token = _config()
    payload = {
        'url': target,
        'crawlPurposes': ['search'],
        'limit': 20,
        'depth': 2,
        'formats': ['markdown'],
        'render': False,
        'source': 'all',
        'options': {'includeExternalLinks': False, 'includeSubdomains': False},
    }
    response = await _request('POST', _api_base(account_id), json_payload=payload)
    job_id = str(response.get('result') or '')
    if not job_id:
        raise HTTPException(502, 'Cloudflare crawler did not return a job id')
    await _audit('cloudflare_lead_verification_started', 'Cloudflare lead website verification started', {
        'lead_id': lead_id,
        'crawl_job_id': job_id,
        'url': target,
    })
    return {
        'lead_id': lead_id,
        'job_id': job_id,
        'status': 'QUEUED',
        'url': target,
        'purpose': 'PUBLIC_EVIDENCE_VERIFICATION',
        'binding_authority': False,
    }
