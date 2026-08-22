from __future__ import annotations

import os
import secrets
import time
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from auth import verify_customer_token, verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Global Language & Translation', version='1.1.0', docs_url=None, redoc_url=None)
Role = Literal['owner','employee','customer']

RTL_LANGS = {'ar','fa','he','ur','ps','sd','ug','yi'}
CORE_LOCALES = [
    'en-US','es','fr','pt-BR','de','it','nl','pl','ru','uk','tr','ar','he','fa','ur',
    'hi','bn','pa','ta','te','mr','gu','zh-Hans','zh-Hant','ja','ko','vi','th','id','ms',
    'fil','sw','am','ha','yo','ig','zu','af','el','cs','ro','hu','sv','no','da','fi'
]
PUBLIC_WINDOW: dict[str, list[float]] = {}

class PreferenceUpdate(BaseModel):
    primary_locale: str = Field(default='en-US', min_length=2, max_length=35)
    fallback_locale: str = Field(default='en-US', min_length=2, max_length=35)
    auto_translate: bool = True
    bilingual_view: bool = True
    translate_messages: bool = True
    translate_documents: bool = False
    translate_notifications: bool = True
    require_human_review_for_legal: bool = True
    timezone: str = Field(default='UTC', max_length=80)

class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    target_locale: str = Field(min_length=2, max_length=35)
    source_locale: str | None = Field(default=None, max_length=35)
    source_type: str = Field(default='ad_hoc', max_length=80)
    source_id: str | None = Field(default=None, max_length=180)
    field_name: str = Field(default='text', max_length=80)
    legal_or_regulatory: bool = False

class BatchTranslateRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=100)
    target_locale: str = Field(min_length=2, max_length=35)
    source_locale: str | None = Field(default=None, max_length=35)
    source_type: str = Field(default='ui', max_length=80)

class ReviewRequest(BaseModel):
    status: Literal['approved','rejected']
    note: str | None = Field(default=None, max_length=1000)


def now(): return datetime.now(timezone.utc).isoformat()

def employee_token():
    token=os.getenv('EMPLOYEE_TOKEN')
    if not token: raise HTTPException(503,'Employee language access is not configured')
    return token

def identity(role, authorization, employee_id):
    if role not in {'owner','employee','customer'}: raise HTTPException(400,'Invalid X-Role')
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
    token=authorization.removeprefix('Bearer ').strip()
    if role=='owner':
        if not verify_owner_token(token): raise HTTPException(403,'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if role=='employee':
        if not secrets.compare_digest(token,employee_token()): raise HTTPException(403,'Invalid employee credential')
        return {'role':'employee','id':(employee_id or 'staff')[:160]}
    c=verify_customer_token(token)
    if not c: raise HTTPException(403,'Invalid customer credential')
    return {'role':'customer','id':str(c['participant_id'])}

def azure_configured():
    return bool(os.getenv('AZURE_TRANSLATOR_KEY','').strip() and os.getenv('AZURE_TRANSLATOR_ENDPOINT','').strip())

def locale_direction(locale: str):
    return 'rtl' if locale.lower().split('-')[0] in RTL_LANGS else 'ltr'

def public_ui_enabled():
    return os.getenv('PUBLIC_UI_TRANSLATION_ENABLED','false').lower()=='true'

def enforce_public_limit(request: Request):
    ip=request.client.host if request.client else 'unknown'; ts=time.time(); window=PUBLIC_WINDOW.setdefault(ip,[])
    window[:]=[x for x in window if ts-x<60]
    max_per_minute=int(os.getenv('PUBLIC_UI_TRANSLATION_RPM','20'))
    if len(window)>=max_per_minute: raise HTTPException(429,'Public UI translation rate limit exceeded')
    window.append(ts)

async def azure_translate(texts: list[str], target: str, source: str|None=None):
    if not azure_configured(): raise HTTPException(503,'Production translation provider is not configured')
    endpoint=os.getenv('AZURE_TRANSLATOR_ENDPOINT','').strip().rstrip('/')
    key=os.getenv('AZURE_TRANSLATOR_KEY','').strip(); region=os.getenv('AZURE_TRANSLATOR_REGION','').strip()
    params={'api-version':'3.0','to':target}
    if source: params['from']=source
    headers={'Ocp-Apim-Subscription-Key':key,'Content-Type':'application/json'}
    if region: headers['Ocp-Apim-Subscription-Region']=region
    async with httpx.AsyncClient(timeout=30) as client:
        r=await client.post(f'{endpoint}/translate',params=params,headers=headers,json=[{'Text':t} for t in texts])
        r.raise_for_status(); data=r.json()
    out=[]
    for item in data:
        trans=(item.get('translations') or [{}])[0]; detected=(item.get('detectedLanguage') or {}).get('language')
        out.append({'text':trans.get('text',''),'detected_language':detected,'to':trans.get('to',target)})
    return out

async def audit(translation_id,actor,action,detail=None):
    await get_backend().insert('translation_audit_events',{'event_id':f'tae_{secrets.token_urlsafe(14)}','translation_id':translation_id,'actor_role':actor['role'],'actor_id':actor['id'],'action':action,'detail':detail,'created_at':now()})

@app.get('/language/health')
async def health():
    return {'status':'ok','service':'global-language','provider':'azure-translator','provider_configured':azure_configured(),'public_ui_translation':public_ui_enabled(),'original_text_preserved':True,'legal_translation_requires_review':True,'rtl_supported':True,'bcp47':True}

@app.get('/language/locales')
async def locales():
    locales=set(CORE_LOCALES)
    endpoint=os.getenv('AZURE_TRANSLATOR_ENDPOINT','https://api.cognitive.microsofttranslator.com').strip().rstrip('/')
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r=await client.get(f'{endpoint}/languages',params={'api-version':'3.0','scope':'translation'})
            if r.is_success:
                locales.update((r.json().get('translation') or {}).keys())
    except httpx.HTTPError:
        pass
    ordered=sorted(locales)
    return {'locales':ordered,'direction':{x:locale_direction(x) for x in ordered},'provider_discovery':True}

@app.post('/language/ui-translate-batch')
async def public_ui_translate(payload: BatchTranslateRequest, request: Request):
    if not public_ui_enabled(): raise HTTPException(503,'Public UI translation is disabled')
    enforce_public_limit(request)
    if payload.source_type!='ui': raise HTTPException(403,'Public endpoint is UI-only')
    if len(payload.texts)>60 or sum(len(t) for t in payload.texts)>12000: raise HTTPException(413,'Public UI translation batch too large')
    result=await azure_translate(payload.texts,payload.target_locale,payload.source_locale)
    return {'translations':result,'target_locale':payload.target_locale,'direction':locale_direction(payload.target_locale)}

@app.get('/language/preferences')
async def get_preferences(x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    rows=await get_backend().select('language_preferences',params={'participant_role':f'eq.{actor["role"]}','participant_id':f'eq.{actor["id"]}','limit':'1'}) or []
    if rows: return {'preferences':rows[0]}
    return {'preferences':{'participant_role':actor['role'],'participant_id':actor['id'],'primary_locale':'en-US','fallback_locale':'en-US','auto_translate':True,'bilingual_view':True,'timezone':'UTC'}}

@app.put('/language/preferences')
async def set_preferences(payload: PreferenceUpdate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); ts=now(); rows=await get_backend().select('language_preferences',params={'participant_role':f'eq.{actor["role"]}','participant_id':f'eq.{actor["id"]}','limit':'1'}) or []
    values={**payload.model_dump(),'updated_at':ts}
    if rows: await get_backend().patch('language_preferences',values,params={'participant_role':f'eq.{actor["role"]}','participant_id':f'eq.{actor["id"]}'})
    else: await get_backend().insert('language_preferences',{'preference_id':f'lng_{secrets.token_urlsafe(12)}','participant_role':actor['role'],'participant_id':actor['id'],**values,'created_at':ts})
    return {'preferences':{'participant_role':actor['role'],'participant_id':actor['id'],**values},'direction':locale_direction(payload.primary_locale)}

@app.post('/language/translate')
async def translate(payload: TranslateRequest, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); sid=payload.source_id or f'adhoc_{secrets.token_urlsafe(10)}'
    cached=await get_backend().select('translations',params={'source_type':f'eq.{payload.source_type}','source_id':f'eq.{sid}','field_name':f'eq.{payload.field_name}','target_locale':f'eq.{payload.target_locale}','limit':'1'}) or []
    if cached and cached[0].get('source_text')==payload.text: return {'translation':cached[0],'cached':True,'direction':locale_direction(payload.target_locale)}
    result=(await azure_translate([payload.text],payload.target_locale,payload.source_locale))[0]; tid=f'trn_{secrets.token_urlsafe(14)}'; review=payload.legal_or_regulatory
    row={'translation_id':tid,'source_type':payload.source_type,'source_id':sid,'field_name':payload.field_name,'source_locale':payload.source_locale or result.get('detected_language'),'target_locale':payload.target_locale,'source_text':payload.text,'translated_text':result['text'],'provider':'azure-translator','provider_model':'text-v3','confidence':None,'legal_or_regulatory':payload.legal_or_regulatory,'human_review_required':review,'human_review_status':'pending' if review else 'not_required','created_at':now()}
    await get_backend().insert('translations',row); await audit(tid,actor,'translated','Original preserved; translation created')
    return {'translation':row,'cached':False,'direction':locale_direction(payload.target_locale),'authoritative':False if review else None,'notice':'Legal/customs translation requires designated human review.' if review else None}

@app.post('/language/translate-batch')
async def translate_batch(payload: BatchTranslateRequest, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role,authorization,x_employee_id)
    if sum(len(t) for t in payload.texts)>30000: raise HTTPException(413,'Translation batch too large')
    result=await azure_translate(payload.texts,payload.target_locale,payload.source_locale)
    return {'translations':result,'target_locale':payload.target_locale,'direction':locale_direction(payload.target_locale)}

@app.patch('/language/translations/{translation_id}/review')
async def review_translation(translation_id: str, payload: ReviewRequest, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']=='customer': raise HTTPException(403,'Customers cannot approve regulated translations')
    rows=await get_backend().select('translations',params={'translation_id':f'eq.{translation_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Translation not found')
    if rows[0].get('legal_or_regulatory') and actor['role']!='owner': raise HTTPException(403,'Owner approval required for legal/regulatory translations')
    values={'human_review_status':payload.status,'reviewed_by_role':actor['role'],'reviewed_by_id':actor['id'],'reviewed_at':now()}
    await get_backend().patch('translations',values,params={'translation_id':f'eq.{translation_id}'})
    await audit(translation_id,actor,f'review_{payload.status}',payload.note)
    return {'translation_id':translation_id,'review_status':payload.status,'reviewed_by':actor}
