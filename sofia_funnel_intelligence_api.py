from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY SOFIA Funnel Intelligence', version='1.0.0', docs_url=None, redoc_url=None)

CATALOG_PATH = Path(__file__).resolve().parent / 'public' / 'cuba-catalog.json'
ORG = 'org_sahjony_global_trade'


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _authorized(authorization: str | None) -> None:
    token = (authorization or '').removeprefix('Bearer ').strip()
    if token and verify_owner_token(token):
        return
    cron = os.getenv('CRON_SECRET', '').strip()
    if cron and token == cron:
        return
    raise HTTPException(403, 'Owner or trusted cron authorization required')


def _catalog() -> list[dict[str, Any]]:
    try:
        return list((json.loads(CATALOG_PATH.read_text(encoding='utf-8')) or {}).get('products') or [])
    except Exception:
        return []


def _blob(row: dict[str, Any]) -> str:
    keys = ('legal_name','trade_name','buyer_company','business_name','company_name','product_need','product_description','product_category','primary_activity','activity','notes','source')
    return ' '.join(str(row.get(k) or '') for k in keys).lower()


def _segment(row: dict[str, Any]) -> list[str]:
    t = _blob(row)
    rules = {
        'food_hospitality':['food','alimento','restaurante','cafeter','panader','hotel','hostal','bebida'],
        'technology':['telefono','smartphone','computer','computadora','laptop','tablet','informatica','software','electronica'],
        'beauty_personal_care':['belleza','cosmet','perfume','salon','barber','peluquer','higiene'],
        'home_family':['hogar','familia','bebe','niño','limpieza','papel','textil','mueble'],
        'construction_industrial':['constru','ferreter','industrial','manufactur','maquinaria','taller','electric','plomer'],
        'energy':['energia','solar','generator','generador','combustible','diesel','fuel'],
        'automotive':['auto','vehiculo','neumatic','mecanica','transporte','repuesto'],
        'agriculture':['agric','fertiliz','granja','cultivo','riego','agro'],
        'health':['salud','farmac','medic','clinica','primeros auxilios'],
    }
    scored=[]
    for seg, needles in rules.items():
        score=sum(1 for n in needles if n in t)
        if score: scored.append((score,seg))
    scored.sort(reverse=True)
    return [s for _,s in scored[:4]] or ['general_trade']


def _product_score(p: dict[str, Any], segments: list[str], row: dict[str, Any]) -> int:
    t = (str(p.get('category') or '')+' '+str(p.get('product') or '')).lower()
    score=0
    maps={
        'food_hospitality':['alimento','cocina','limpieza','papel','refriger','hotel'],
        'technology':['teléfono','smartphone','computadora','laptop','tablet','electr','router','impresora','ssd'],
        'beauty_personal_care':['perfume','belleza','cosm','cuidado personal','higiene'],
        'home_family':['hogar','bebé','familia','papel','limpieza','cocina','dormitorio'],
        'construction_industrial':['constru','industrial','herramient','eléctr','maquinaria'],
        'energy':['solar','energía','generador','batería'],
        'automotive':['auto','vehículo','batería','neumático','repuesto'],
        'agriculture':['agric','fertiliz','solar','riego'],
        'health':['salud','primeros auxilios','medicamentos'],
        'general_trade':['alimentos','hogar','limpieza','teléfonos'],
    }
    for s in segments:
        score += 3*sum(1 for n in maps.get(s,[]) if n in t)
    need=_blob(row)
    for token in [x for x in need.replace('/',' ').replace(',',' ').split() if len(x)>4][:30]:
        if token in t: score += 2
    if str(p.get('priority') or '').upper()=='A': score += 1
    if str(p.get('status') or '').upper()=='COMPLIANCE_REVIEW': score -= 2
    return score


def _recommend(row: dict[str, Any], limit: int=8) -> list[dict[str, Any]]:
    segs=_segment(row)
    ranked=[]
    for p in _catalog():
        s=_product_score(p,segs,row)
        if s>0: ranked.append((s,p))
    ranked.sort(key=lambda x:(-x[0],str(x[1].get('product') or '')))
    return [{'sku':p.get('sku'),'product':p.get('product'),'category':p.get('category'),'status':p.get('status'),'score':s} for s,p in ranked[:limit]]


def _commercial_score(row: dict[str, Any]) -> tuple[int,list[str]]:
    score=15; reasons=[]
    t=_blob(row)
    if row.get('product_need') or row.get('product_description'): score+=20; reasons.append('product_need_present')
    if row.get('quantity'): score+=15; reasons.append('quantity_present')
    if row.get('destination_country') or row.get('destination'): score+=10; reasons.append('destination_present')
    if row.get('target_budget'): score+=10; reasons.append('budget_present')
    if row.get('email') or row.get('public_email') or row.get('phone') or row.get('public_phone'): score+=10; reasons.append('contact_route_present')
    if any(x in str(row.get('sales_status') or '').upper() for x in ('REPLIED','QUALIFIED')): score+=15; reasons.append('engaged')
    if any(x in t for x in ('rfq','quote','quotation','cotizacion','cotización','buy','comprar','need','necesito')): score+=10; reasons.append('buying_language')
    return min(score,100),reasons


def _stage(row: dict[str, Any]) -> str:
    if str(row.get('qualification_status') or '').upper()=='QUALIFIED': return 'QUALIFIED_DEMAND'
    if row.get('intake_id') and (row.get('product_need') or row.get('product_description')): return 'RFQ_INTAKE'
    if str(row.get('sales_status') or '').upper() in {'REPLIED','QUALIFIED_LEAD'}: return 'QUALIFICATION'
    return 'RESEARCH'


def _next_action(row: dict[str, Any], score: int) -> str:
    missing=[]
    if not (row.get('product_need') or row.get('product_description')): missing.append('product')
    if not row.get('quantity'): missing.append('quantity')
    if not (row.get('destination_country') or row.get('destination')): missing.append('destination')
    if missing: return 'Qualify '+', '.join(missing)+' before supplier disclosure or firm pricing.'
    if score>=70: return 'Source 3 comparable suppliers, verify KYB/payment path, and prepare protected-margin quotation.'
    return 'Enrich buyer context and validate timing, specifications, budget/payment preference and authority.'


async def _sources(limit:int) -> list[dict[str, Any]]:
    b=get_backend(); out=[]
    for table,source in (('customer_accounts','customer_crm'),('customer_trade_intakes','trade_intake'),('external_trade_prospects','external_research'),('whatsapp_leads','whatsapp')):
        try:
            rows=await b.select(table,params={'limit':str(limit)}) or []
            for r in rows: out.append({'_table':table,'_source':source,**r})
        except Exception:
            continue
    return out


@app.get('/crm/sofia/funnel-intelligence/health')
async def health():
    p=persistent_backend_status()
    return {'status':'ok' if p.get('configured') else 'configuration_required','service':'sofia-funnel-intelligence','daily_refresh':True,'all_funnel_sources':True,'catalog_matching':True,'commercial_scoring':True,'next_best_action':True,'supplier_research_queue':True,'binding_actions_allowed':False,'cold_bulk_marketing':False,'canonical_backend':'supabase'}


@app.get('/crm/sofia/funnel-intelligence')
async def intelligence(authorization:str|None=Header(None,alias='Authorization'),limit:int=Query(250,ge=1,le=5000)):
    _authorized(authorization)
    rows=await _sources(limit)
    result=[]
    for r in rows[:limit]:
        score,reasons=_commercial_score(r); recs=_recommend(r)
        result.append({'lead_ref':r.get('intake_id') or r.get('customer_id') or r.get('prospect_id') or r.get('lead_id'),'source':r['_source'],'company':r.get('legal_name') or r.get('buyer_company') or r.get('business_name') or r.get('company_name'),'segments':_segment(r),'commercial_score':score,'score_reasons':reasons,'stage':_stage(r),'recommended_products':recs,'next_best_action':_next_action(r,score),'supplier_research_priority':'HIGH' if score>=70 else 'NORMAL' if score>=45 else 'LOW','protected_economics_status':'UNSET_UNTIL_QUOTE','binding_action':False})
    result.sort(key=lambda x:-x['commercial_score'])
    return {'status':'ok','agent':'SOFIA','count':len(result),'leads':result,'rule':'Research and recommendations do not create qualified demand, firm quotations, contracts, invoices, commissions or revenue.'}


@app.get('/crm/sofia/daily-refresh')
async def daily_refresh(authorization:str|None=Header(None,alias='Authorization'),limit:int=Query(5000,ge=1,le=25000)):
    _authorized(authorization)
    rows=await _sources(limit)
    ts=now(); b=get_backend(); written=0; high=0
    for r in rows[:limit]:
        ref=str(r.get('intake_id') or r.get('customer_id') or r.get('prospect_id') or r.get('lead_id') or '')
        if not ref: continue
        score,reasons=_commercial_score(r); recs=_recommend(r)
        key='sfi_'+hashlib.sha256((r['_source']+'|'+ref).encode()).hexdigest()[:28]
        payload={'organization_id':ORG,'source':r['_source'],'lead_ref':ref,'company':r.get('legal_name') or r.get('buyer_company') or r.get('business_name') or r.get('company_name'),'segments':_segment(r),'commercial_score':score,'score_reasons':reasons,'commercial_stage':_stage(r),'recommended_products':recs,'next_best_action':_next_action(r,score),'supplier_research_priority':'HIGH' if score>=70 else 'NORMAL' if score>=45 else 'LOW','protected_economics_status':'UNSET_UNTIL_QUOTE','last_sofia_refresh':ts,'qualified_demand_inferred':False,'firm_quote_inferred':False,'contract_inferred':False,'invoice_inferred':False,'revenue_inferred':False,'binding_actions_allowed':False}
        await b.upsert('sahjony_trade_records',{'logical_table':'sofia_funnel_intelligence','record_key':key,'data':payload,'updated_at':ts},on_conflict='logical_table,record_key')
        written+=1
        if score>=70: high+=1
    return {'status':'ok','agent':'SOFIA','refreshed_at':ts,'records_evaluated':len(rows[:limit]),'records_written':written,'high_priority_supplier_research':high,'autonomous_scope':'research, scoring, catalog matching, next-best-action and supplier-research prioritization','outreach_sent':0,'binding_actions':0}
