from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Global Trade Collaboration', version='1.1.0', docs_url=None, redoc_url=None)
ParticipantType = Literal[
    'customer','buyer','supplier','customs_broker','freight_forwarder','carrier','inspector','warehouse_3pl',
    'insurer','bank_finance','attorney','accountant','government_agency','agent','consultant','other'
]
ALLOWED_MODULES = {'messages','documents','shipping','compliance','commercial_status','tasks','quotes','payments','qc','claims'}
ALLOWED_PERMISSIONS = {'view','comment','upload','acknowledge','download'}

class ParticipantCreate(BaseModel):
    participant_type: ParticipantType
    legal_name: str | None = Field(default=None,max_length=240)
    contact_name: str | None = Field(default=None,max_length=180)
    email: str | None = Field(default=None,max_length=320)
    phone_e164: str | None = Field(default=None,max_length=40)
    company_name: str | None = Field(default=None,max_length=240)
    preferred_locale: str = Field(default='en-US',max_length=35)

class GrantCreate(BaseModel):
    participant_id: str | None = Field(default=None,max_length=180)
    trade_case_id: str | None = Field(default=None,max_length=180)
    customer_id: str | None = Field(default=None,max_length=180)
    recipient_email: str | None = Field(default=None,max_length=320)
    scope_modules: list[str] = Field(min_length=1,max_length=20)
    permissions: list[str] = Field(default_factory=lambda:['view'])
    allowed_resource_ids: list[str] = Field(default_factory=list,max_length=100)
    preferred_locale: str = Field(default='en-US',max_length=35)
    allow_download: bool = False
    allow_upload: bool = False
    allow_comment: bool = True
    require_verified_identity: bool = True
    max_uses: int | None = Field(default=None,ge=1,le=10000)
    expires_in_hours: int = Field(default=168,ge=1,le=2160)

class ShareItemCreate(BaseModel):
    module: str = Field(min_length=2,max_length=80)
    resource_type: str = Field(min_length=2,max_length=80)
    resource_id: str | None = Field(default=None,max_length=180)
    title: str = Field(min_length=1,max_length=240)
    summary: str | None = Field(default=None,max_length=4000)
    payload: dict[str,Any] = Field(default_factory=dict)
    source_locale: str = Field(default='en-US',max_length=35)
    legal_or_regulatory: bool = False

class CommentCreate(BaseModel):
    resource_type: str | None = Field(default=None,max_length=80)
    resource_id: str | None = Field(default=None,max_length=180)
    body: str = Field(min_length=1,max_length=6000)
    source_locale: str | None = Field(default=None,max_length=35)


def now(): return datetime.now(timezone.utc)
def now_iso(): return now().isoformat()
def hash_token(token: str): return hashlib.sha256(token.encode('utf-8')).hexdigest()
def hash_meta(value: str | None): return hashlib.sha256((value or '').encode('utf-8')).hexdigest() if value else None

def employee_token():
    token=os.getenv('EMPLOYEE_TOKEN','').strip()
    if not token: raise HTTPException(503,'Employee collaboration access is not configured')
    return token

def identity(role, authorization, employee_id):
    if role not in {'owner','employee'}: raise HTTPException(400,'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
    token=authorization.removeprefix('Bearer ').strip()
    if role=='owner':
        if not verify_owner_token(token): raise HTTPException(403,'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if not secrets.compare_digest(token,employee_token()): raise HTTPException(403,'Invalid employee credential')
    return {'role':'employee','id':(employee_id or 'staff')[:160]}

async def audit(grant_id, action, outcome, request: Request | None=None, participant_id=None, resource_type=None, resource_id=None, detail=None):
    ua=request.headers.get('user-agent') if request else None
    ip=request.client.host if request and request.client else None
    await get_backend().insert('collaboration_access_events',{
        'event_id':f'cae_{secrets.token_urlsafe(14)}','grant_id':grant_id,'participant_id':participant_id,
        'action':action,'resource_type':resource_type,'resource_id':resource_id,'outcome':outcome,
        'ip_hash':hash_meta(ip),'user_agent_hash':hash_meta(ua),'detail':detail,'created_at':now_iso()})

async def verified_participant(participant_id: str | None):
    if not participant_id: return False
    rows=await get_backend().select('collaboration_participants',params={'participant_id':f'eq.{participant_id}','limit':'1'}) or []
    return bool(rows and rows[0].get('verification_status')=='verified')

async def load_grant(raw_token: str, request: Request, action='view'):
    rows=await get_backend().select('collaboration_grants',params={'token_hash':f'eq.{hash_token(raw_token)}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Share grant not found')
    g=rows[0]
    if g.get('status')!='active':
        await audit(g['grant_id'],action,'denied',request,g.get('participant_id'),detail='Grant not active')
        raise HTTPException(410,'Share grant is not active')
    try: expires=datetime.fromisoformat(str(g['expires_at']).replace('Z','+00:00'))
    except Exception: raise HTTPException(410,'Share grant expiry invalid')
    if expires <= now():
        await get_backend().patch('collaboration_grants',{'status':'expired'},params={'grant_id':f"eq.{g['grant_id']}"})
        await audit(g['grant_id'],action,'expired',request,g.get('participant_id'))
        raise HTTPException(410,'Share grant expired')
    max_uses=g.get('max_uses')
    if max_uses is not None and int(g.get('use_count') or 0)>=int(max_uses):
        await get_backend().patch('collaboration_grants',{'status':'exhausted'},params={'grant_id':f"eq.{g['grant_id']}"})
        await audit(g['grant_id'],action,'denied',request,g.get('participant_id'),detail='Max uses reached')
        raise HTTPException(410,'Share grant exhausted')
    if g.get('require_verified_identity') and not await verified_participant(g.get('participant_id')):
        await audit(g['grant_id'],action,'denied',request,g.get('participant_id'),detail='Participant verification required')
        raise HTTPException(403,'Verified participant identity required')
    return g

@app.get('/collaboration/health')
async def health():
    return {'status':'ok','service':'governed-collaboration','raw_tokens_stored':False,'revocable':True,'expiring':True,'least_privilege':True,'curated_share_items':True}

@app.post('/collaboration/participants')
async def create_participant(payload: ParticipantCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); pid=f'pty_{secrets.token_urlsafe(12)}'; ts=now_iso()
    row={'participant_id':pid,**payload.model_dump(),'verification_status':'pending','created_by_role':actor['role'],'created_by_id':actor['id'],'created_at':ts,'updated_at':ts}
    await get_backend().insert('collaboration_participants',row); return {'participant':row}

@app.post('/collaboration/participants/{participant_id}/verify')
async def verify_participant(participant_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner': raise HTTPException(403,'Owner verification required')
    result=await get_backend().patch('collaboration_participants',{'verification_status':'verified','updated_at':now_iso()},params={'participant_id':f'eq.{participant_id}'})
    return {'participant_id':participant_id,'verification_status':'verified','persistence':result}

@app.get('/collaboration/participants')
async def list_participants(x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role,authorization,x_employee_id)
    return {'participants':await get_backend().select('collaboration_participants',params={'order':'updated_at.desc','limit':'500'}) or []}

@app.post('/collaboration/grants')
async def create_grant(payload: GrantCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); modules=set(payload.scope_modules); perms=set(payload.permissions)
    if not modules.issubset(ALLOWED_MODULES): raise HTTPException(400,'Unsupported share module')
    if not perms.issubset(ALLOWED_PERMISSIONS): raise HTTPException(400,'Unsupported share permission')
    if payload.require_verified_identity and not payload.participant_id: raise HTTPException(400,'Verified shares require participant_id')
    if payload.require_verified_identity and not await verified_participant(payload.participant_id): raise HTTPException(409,'Participant must be owner-verified before this share can be created')
    if 'download' in perms and not payload.allow_download: raise HTTPException(400,'Download permission requires allow_download=true')
    if 'upload' in perms and not payload.allow_upload: raise HTTPException(400,'Upload permission requires allow_upload=true')
    if 'comment' in perms and not payload.allow_comment: raise HTTPException(400,'Comment permission requires allow_comment=true')
    if actor['role']=='employee' and modules.intersection({'quotes','payments','commercial_status'}): raise HTTPException(403,'Owner approval required to share commercial/payment scope')
    raw=secrets.token_urlsafe(32); gid=f'grt_{secrets.token_urlsafe(14)}'; expires=now()+timedelta(hours=payload.expires_in_hours)
    row={'grant_id':gid,'participant_id':payload.participant_id,'trade_case_id':payload.trade_case_id,'scope_modules':sorted(modules),'permissions':sorted(perms),
         'allowed_resource_ids':payload.allowed_resource_ids,'customer_id':payload.customer_id,'recipient_email':payload.recipient_email,
         'token_hash':hash_token(raw),'token_hint':raw[-6:],'preferred_locale':payload.preferred_locale,'allow_download':payload.allow_download,
         'allow_upload':payload.allow_upload,'allow_comment':payload.allow_comment,'allow_reshare':False,'require_verified_identity':payload.require_verified_identity,
         'max_uses':payload.max_uses,'use_count':0,'expires_at':expires.isoformat(),'status':'active','created_by_role':actor['role'],'created_by_id':actor['id'],'created_at':now_iso()}
    await get_backend().insert('collaboration_grants',row)
    return {'grant':{k:v for k,v in row.items() if k!='token_hash'},'share_token':raw,'share_path':f'/share?token={raw}'}

@app.get('/collaboration/grants')
async def list_grants(trade_case_id: str|None=Query(default=None,max_length=180), x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role,authorization,x_employee_id); params={'order':'created_at.desc','limit':'500'}
    if trade_case_id: params['trade_case_id']=f'eq.{trade_case_id}'
    rows=await get_backend().select('collaboration_grants',params=params) or []
    for r in rows: r.pop('token_hash',None)
    return {'grants':rows}

@app.post('/collaboration/grants/{grant_id}/items')
async def add_share_item(grant_id: str, payload: ShareItemCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    grants=await get_backend().select('collaboration_grants',params={'grant_id':f'eq.{grant_id}','limit':'1'}) or []
    if not grants: raise HTTPException(404,'Grant not found')
    g=grants[0]
    if payload.module not in (g.get('scope_modules') or []): raise HTTPException(403,'Module outside share grant')
    if actor['role']=='employee' and payload.module in {'quotes','payments','commercial_status'}: raise HTTPException(403,'Owner approval required for commercial/payment sharing')
    iid=f'shi_{secrets.token_urlsafe(12)}'; row={'item_id':iid,'grant_id':grant_id,'module':payload.module,'resource_type':payload.resource_type,
        'resource_id':payload.resource_id,'title':payload.title,'summary':payload.summary,'payload':payload.payload,'source_locale':payload.source_locale,
        'legal_or_regulatory':payload.legal_or_regulatory,'created_by_role':actor['role'],'created_by_id':actor['id'],'created_at':now_iso()}
    await get_backend().insert('collaboration_shared_items',row); return {'item':row}

@app.post('/collaboration/grants/{grant_id}/revoke')
async def revoke_grant(grant_id: str, request: Request, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    result=await get_backend().patch('collaboration_grants',{'status':'revoked','revoked_at':now_iso(),'revoked_by_role':actor['role'],'revoked_by_id':actor['id']},params={'grant_id':f'eq.{grant_id}'})
    await audit(grant_id,'revoke','revoked',request,detail=f"Revoked by {actor['role']}:{actor['id']}")
    return {'grant_id':grant_id,'status':'revoked','persistence':result}

@app.get('/collaboration/access')
async def access_share(request: Request, token: str=Query(min_length=20,max_length=200)):
    g=await load_grant(token,request,'access')
    await get_backend().patch('collaboration_grants',{'use_count':int(g.get('use_count') or 0)+1},params={'grant_id':f"eq.{g['grant_id']}"})
    items=await get_backend().select('collaboration_shared_items',params={'grant_id':f"eq.{g['grant_id']}",'order':'created_at.asc','limit':'500'}) or []
    await audit(g['grant_id'],'access','allowed',request,g.get('participant_id'))
    return {'grant':{k:v for k,v in g.items() if k!='token_hash'},'items':items,'policy':{
        'modules':g.get('scope_modules') or [],'permissions':g.get('permissions') or [],'allow_download':bool(g.get('allow_download')),
        'allow_upload':bool(g.get('allow_upload')),'allow_comment':bool(g.get('allow_comment')),'allow_reshare':False}}

@app.post('/collaboration/comments')
async def add_comment(payload: CommentCreate, request: Request, x_share_token: str|None=Header(None,alias='X-Share-Token')):
    if not x_share_token: raise HTTPException(401,'Missing X-Share-Token')
    g=await load_grant(x_share_token,request,'comment')
    if not g.get('allow_comment') or 'comment' not in (g.get('permissions') or []):
        await audit(g['grant_id'],'comment','denied',request,g.get('participant_id'),payload.resource_type,payload.resource_id,'Comment not permitted')
        raise HTTPException(403,'Commenting not permitted')
    allowed_ids=g.get('allowed_resource_ids') or []
    if allowed_ids and payload.resource_id and payload.resource_id not in allowed_ids: raise HTTPException(403,'Resource outside grant scope')
    cid=f'cmt_{secrets.token_urlsafe(12)}'; row={'comment_id':cid,'grant_id':g['grant_id'],'trade_case_id':g.get('trade_case_id'),
        'participant_id':g.get('participant_id'),'resource_type':payload.resource_type,'resource_id':payload.resource_id,'body':payload.body,
        'source_locale':payload.source_locale or g.get('preferred_locale'),'created_at':now_iso()}
    await get_backend().insert('collaboration_comments',row)
    await audit(g['grant_id'],'comment','allowed',request,g.get('participant_id'),payload.resource_type,payload.resource_id)
    return {'comment':row}
