from __future__ import annotations

from collections import defaultdict
from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Country CRM', version='1.0.0', docs_url=None, redoc_url=None)

COUNTRIES = {
    'CU': 'Cuba', 'US': 'United States', 'MX': 'Mexico', 'DO': 'Dominican Republic',
    'PA': 'Panama', 'CO': 'Colombia', 'BR': 'Brazil', 'CL': 'Chile', 'PE': 'Peru',
    'CR': 'Costa Rica', 'GT': 'Guatemala', 'CA': 'Canada', 'ES': 'Spain',
    'GB': 'United Kingdom', 'DE': 'Germany', 'NL': 'Netherlands', 'TR': 'Türkiye',
    'AE': 'United Arab Emirates', 'IN': 'India', 'VN': 'Vietnam', 'CN': 'China',
}

ALIASES = {
    'cuba': 'CU', 'united states': 'US', 'usa': 'US', 'u.s.': 'US', 'us': 'US',
    'mexico': 'MX', 'méxico': 'MX', 'dominican republic': 'DO', 'república dominicana': 'DO',
    'panama': 'PA', 'panamá': 'PA', 'colombia': 'CO', 'brazil': 'BR', 'brasil': 'BR',
    'chile': 'CL', 'peru': 'PE', 'perú': 'PE', 'costa rica': 'CR', 'guatemala': 'GT',
    'canada': 'CA', 'canadá': 'CA', 'spain': 'ES', 'españa': 'ES',
    'united kingdom': 'GB', 'uk': 'GB', 'great britain': 'GB', 'germany': 'DE', 'alemania': 'DE',
    'netherlands': 'NL', 'holland': 'NL', 'países bajos': 'NL', 'turkey': 'TR', 'türkiye': 'TR',
    'united arab emirates': 'AE', 'uae': 'AE', 'emiratos árabes unidos': 'AE',
    'india': 'IN', 'vietnam': 'VN', 'viet nam': 'VN', 'china': 'CN',
}

# Cuba is permanently visible; the other entries are the first global search departments.
DEFAULT_DEPARTMENTS = ['CU','US','MX','DO','PA','CO','BR','CL','PE','CR','GT','CA','ES','GB','DE','NL','TR','AE','IN','VN','CN']


def owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(authorization.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


def country_code(value: str | None) -> str:
    raw = str(value or '').strip()
    if not raw:
        return 'UN'
    upper = raw.upper()
    if len(upper) == 2 and upper.isalpha():
        return upper
    return ALIASES.get(raw.lower(), 'UN')


def department(code: str) -> dict:
    return {
        'country_code': code,
        'country_name': COUNTRIES.get(code, 'Unassigned' if code == 'UN' else code),
        'permanent_department': code == 'CU',
        'search_enabled': code in DEFAULT_DEPARTMENTS,
        'lead_count': 0,
        'customer_count': 0,
        'prospect_count': 0,
        'trade_intake_count': 0,
        'qualified_intake_count': 0,
        'promoted_intake_count': 0,
        'follow_up_due': 0,
        'estimated_pipeline_value': 0.0,
    }


async def snapshot() -> tuple[list[dict], dict[str, list[dict]]]:
    backend = get_backend()
    accounts = await backend.select('customer_accounts', params={'limit': '5000'}) or []
    intakes = await backend.select('customer_trade_intakes', params={'limit': '5000'}) or []
    leads = await backend.select('lead_scout_leads', params={'limit': '5000'}) or []

    by_customer = {row.get('customer_id'): row for row in accounts}
    buckets: dict[str, dict] = {code: department(code) for code in DEFAULT_DEPARTMENTS}
    detail: dict[str, list[dict]] = defaultdict(list)

    for account in accounts:
        code = country_code(account.get('country_code'))
        buckets.setdefault(code, department(code))
        b = buckets[code]
        b['customer_count'] += 1
        if account.get('status') == 'PROSPECT' or account.get('sales_status') in {'NEW','CONTACTED','FOLLOW_UP_DUE','REPLIED','QUALIFIED_LEAD'}:
            b['prospect_count'] += 1
        if account.get('sales_status') == 'FOLLOW_UP_DUE':
            b['follow_up_due'] += 1
        detail[code].append({'kind': 'customer', **account})

    for intake in intakes:
        account = by_customer.get(intake.get('customer_id')) or {}
        code = country_code(account.get('country_code') or intake.get('destination_country'))
        buckets.setdefault(code, department(code))
        b = buckets[code]
        b['trade_intake_count'] += 1
        if intake.get('qualification_status') == 'QUALIFIED':
            b['qualified_intake_count'] += 1
        if intake.get('managed_trade_request_id') or intake.get('status') == 'PROMOTED':
            b['promoted_intake_count'] += 1
        try:
            b['estimated_pipeline_value'] += float(intake.get('target_budget') or 0)
        except (TypeError, ValueError):
            pass
        detail[code].append({'kind': 'intake', **intake})

    for lead in leads:
        code = country_code(lead.get('country'))
        buckets.setdefault(code, department(code))
        b = buckets[code]
        b['lead_count'] += 1
        try:
            b['estimated_pipeline_value'] += float(lead.get('estimated_deal_value') or 0)
        except (TypeError, ValueError):
            pass
        detail[code].append({'kind': 'lead', **lead})

    rows = list(buckets.values())
    rows.sort(key=lambda r: (0 if r['country_code'] == 'CU' else 1, -(r['lead_count'] + r['customer_count'] + r['trade_intake_count']), r['country_name']))
    return rows, detail


@app.get('/country-crm/health')
async def health():
    persistence = persistent_backend_status()
    return {
        'status': 'ok' if persistence['configured'] else 'configuration_required',
        'service': 'country-segmented-crm',
        'segmentation': 'COUNTRY',
        'cuba_department_permanent': True,
        'dynamic_country_departments': True,
        'global_search_departments': DEFAULT_DEPARTMENTS,
        'persistence_provider': persistence['provider'],
    }


@app.get('/country-crm/departments')
async def departments(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows, _ = await snapshot()
    return {
        'status': 'ok',
        'department_count': len(rows),
        'cuba_department': 'CU',
        'departments': rows,
        'totals': {
            'leads': sum(r['lead_count'] for r in rows),
            'customers': sum(r['customer_count'] for r in rows),
            'trade_intakes': sum(r['trade_intake_count'] for r in rows),
            'qualified': sum(r['qualified_intake_count'] for r in rows),
            'promoted': sum(r['promoted_intake_count'] for r in rows),
            'pipeline_value': round(sum(r['estimated_pipeline_value'] for r in rows), 2),
        },
    }


@app.get('/country-crm/departments/{code}')
async def department_detail(code: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    normalized = country_code(code)
    rows, detail = await snapshot()
    summary = next((r for r in rows if r['country_code'] == normalized), department(normalized))
    items = detail.get(normalized, [])
    return {'status': 'ok', 'department': summary, 'items': items, 'item_count': len(items)}
