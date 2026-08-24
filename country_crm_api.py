from __future__ import annotations

from collections import Counter, defaultdict
from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Worldwide CRM', version='1.3.0', docs_url=None, redoc_url=None)

COUNTRIES = {
    'CU':'Cuba','US':'United States','MX':'Mexico','DO':'Dominican Republic','PA':'Panama','CO':'Colombia','BR':'Brazil','CL':'Chile','PE':'Peru','CR':'Costa Rica','GT':'Guatemala','CA':'Canada',
    'ES':'Spain','GB':'United Kingdom','DE':'Germany','NL':'Netherlands','TR':'Türkiye','AE':'United Arab Emirates','IN':'India','VN':'Vietnam','CN':'China','JP':'Japan','KR':'South Korea','TW':'Taiwan',
    'SA':'Saudi Arabia','LY':'Libya','IQ':'Iraq','PK':'Pakistan','AU':'Australia','NZ':'New Zealand','NA':'Namibia','ZA':'South Africa','EG':'Egypt','DZ':'Algeria','MA':'Morocco','TN':'Tunisia','JO':'Jordan',
    'IT':'Italy','FR':'France','CH':'Switzerland','AT':'Austria','TH':'Thailand','MY':'Malaysia','ID':'Indonesia','BD':'Bangladesh','PH':'Philippines','SG':'Singapore','QA':'Qatar','KW':'Kuwait','BH':'Bahrain','OM':'Oman',
    'AR':'Argentina','UY':'Uruguay','PY':'Paraguay','BO':'Bolivia','EC':'Ecuador','VE':'Venezuela','GY':'Guyana','SR':'Suriname','NO':'Norway','SE':'Sweden','FI':'Finland','DK':'Denmark','BE':'Belgium','PL':'Poland',
    'RO':'Romania','BG':'Bulgaria','GR':'Greece','PT':'Portugal','IE':'Ireland','CZ':'Czech Republic','HU':'Hungary','SK':'Slovakia','UA':'Ukraine','KZ':'Kazakhstan','UZ':'Uzbekistan','NG':'Nigeria','AO':'Angola',
    'GH':'Ghana','CI':'Côte d’Ivoire','KE':'Kenya','TZ':'Tanzania','ET':'Ethiopia','UG':'Uganda','ZM':'Zambia','ZW':'Zimbabwe','MZ':'Mozambique','BW':'Botswana','CD':'DR Congo','CG':'Republic of the Congo','GN':'Guinea'
}

ALIASES = {name.lower(): code for code, name in COUNTRIES.items()}
ALIASES.update({'usa':'US','u.s.':'US','us':'US','uk':'GB','great britain':'GB','uae':'AE','korea':'KR','south korea':'KR','taiwán':'TW','méxico':'MX','japón':'JP','españa':'ES','brasil':'BR'})

DEFAULT_DEPARTMENTS = list(COUNTRIES.keys())


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

    if any(x in text for x in ('crude oil','crude buyer','refinery crude','murban','upper zakum','mars crude','wti crude','merey')):
        sector, product_family = 'GLOBAL_CRUDE', 'CRUDE_OIL'
    elif any(x in text for x in ('lng','liquefied natural gas')):
        sector, product_family = 'NATURAL_GAS', 'LNG'
    elif any(x in text for x in ('lpg','propane','butane')):
        sector, product_family = 'NATURAL_GAS', 'LPG'
    elif any(x in text for x in ('jet fuel','a1 jet','jet a-1')):
        sector, product_family = 'REFINED_PRODUCTS', 'JET_A1'
    elif any(x in text for x in ('gasoline','diesel','ulsd','fuel distributor','fuel supply','combustible','en590','d6')):
        sector = 'CUBA_FUELS' if country in {'CU','US','CN'} and 'cuba' in text else 'REFINED_PRODUCTS'
        product_family = 'GASOLINE_DIESEL' if 'gasoline' in text and 'diesel' in text else ('GASOLINE' if 'gasoline' in text else 'DIESEL_ULSD')
    elif any(x in text for x in ('wheat','soybean','soybeans','corn','maize','barley','grain','rice','sugar')):
        sector, product_family = 'AGRICULTURE_FOOD', 'GRAINS_OILSEEDS'
    elif any(x in text for x in ('iron ore','copper','aluminum','aluminium','nickel','lithium','cobalt','steel','metal')):
        sector, product_family = 'METALS_MINING', 'METALS_MINERALS'
    elif any(x in text for x in ('fertilizer','urea','ammonia','phosphate','potash','chemical')):
        sector, product_family = 'CHEMICALS_FERTILIZER', 'FERTILIZER_CHEMICALS'
    elif any(x in text for x in ('solar','photovoltaic','inverter','battery','batteries','ecoflow','charging','electrolinera')):
        sector = 'CUBA_RENEWABLES' if country == 'CU' else 'RENEWABLE_ENERGY'; product_family = 'SOLAR_STORAGE_EV'
    elif any(x in text for x in ('agro','agriculture','irrigation','riego')):
        sector = 'CUBA_AGRO_ENERGY' if country == 'CU' else 'AGRICULTURE_FOOD'; product_family = 'AGRO_IRRIGATION_POWER'
    elif any(x in text for x in ('machinery','industrial equipment','equipment','manufacturing','factory')):
        sector, product_family = 'INDUSTRIALS', 'MACHINERY_EQUIPMENT'
    elif any(x in text for x in ('cement','construction material','rebar','building material')):
        sector, product_family = 'CONSTRUCTION_MATERIALS', 'BUILDING_MATERIALS'
    elif any(x in text for x in ('electronics','semiconductor','component','telecom')):
        sector, product_family = 'ELECTRONICS_COMPONENTS', 'ELECTRONICS_TELECOM'
    elif any(x in text for x in ('backup power','generator','electrical services','refrigeration')):
        sector = 'CUBA_ENERGY_INFRASTRUCTURE' if country == 'CU' else 'ENERGY_INFRASTRUCTURE'; product_family = 'BACKUP_POWER_INFRASTRUCTURE'
    elif any(x in text for x in ('investment partner','investor','investment opportunity')):
        sector, product_family = 'INVESTMENT_STRATEGIC', 'STRATEGIC_CAPITAL'
    else:
        sector, product_family = 'GENERAL_TRADE', 'OTHER'

    if role_raw in {'BUYER','IMPORT_NEED'}: commercial_role = 'BUYER'
    elif role_raw in {'SELLER','SUPPLIER','EXPORT_OFFER'}: commercial_role = 'SELLER_SUPPLIER'
    elif role_raw in {'BOTH','DISTRIBUTOR'}: commercial_role = 'DISTRIBUTOR_CHANNEL'
    elif role_raw in {'PARTNER','REFERRAL'}: commercial_role = 'STRATEGIC_PARTNER'
    else: commercial_role = role_raw or 'OTHER'

    return {'sector':sector,'product_family':product_family,'commercial_role':commercial_role,'country_department':country}


def department(code: str) -> dict:
    return {
        'country_code':code,
        'country_name':COUNTRIES.get(code,'Unassigned' if code=='UN' else code),
        'permanent_department':code=='CU',
        'search_enabled':code in DEFAULT_DEPARTMENTS,
        'lead_count':0,
        'customer_count':0,
        'prospect_count':0,
        'trade_intake_count':0,
        'qualified_intake_count':0,
        'promoted_intake_count':0,
        'follow_up_due':0,
        'gross_pipeline_value':0.0,
        'qualified_pipeline_value':0.0,
        'active_managed_trade_value':0.0,
        'research_opportunity_value':0.0,
        'non_usd_budget_count':0,
        'sector_counts':{},
        'product_family_counts':{},
        'commercial_role_counts':{}
    }


def usd_budget(intake: dict) -> float:
    if str(intake.get('currency') or 'USD').upper() != 'USD':
        return 0.0
    try:
        value = float(intake.get('target_budget') or 0)
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0 else 0.0


async def snapshot() -> tuple[list[dict], dict[str, list[dict]]]:
    backend = get_backend(); accounts = await backend.select('customer_accounts', params={'limit':'5000'}) or []; intakes = await backend.select('customer_trade_intakes', params={'limit':'5000'}) or []; leads = await backend.select('lead_scout_leads', params={'limit':'5000'}) or []
    by_customer = {row.get('customer_id'):row for row in accounts}; buckets={code:department(code) for code in DEFAULT_DEPARTMENTS}; detail=defaultdict(list); sector_counters=defaultdict(Counter); product_counters=defaultdict(Counter); role_counters=defaultdict(Counter)
    for account in accounts:
        code=country_code(account.get('country_code')); buckets.setdefault(code,department(code)); b=buckets[code]; b['customer_count']+=1
        if account.get('status')=='PROSPECT' or account.get('sales_status') in {'NEW','CONTACTED','FOLLOW_UP_DUE','REPLIED','QUALIFIED_LEAD'}: b['prospect_count']+=1
        if account.get('sales_status')=='FOLLOW_UP_DUE': b['follow_up_due']+=1
        detail[code].append({'kind':'customer',**account})
    for intake in intakes:
        account=by_customer.get(intake.get('customer_id')) or {}; code=country_code(account.get('country_code') or intake.get('destination_country')); buckets.setdefault(code,department(code)); b=buckets[code]; b['trade_intake_count']+=1
        value=usd_budget(intake)
        if str(intake.get('currency') or 'USD').upper()!='USD' and intake.get('target_budget'): b['non_usd_budget_count']+=1
        if value: b['gross_pipeline_value']+=value
        if intake.get('qualification_status')=='QUALIFIED':
            b['qualified_intake_count']+=1
            if value: b['qualified_pipeline_value']+=value
        if intake.get('managed_trade_request_id') or intake.get('status')=='PROMOTED':
            b['promoted_intake_count']+=1
            if value: b['active_managed_trade_value']+=value
        detail[code].append({'kind':'intake',**intake})
    for lead in leads:
        code=country_code(lead.get('country')); buckets.setdefault(code,department(code)); b=buckets[code]; b['lead_count']+=1; classification=classify_lead(lead); sector_counters[code][classification['sector']]+=1; product_counters[code][classification['product_family']]+=1; role_counters[code][classification['commercial_role']]+=1
        try: b['research_opportunity_value']+=max(0.0,float(lead.get('estimated_deal_value') or 0))
        except (TypeError,ValueError): pass
        detail[code].append({'kind':'lead',**classification,**lead})
    for code,bucket in buckets.items(): bucket['sector_counts']=dict(sector_counters[code].most_common()); bucket['product_family_counts']=dict(product_counters[code].most_common()); bucket['commercial_role_counts']=dict(role_counters[code].most_common())
    rows=list(buckets.values()); rows.sort(key=lambda r:(0 if r['country_code']=='CU' else 1,-(r['lead_count']+r['customer_count']+r['trade_intake_count']),r['country_name'])); return rows,detail


@app.get('/country-crm/health')
async def health():
    persistence=persistent_backend_status(); return {'status':'ok' if persistence['configured'] else 'configuration_required','service':'worldwide-segmented-crm','segmentation':['COUNTRY','SECTOR','PRODUCT_FAMILY','COMMERCIAL_ROLE'],'cuba_department_permanent':True,'dynamic_country_departments':True,'global_search_departments':DEFAULT_DEPARTMENTS,'persistence_provider':persistence['provider'],'valuation_policy':'Research lead estimates are excluded from commercial pipeline. USD pipeline is sourced only from explicit target budgets on real trade intakes.'}


@app.get('/country-crm/departments')
async def departments(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization); rows,detail=await snapshot(); all_items=[item for items in detail.values() for item in items if item.get('kind')=='lead']; sector_totals=Counter(item.get('sector','GENERAL_TRADE') for item in all_items); product_totals=Counter(item.get('product_family','OTHER') for item in all_items); role_totals=Counter(item.get('commercial_role','OTHER') for item in all_items)
    gross=round(sum(r['gross_pipeline_value'] for r in rows),2); qualified=round(sum(r['qualified_pipeline_value'] for r in rows),2); active=round(sum(r['active_managed_trade_value'] for r in rows),2); research=round(sum(r['research_opportunity_value'] for r in rows),2)
    return {
        'status':'ok',
        'department_count':len(rows),
        'cuba_department':'CU',
        'departments':rows,
        'portfolio_segmentation':{'sectors':dict(sector_totals.most_common()),'product_families':dict(product_totals.most_common()),'commercial_roles':dict(role_totals.most_common())},
        'totals':{
            'leads':sum(r['lead_count'] for r in rows),
            'customers':sum(r['customer_count'] for r in rows),
            'trade_intakes':sum(r['trade_intake_count'] for r in rows),
            'qualified':sum(r['qualified_intake_count'] for r in rows),
            'promoted':sum(r['promoted_intake_count'] for r in rows),
            'pipeline_value':gross,
            'gross_pipeline_value':gross,
            'qualified_pipeline_value':qualified,
            'active_managed_trade_value':active,
            'research_opportunity_value':research,
            'contracted_value':None,
            'recognized_revenue':None,
            'non_usd_budget_count':sum(r['non_usd_budget_count'] for r in rows)
        },
        'valuation_policy':{
            'pipeline_value_definition':'Sum of explicit positive USD target_budget values on real customer_trade_intakes only.',
            'qualified_pipeline_definition':'Gross pipeline restricted to qualification_status=QUALIFIED.',
            'active_managed_trade_definition':'Gross pipeline restricted to PROMOTED intakes or intakes linked to managed trade.',
            'research_opportunity_definition':'Estimated values on research leads; tracked separately and never presented as pipeline, revenue or contracted value.',
            'contracted_value_definition':'Not calculated until executed-contract evidence is stored.',
            'recognized_revenue_definition':'Not calculated here; revenue must come from the accounting ledger.',
            'non_usd_policy':'Non-USD target budgets are excluded from USD totals until a governed FX conversion exists.'
        }
    }


@app.get('/country-crm/departments/{code}')
async def department_detail(code: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization); normalized=country_code(code); rows,detail=await snapshot(); summary=next((r for r in rows if r['country_code']==normalized),department(normalized)); items=detail.get(normalized,[]); return {'status':'ok','department':summary,'items':items,'item_count':len(items),'valuation_policy':'Research lead estimates are separate from commercial pipeline.'}
