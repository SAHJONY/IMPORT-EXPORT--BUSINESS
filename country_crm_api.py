from __future__ import annotations

from collections import Counter, defaultdict
from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Country CRM', version='1.1.0', docs_url=None, redoc_url=None)

COUNTRIES = {
    'CU': 'Cuba', 'US': 'United States', 'MX': 'Mexico', 'DO': 'Dominican Republic',
    'PA': 'Panama', 'CO': 'Colombia', 'BR': 'Brazil', 'CL': 'Chile', 'PE': 'Peru',
    'CR': 'Costa Rica', 'GT': 'Guatemala', 'CA': 'Canada', 'ES': 'Spain',
    'GB': 'United Kingdom', 'DE': 'Germany', 'NL': 'Netherlands', 'TR': 'Türkiye',
    'AE': 'United Arab Emirates', 'IN': 'India', 'VN': 'Vietnam', 'CN': 'China',
    'JP': 'Japan', 'KR': 'South Korea', 'TW': 'Taiwan',
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
    'japan': 'JP', 'japón': 'JP', 'south korea': 'KR', 'korea': 'KR', 'corea del sur': 'KR',
    'taiwan': 'TW', 'taiwán': 'TW',
}

DEFAULT_DEPARTMENTS = ['CU','US','MX','DO','PA','CO','BR','CL','PE','CR','GT','CA','ES','GB','DE','NL','TR','AE','IN','VN','CN','JP','KR','TW']


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


def classify_lead(lead: dict) -> dict:
    text = ' '.join(str(lead.get(k) or '') for k in ('business_name','product_need_or_offer','notes','source_description')).lower()
    country = country_code(lead.get('country'))
    role_raw = str(lead.get('deal_side') or lead.get('lead_type') or 'OTHER').upper()

    if any(x in text for x in ('crude oil','crude buyer','refinery crude','murban','upper zakum','mars crude','wti crude')):
        sector = 'GLOBAL_CRUDE'
        product_family = 'CRUDE_OIL'
    elif any(x in text for x in ('gasoline','diesel','ulsd','fuel distributor','fuel supply','combustible')):
        sector = 'CUBA_FUELS' if country in {'CU','US','CN'} and 'cuba' in text else 'REFINED_PRODUCTS'
        if 'gasoline' in text and 'diesel' in text:
            product_family = 'GASOLINE_DIESEL'
        elif 'gasoline' in text:
            product_family = 'GASOLINE'
        elif 'diesel' in text or 'ulsd' in text:
            product_family = 'DIESEL_ULSD'
        else:
            product_family = 'REFINED_FUELS'
    elif any(x in text for x in ('jet fuel','a1 jet','jet a-1')):
        sector = 'REFINED_PRODUCTS'
        product_family = 'JET_A1'
    elif any(x in text for x in ('solar','photovoltaic','inverter','battery','batteries','ecoflow','charging','electrolinera')):
        sector = 'CUBA_RENEWABLES' if country == 'CU' else 'RENEWABLE_ENERGY'
        product_family = 'SOLAR_STORAGE_EV'
    elif any(x in text for x in ('agro','agriculture','irrigation','riego')):
        sector = 'CUBA_AGRO_ENERGY' if country == 'CU' else 'AGRO_ENERGY'
        product_family = 'AGRO_IRRIGATION_POWER'
    elif any(x in text for x in ('backup power','generator','electrical services','refrigeration','telecom')):
        sector = 'CUBA_ENERGY_INFRASTRUCTURE' if country == 'CU' else 'ENERGY_INFRASTRUCTURE'
        product_family = 'BACKUP_POWER_INFRASTRUCTURE'
    elif any(x in text for x in ('investment partner','investor','investment opportunity')):
        sector = 'ENERGY_INVESTMENT'
        product_family = 'STRATEGIC_CAPITAL'
    else:
        sector = 'GENERAL_TRADE'
        product_family = 'OTHER'

    if role_raw in {'BUYER','IMPORT_NEED'}:
        commercial_role = 'BUYER'
    elif role_raw in {'SELLER','SUPPLIER','EXPORT_OFFER'}:
        commercial_role = 'SELLER_SUPPLIER'
    elif role_raw in {'BOTH','DISTRIBUTOR'}:
        commercial_role = 'DISTRIBUTOR_CHANNEL'
    elif role_raw in {'PARTNER','REFERRAL'}:
        commercial_role = 'STRATEGIC_PARTNER'
    else:
        commercial_role = role_raw or 'OTHER'

    return {
        'sector': sector,
        'product_family': product_family,
        'commercial_role': commercial_role,
        'country_department': country,
    }


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
        'sector_counts': {},
        'product_family_counts': {},
        'commercial_role_counts': {},
    }


async def snapshot() -> tuple[list[dict], dict[str, list[dict]]]:
    backend = get_backend()
    accounts = await backend.select('customer_accounts', params={'limit': '5000'}) or []
    intakes = await backend.select('customer_trade_intakes', params={'limit': '5000'}) or []
    leads = await backend.select('lead_scout_leads', params={'limit': '5000'}) or []

    by_customer = {row.get('customer_id'): row for row in accounts}
    buckets: dict[str, dict] = {code: department(code) for code in DEFAULT_DEPARTMENTS}
    detail: dict[str, list[dict]] = defaultdict(list)
    sector_counters: dict[str, Counter] = defaultdict(Counter)
    product_counters: dict[str, Counter] = defaultdict(Counter)
    role_counters: dict[str, Counter] = defaultdict(Counter)

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
        classification = classify_lead(lead)
        sector_counters[code][classification['sector']] += 1
        product_counters[code][classification['product_family']] += 1
        role_counters[code][classification['commercial_role']] += 1
        try:
            b['estimated_pipeline_value'] += float(lead.get('estimated_deal_value') or 0)
        except (TypeError, ValueError):
            pass
        detail[code].append({'kind': 'lead', **classification, **lead})

    for code, bucket in buckets.items():
        bucket['sector_counts'] = dict(sector_counters[code].most_common())
        bucket['product_family_counts'] = dict(product_counters[code].most_common())
        bucket['commercial_role_counts'] = dict(role_counters[code].most_common())

    rows = list(buckets.values())
    rows.sort(key=lambda r: (0 if r['country_code'] == 'CU' else 1, -(r['lead_count'] + r['customer_count'] + r['trade_intake_count']), r['country_name']))
    return rows, detail


@app.get('/country-crm/health')
async def health():
    persistence = persistent_backend_status()
    return {
        'status': 'ok' if persistence['configured'] else 'configuration_required',
        'service': 'country-segmented-crm',
        'segmentation': ['COUNTRY','SECTOR','PRODUCT_FAMILY','COMMERCIAL_ROLE'],
        'cuba_department_permanent': True,
        'dynamic_country_departments': True,
        'global_search_departments': DEFAULT_DEPARTMENTS,
        'persistence_provider': persistence['provider'],
    }


@app.get('/country-crm/departments')
async def departments(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows, detail = await snapshot()
    all_items = [item for items in detail.values() for item in items if item.get('kind') == 'lead']
    sector_totals = Counter(item.get('sector','GENERAL_TRADE') for item in all_items)
    product_totals = Counter(item.get('product_family','OTHER') for item in all_items)
    role_totals = Counter(item.get('commercial_role','OTHER') for item in all_items)
    return {
        'status': 'ok',
        'department_count': len(rows),
        'cuba_department': 'CU',
        'departments': rows,
        'portfolio_segmentation': {
            'sectors': dict(sector_totals.most_common()),
            'product_families': dict(product_totals.most_common()),
            'commercial_roles': dict(role_totals.most_common()),
        },
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
