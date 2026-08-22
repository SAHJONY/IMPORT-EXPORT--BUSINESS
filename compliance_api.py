from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_customer_token, verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Global Trade Compliance", version="1.0.0", docs_url=None, redoc_url=None)
Role = Literal['owner','employee','customer']

BASE_REQUIREMENTS = [
    ('party_screening','OFAC/BIS','Restricted/denied-party screening'),
    ('classification','CBP/BIS/Census','HTS / Schedule B / ECCN determination'),
    ('origin','CBP','Country of origin and marking review'),
    ('valuation','CBP','Customs valuation and related-party/assist review'),
    ('incoterms','Contract','Incoterm and responsibility allocation'),
    ('documents','CBP/Carrier','Commercial invoice, packing list, transport document'),
    ('broker_authority','CBP','Broker/forwarder authority and POA if applicable'),
    ('bond','CBP','Customs bond applicability and sufficiency'),
    ('entry','CBP','Cargo release and entry summary readiness'),
    ('recordkeeping','CBP/BIS/Census','Regulatory record retention and audit evidence'),
]
EXPORT_REQUIREMENTS = [
    ('ear_scope','BIS','EAR jurisdiction / subject-to-EAR determination'),
    ('license','BIS','License / license exception / NLR determination'),
    ('end_use','BIS','End-use and end-user review'),
    ('eei','Census/BIS','AES/EEI filing determination and ITN when required'),
]
IMPORT_REQUIREMENTS = [
    ('admissibility','CBP','Import admissibility and prohibited/restricted merchandise review'),
    ('pga','Partner Government Agencies','Product-agency applicability review (FDA/USDA/EPA/FCC/CPSC/etc.)'),
    ('duties','CBP/HTSUS','Duty, tariff, trade-remedy and special-program review'),
]

class ComplianceCreate(BaseModel):
    trade_case_id: str = Field(min_length=1,max_length=160)
    shipment_id: str | None = Field(default=None,max_length=160)
    customer_id: str | None = Field(default=None,max_length=160)
    direction: Literal['import','export','domestic','cross_trade']
    origin_country: str | None = Field(default=None,max_length=100)
    destination_country: str | None = Field(default=None,max_length=100)
    importer_of_record: str | None = Field(default=None,max_length=240)
    exporter_usppi: str | None = Field(default=None,max_length=240)
    consignee: str | None = Field(default=None,max_length=240)
    end_user: str | None = Field(default=None,max_length=240)
    incoterm: str | None = Field(default=None,max_length=20)
    customer_visible: bool = False

class RequirementUpdate(BaseModel):
    status: Literal['open','in_progress','satisfied','waived','blocked']
    evidence_document_id: str | None = Field(default=None,max_length=160)
    filing_reference: str | None = Field(default=None,max_length=240)
    notes: str | None = Field(default=None,max_length=2000)


def now(): return datetime.now(timezone.utc).isoformat()

def employee_token():
    token=os.getenv('EMPLOYEE_TOKEN')
    if not token: raise HTTPException(503,'Employee compliance access is not configured')
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

async def audit(compliance_id,actor,event_type,detail,release_effect='none'):
    await get_backend().insert('compliance_audit_events',{
        'event_id':f'cae_{secrets.token_urlsafe(14)}','compliance_id':compliance_id,
        'actor_role':actor['role'],'actor_id':actor['id'],'event_type':event_type,
        'detail':detail,'release_effect':release_effect,'created_at':now()})

async def publish_event(row,actor,title,body,severity='info',action_required=False):
    try:
        await get_backend().insert('business_events',{
            'event_id':f'evt_{secrets.token_urlsafe(14)}','trade_case_id':row['trade_case_id'],
            'customer_id':row.get('customer_id'),'event_type':'compliance','source':'compliance_api',
            'source_ref':row['compliance_id'],'title':title,'body':body,'severity':severity,
            'action_required':action_required,'customer_visible':bool(row.get('customer_visible')),
            'actor_role':actor['role'],'actor_id':actor['id'],'created_at':now()})
    except Exception:
        pass

@app.get('/compliance/health')
async def health():
    return {'status':'ok','service':'trade-compliance','fail_closed':True,'persistence':'insforge'}

@app.post('/compliance')
async def create_case(payload: ComplianceCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']=='customer': raise HTTPException(403,'Customers cannot create compliance cases')
    cid=f'cmp_{secrets.token_urlsafe(14)}'; ts=now()
    row={'compliance_id':cid,**payload.model_dump(),'created_by_role':actor['role'],'created_by_id':actor['id'],'created_at':ts,'updated_at':ts}
    await get_backend().insert('trade_compliance_cases',row)
    reqs=list(BASE_REQUIREMENTS)
    if payload.direction in {'export','cross_trade'}: reqs+=EXPORT_REQUIREMENTS
    if payload.direction in {'import','cross_trade'}: reqs+=IMPORT_REQUIREMENTS
    await get_backend().insert('compliance_requirements',[{
        'requirement_id':f'req_{secrets.token_urlsafe(12)}','compliance_id':cid,'category':cat,
        'authority':auth,'requirement_name':name,'applicability':'review','status':'open',
        'created_at':ts,'updated_at':ts} for cat,auth,name in reqs])
    await audit(cid,actor,'case_created','Compliance case created','block')
    await publish_event(row,actor,'Compliance review opened','Trade release is blocked until required legal/customs controls are satisfied.','warning',True)
    return {'compliance':row,'requirements_created':len(reqs)}

@app.get('/compliance')
async def list_cases(trade_case_id: str|None=Query(default=None,max_length=160), customer_id: str|None=Query(default=None,max_length=160), x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); params={'order':'updated_at.desc','limit':'250'}
    if trade_case_id: params['trade_case_id']=f'eq.{trade_case_id}'
    if actor['role']=='customer':
        params['customer_id']=f'eq.{actor["id"]}'; params['customer_visible']='eq.true'
    elif customer_id: params['customer_id']=f'eq.{customer_id}'
    rows=await get_backend().select('trade_compliance_cases',params=params)
    return {'compliance_cases':rows or [],'actor':actor}

@app.get('/compliance/{compliance_id}/requirements')
async def requirements(compliance_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    cases=await get_backend().select('trade_compliance_cases',params={'compliance_id':f'eq.{compliance_id}','limit':'1'})
    if not cases: raise HTTPException(404,'Compliance case not found')
    case=cases[0]
    if actor['role']=='customer' and (case.get('customer_id')!=actor['id'] or not case.get('customer_visible')): raise HTTPException(403,'Customer scope mismatch')
    rows=await get_backend().select('compliance_requirements',params={'compliance_id':f'eq.{compliance_id}','order':'created_at.asc','limit':'250'})
    return {'requirements':rows or []}

@app.patch('/compliance/{compliance_id}/requirements/{requirement_id}')
async def update_requirement(compliance_id: str, requirement_id: str, payload: RequirementUpdate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']=='customer': raise HTTPException(403,'Customers cannot change compliance controls')
    values=payload.model_dump(exclude_none=True); values['updated_at']=now()
    if payload.status in {'satisfied','waived'}:
        values['completed_at']=now(); values['completed_by_role']=actor['role']; values['completed_by_id']=actor['id']
    result=await get_backend().patch('compliance_requirements',values,params={'requirement_id':f'eq.{requirement_id}','compliance_id':f'eq.{compliance_id}'})
    await audit(compliance_id,actor,'requirement_updated',f'{requirement_id} -> {payload.status}','review' if payload.status=='blocked' else 'none')
    return {'requirement_id':requirement_id,'status':payload.status,'persistence':result}

@app.post('/compliance/{compliance_id}/evaluate-release')
async def evaluate_release(compliance_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']=='customer': raise HTTPException(403,'Customers cannot evaluate release')
    cases=await get_backend().select('trade_compliance_cases',params={'compliance_id':f'eq.{compliance_id}','limit':'1'})
    if not cases: raise HTTPException(404,'Compliance case not found')
    reqs=await get_backend().select('compliance_requirements',params={'compliance_id':f'eq.{compliance_id}','limit':'250'})
    unresolved=[r for r in (reqs or []) if r.get('applicability')!='not_applicable' and r.get('status') not in {'satisfied','waived'}]
    status='ready' if not unresolved else 'blocked'
    await get_backend().patch('trade_compliance_cases',{'release_status':status,'updated_at':now()},params={'compliance_id':f'eq.{compliance_id}'})
    await audit(compliance_id,actor,'release_evaluated',f'{len(unresolved)} unresolved requirement(s)','unblock' if status=='ready' else 'block')
    return {'compliance_id':compliance_id,'release_status':status,'unresolved_count':len(unresolved),'unresolved':unresolved}

@app.post('/compliance/{compliance_id}/owner-release')
async def owner_release(compliance_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner': raise HTTPException(403,'Final compliance release is owner-only')
    reqs=await get_backend().select('compliance_requirements',params={'compliance_id':f'eq.{compliance_id}','limit':'250'})
    unresolved=[r for r in (reqs or []) if r.get('applicability')!='not_applicable' and r.get('status') not in {'satisfied','waived'}]
    if unresolved: raise HTTPException(409,f'Compliance release blocked: {len(unresolved)} unresolved requirement(s)')
    result=await get_backend().patch('trade_compliance_cases',{'release_status':'released','legal_status':'approved','updated_at':now()},params={'compliance_id':f'eq.{compliance_id}'})
    await audit(compliance_id,actor,'owner_release','Final owner compliance release','unblock')
    return {'compliance_id':compliance_id,'release_status':'released','persistence':result}
