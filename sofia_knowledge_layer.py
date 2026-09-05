from __future__ import annotations
import asyncio, json, os, re, time
from typing import Any
import httpx
from insforge_backend import get_backend

_CUBA_HEALTH = os.getenv('SOFIA_CUBA_CRM_HEALTH_URL','https://www.sahjony.com/crm/cuba-mipymes/health').strip()
_CACHE: dict[str, tuple[float, Any]] = {}
TTL = 300

def _norm(s:str)->str: return re.sub(r'\s+',' ',(s or '').lower()).strip()
def _tokens(s:str)->list[str]:
    stop={'the','and','for','with','from','para','con','que','los','las','una','uno','del','por','what','have','tenemos','cuba','mipyme','mipymes','lead','leads'}
    return [x for x in re.findall(r'[a-záéíóúñ0-9][a-záéíóúñ0-9_-]{2,}',_norm(s)) if x not in stop][:10]
def _is_cuba(s:str)->bool: return any(x in _norm(s) for x in ('cuba','cubano','cubana','mipyme','mipymes','mariel','habana'))
def _inventory_ask(s:str)->bool: return any(x in _norm(s) for x in ('que tenemos','qué tenemos','hay leads','hay oportunidades','cuantos leads','cuántos leads','what leads','what opportunities','crm','base de datos','database','prospectos','registros'))

async def _cached_select(table:str, limit:int=10000)->list[dict[str,Any]]:
    now=time.monotonic(); hit=_CACHE.get(table)
    if hit and now-hit[0] < TTL: return hit[1]
    try: rows=await get_backend().select(table,params={'limit':str(limit)}) or []
    except Exception: rows=[]
    _CACHE[table]=(now,rows); return rows

async def _cuba_snapshot()->dict[str,Any]:
    try:
        async with httpx.AsyncClient(timeout=10,follow_redirects=True) as c:
            r=await c.get(_CUBA_HEALTH,headers={'Accept':'application/json'}); r.raise_for_status(); d=r.json()
        return {'verified':True,'record_count':int(d.get('record_count') or 0),'target':int(d.get('target') or 0),'remaining_shortfall':int(d.get('remaining_shortfall') or 0),'count_semantics':d.get('count_semantics'),'source_scope':d.get('source_scope'),'ownership_policy':d.get('ownership_policy')}
    except Exception as e: return {'verified':False,'reason':type(e).__name__}

def _score(row:dict[str,Any], tokens:list[str])->int:
    if not tokens:return 0
    blob=_norm(json.dumps(row,ensure_ascii=False,default=str))
    return sum(3 if t in _norm(str(row.get('product_need_or_offer') or row.get('product_need') or '')) else 1 for t in tokens if t in blob)

def _compact(row:dict[str,Any])->dict[str,Any]:
    keys=('business_name','company_name','legal_name','contact_name','country','country_code','city_region','lead_type','deal_side','product_need_or_offer','product_need','status','qualification_status','source_url','source_description','notes','updated_at')
    return {k:row.get(k) for k in keys if row.get(k) not in (None,'')}

async def build_business_knowledge(text:str, contact_context:dict[str,Any]|None=None)->dict[str,Any]:
    tokens=_tokens(text); cuba=_is_cuba(text); inventory=_inventory_ask(text)
    result:dict[str,Any]={'mode':'context_first','query':text[:500],'stage_semantics':{'prospect':'research record, not automatically qualified','lead':'contact with commercial relevance','qualified_demand':'evidence-backed requirement','opportunity':'qualified commercial case with next action','rfq':'complete request for quotation','quote':'firm or explicitly non-binding quotation as labeled','contracted':'binding only after authorized agreement','collected':'revenue actually received'}}
    if contact_context:
        result['contact']={'whatsapp_leads':contact_context.get('whatsapp_leads',[])[:3],'customers':contact_context.get('customers',[])[:3],'trade_intakes':contact_context.get('trade_intakes',[])[:8],'recent_events':contact_context.get('recent_events',[])[:8]}
    if cuba:
        result['cuba_private_sector']=await _cuba_snapshot()
    # Only load broad research inventory when the message asks inventory or contains product terms.
    if inventory or tokens:
        tables=['external_trade_prospects','customer_trade_intakes','whatsapp_leads']
        rows_by=await asyncio.gather(*[_cached_select(t) for t in tables])
        matches=[]
        for table,rows in zip(tables,rows_by):
            for row in rows:
                if cuba and table=='external_trade_prospects':
                    blob=_norm(json.dumps(row,ensure_ascii=False,default=str))
                    if not any(x in blob for x in ('"cu"','cuba','mipyme','habana','havana','mariel')): continue
                score=_score(row,tokens)
                if score>0 or (inventory and cuba and table=='external_trade_prospects'):
                    matches.append((score,table,row))
        matches.sort(key=lambda x:x[0],reverse=True)
        result['relevant_records']=[{'source':t,'score':s,'record':_compact(r)} for s,t,r in matches[:12]]
        result['retrieval_counts']={t:len(rows) for t,rows in zip(tables,rows_by)}
    result['truth_rules']=[
        'Never say no records/leads/opportunities exist unless the relevant source was checked in this turn.',
        'Never equate research prospects with qualified leads or active opportunities.',
        'When broad inventory exists, answer with what is verified and propose segmentation/prioritization instead of asking the owner to start from zero.',
        'If a source is unavailable, state that verification is unavailable; do not convert unavailable into zero.'
    ]
    return result
