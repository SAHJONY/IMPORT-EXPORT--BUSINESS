from __future__ import annotations

import os, secrets
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Header, HTTPException
from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY CRM 10X Quality OS', version='1.1.0', docs_url=None, redoc_url=None)


def _now():
    return datetime.now(timezone.utc)


def _as_dt(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace('Z', '+00:00'))
    except Exception:
        return None


def _truthy(v):
    if isinstance(v, bool):
        return v
    return str(v or '').strip().lower() in {'1','true','yes','verified','approved','complete','completed','ready','active'}


def _text(*vals):
    return ' '.join(str(v or '').strip() for v in vals if str(v or '').strip()).strip()


def _company(r):
    return r.get('legal_name') or r.get('trade_name') or r.get('buyer_company') or r.get('company_name') or r.get('business_name') or 'Unknown'


def _is_cuba(r):
    c = str(r.get('country_code') or r.get('buyer_country') or r.get('country') or '').upper().strip()
    return c in {'CU','CUB','CUBA'} or str(r.get('country') or '').strip().casefold() == 'cuba'


def _is_mipyme(r):
    if not _is_cuba(r):
        return False
    t = _text(r.get('actor_type'), r.get('business_type'), r.get('source_platform'), r.get('source_name')).upper()
    return any(x in t for x in ('MIPYME','PRIVATE','PRIVADA','REGISTRO MERCANTIL','MINJUS'))


def _has_contact(r):
    return bool(_text(r.get('email'), r.get('public_email'), r.get('phone'), r.get('public_phone'), r.get('buyer_contact')))


def _has_activity(r):
    return bool(_text(r.get('primary_activity'), r.get('activity'), r.get('product_category'), r.get('business_type')))


def _has_location(r):
    return bool(_text(r.get('province'), r.get('municipality'), r.get('destination'), r.get('country'), r.get('country_code')))


def _has_evidence(r):
    return bool(_text(r.get('source_url'), r.get('source_provenance'), r.get('external_reference'), r.get('registry_reference'), r.get('evidence_summary')))


def _verified(r):
    vals = _text(r.get('verification_status'), r.get('kyb_status'), r.get('registry_status')).upper()
    return any(x in vals for x in ('KYB_VERIFIED','VERIFIED_ACTIVE','VERIFIED MERCHANT','APPROVED'))


def _research_verified(r):
    vals = _text(r.get('verification_status'), r.get('registry_status')).upper()
    return _verified(r) or 'RESEARCH_VERIFIED' in vals or 'REGISTERED' in vals


def _has_need(r):
    return bool(_text(r.get('product_need'), r.get('buyer_requirement'), r.get('requested_product'), r.get('rfq_product')))


def _has_quantity(r):
    for k in ('quantity','requested_quantity','volume','annual_quantity','monthly_quantity'):
        v = r.get(k)
        if v not in (None,'',0,'0'):
            return True
    return False


def _has_supplier_match(r):
    return bool(_text(r.get('supplier_id'), r.get('supplier_company'), r.get('best_supplier'), r.get('supplier_match_id')))


def _has_economics(r):
    return any(r.get(k) not in (None,'',0,'0') for k in ('target_budget','target_price','supplier_reference_cost','expected_profit','estimated_gross_profit','sahjony_fee','commission_amount'))


def _has_next_action(r):
    return bool(_text(r.get('next_action'), r.get('next_best_action'), r.get('next_follow_up_at')))


def _fresh(r, days=30):
    d = _as_dt(r.get('updated_at') or r.get('verification_date') or r.get('created_at'))
    if not d:
        return False
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d >= _now() - timedelta(days=days)


def assess_record(r):
    checks = {
        'identity': _company(r) != 'Unknown',
        'contactability': _has_contact(r),
        'activity_segmented': _has_activity(r),
        'location': _has_location(r),
        'source_evidence': _has_evidence(r),
        'registry_or_research_verified': _research_verified(r),
        'kyb_verified': _verified(r),
        'current_need': _has_need(r),
        'quantity_or_volume': _has_quantity(r),
        'supplier_match': _has_supplier_match(r),
        'commercial_economics': _has_economics(r),
        'next_action': _has_next_action(r),
        'fresh_30d': _fresh(r, 30),
    }
    weights = {
        'identity': 5, 'contactability': 8, 'activity_segmented': 7, 'location': 5,
        'source_evidence': 8, 'registry_or_research_verified': 7, 'kyb_verified': 15,
        'current_need': 12, 'quantity_or_volume': 7, 'supplier_match': 10,
        'commercial_economics': 8, 'next_action': 5, 'fresh_30d': 3,
    }
    score = sum(weights[k] for k,v in checks.items() if v)
    missing = [k for k,v in checks.items() if not v]
    if not checks['contactability']:
        next_action = 'Enrich a legitimate public business contact; continue research autonomously through approved public-source fallbacks.'
    elif not checks['kyb_verified']:
        next_action = 'Obtain/validate KYB and authorized representative evidence before commercial promotion.'
    elif not checks['current_need']:
        next_action = 'Discover a current product/service need and capture it as evidence-backed demand.'
    elif not checks['quantity_or_volume']:
        next_action = 'Confirm quantity, specification, destination and timing.'
    elif not checks['supplier_match']:
        next_action = 'Match at least 3 qualified suppliers and request comparable current terms.'
    elif not checks['commercial_economics']:
        next_action = 'Model landed economics and protect SAHJONY fee/margin before introduction.'
    else:
        next_action = 'Advance through governed Deal Room; preserve evidence and non-binding controls.'
    tier = 'TRANSACTION_READY' if score >= 90 else 'COMMERCIAL_READY' if score >= 75 else 'ACTIVATION_READY' if score >= 55 else 'ENRICHMENT' if score >= 30 else 'RESEARCH'
    return {'score':score,'tier':tier,'checks':checks,'missing':missing,'next_best_action':next_action}


def _auth(role, authorization, employee_id):
    if role not in {'owner','employee'}:
        raise HTTPException(400,'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401,'Missing Authorization')
    token = authorization.removeprefix('Bearer ').strip()
    if role == 'owner':
        if not verify_owner_token(token):
            raise HTTPException(403,'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    configured = os.getenv('EMPLOYEE_TOKEN','').strip()
    if not configured or not secrets.compare_digest(token, configured):
        raise HTTPException(403,'Invalid employee credential')
    return {'role':'employee','id':(employee_id or 'staff')[:160]}


async def _load():
    b = get_backend()
    accounts = await b.select('customer_accounts', params={'limit':'5000'}) or []
    intakes = await b.select('customer_trade_intakes', params={'limit':'5000'}) or []
    try:
        external = await b.select('external_trade_prospects', params={'organization_id':'eq.org_sahjony_global_trade','limit':'5000'}) or []
    except Exception:
        external = []
    try:
        matches = await b.select('deal_supplier_matches', params={'limit':'5000'}) or []
    except Exception:
        matches = []
    return accounts, intakes, external, matches


@app.get('/crm/quality-10x/health')
async def health():
    return {
        'status':'ok','service':'crm-quality-10x','version':'1.1.0',
        'principle':'verification + actionable demand + supplier fit + protected economics > raw record count',
        'fail_closed_promotion':True,'cold_bulk_outreach':False,'revenue_inference':False,
        'sofia_super_proactive_sales_os':True,'owner_dependency_for_research':False,
        'target_standard':'10/10 when verified, current, actionable and transaction-linked data thresholds are met',
    }


@app.get('/crm/quality-10x/scorecard')
async def scorecard():
    accounts, intakes, external, matches = await _load()
    universe = accounts + external
    cuba = [r for r in universe if _is_cuba(r)]
    mipymes = [r for r in universe if _is_mipyme(r)]
    assessed = [assess_record(r) for r in mipymes]
    count = len(assessed)
    def pct(n, d): return round((100*n/d),1) if d else 0.0
    avg = round(sum(x['score'] for x in assessed)/count,1) if count else 0.0
    commercial = sum(1 for x in assessed if x['score'] >= 75)
    transaction = sum(1 for x in assessed if x['score'] >= 90)
    with_contact = sum(1 for r in mipymes if _has_contact(r))
    kyb = sum(1 for r in mipymes if _verified(r))
    current_need_records = sum(1 for r in mipymes if _has_need(r))
    real_intakes = len(intakes)
    qualified_intakes = sum(1 for r in intakes if str(r.get('qualification_status') or '').upper() == 'QUALIFIED')
    matched = len(matches)
    dimensions = {
        'data_foundation': min(100.0, round(pct(sum(1 for r in mipymes if _has_evidence(r)), count),1)),
        'contactability': pct(with_contact,count),
        'kyb_verification': pct(kyb,count),
        'demand_capture': min(100.0, round((qualified_intakes/max(1, min(count,500))) * 100,1)),
        'supplier_matching': min(100.0, round((matched/max(1, qualified_intakes)) * 100,1)) if qualified_intakes else 0.0,
        'record_maturity_average': avg,
    }
    overall = round(sum(dimensions.values())/len(dimensions),1)
    gaps=[]
    if dimensions['contactability'] < 70: gaps.append('Increase legitimate public contact coverage.')
    if dimensions['kyb_verification'] < 50: gaps.append('Build a real KYB-verified merchant/business layer.')
    if qualified_intakes < 10: gaps.append('Convert research records into evidence-backed buyer requirements/RFQs.')
    if matched < max(1, qualified_intakes): gaps.append('Create multiple supplier matches for each qualified requirement.')
    return {
        'status':'ok','score_10':round(overall/10,1),'score_100':overall,
        'assessment':'10/10 is an earned operational state, not a cosmetic label.',
        'coverage':{'loaded_business_records':len(universe),'cuba_records':len(cuba),'cuba_mipyme_records':count,'customer_trade_intakes':real_intakes,'qualified_intakes':qualified_intakes,'deal_supplier_matches':matched},
        'maturity':{'commercial_ready':commercial,'transaction_ready':transaction,'public_contact_coverage_pct':pct(with_contact,count),'kyb_verified_pct':pct(kyb,count),'records_with_current_need':current_need_records},
        'dimensions':dimensions,'gaps':gaps,
        'north_star':'verified opportunities reaching collected revenue with minimal SAHJONY capital exposure',
    }


@app.get('/crm/quality-10x/activation-queue')
async def activation_queue(limit:int=100, x_role:str|None=Header(None,alias='X-Role'), authorization:str|None=Header(None,alias='Authorization'), x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    _auth(x_role,authorization,x_employee_id)
    accounts, intakes, external, matches = await _load()
    intake_by_customer = {}
    for i in intakes:
        intake_by_customer.setdefault(i.get('customer_id'),[]).append(i)
    candidates=[]
    for r in accounts + external:
        if not _is_mipyme(r):
            continue
        a=assess_record(r)
        ref=r.get('customer_id') or r.get('prospect_id') or r.get('external_reference') or r.get('_record_key')
        candidates.append({
            'record_ref':ref,'company':_company(r),'province':r.get('province'),'municipality':r.get('municipality'),
            'activity':r.get('primary_activity') or r.get('activity') or r.get('product_category'),
            'score':a['score'],'tier':a['tier'],'missing':a['missing'],'next_best_action':a['next_best_action'],
            'has_contact':_has_contact(r),'kyb_verified':_verified(r),'current_need':_has_need(r),
            'linked_intakes':len(intake_by_customer.get(r.get('customer_id'),[])),
            'outreach_policy':'CONSENT_OR_PRIOR_BUSINESS_RELATIONSHIP_REQUIRED_FOR_AUTONOMOUS_PROMOTIONAL_SEND',
        })
    candidates.sort(key=lambda x:(x['score'], x['has_contact'], x['current_need']), reverse=True)
    return {'status':'ok','count':min(len(candidates),max(1,min(limit,500))),'queue':candidates[:max(1,min(limit,500))],'pii_exposed':False}


@app.get('/crm/quality-10x/standards')
async def standards():
    return {
        'status':'ok','standard':'SAHJONY VERIFIED TRADE NETWORK 10/10',
        'required_for_verified_business':['identity evidence','business/registry evidence','authorized representative where commercially active','sanctions/restricted-party screening when applicable','current verification timestamp'],
        'required_for_qualified_demand':['current product/service need','quantity/volume','specification','destination','timing','buyer authority evidence'],
        'required_for_supplier_match':['supplier identity/KYB','current comparable quote or commercial indication labeled correctly','MOQ/capacity','Incoterm/origin','lead time','payment terms','quality/specification fit'],
        'required_for_transaction_ready':['buyer verified','supplier verified','written demand','commercial terms','compliance path','payment path','logistics path','SAHJONY fee protection','no unsupported binding commitment'],
        'revenue_rule':'Revenue/commission is never marked earned or collected without evidence of an actual transaction and receipt.',
    }


# Keep SOFIA inside the existing CRM serverless surface so this upgrade does not consume another Vercel function.
from sofia_proactive_sales_os import app as sofia_proactive_sales_app
from sofia_fortune500_hardening_api import app as sofia_hardening_app
app.include_router(sofia_proactive_sales_app.router)
app.include_router(sofia_hardening_app.router)
