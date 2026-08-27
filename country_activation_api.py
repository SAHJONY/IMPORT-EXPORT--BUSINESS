from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend
from payment_engine import CANONICAL_TRANSACTION_CURRENCY, USD_ONLY_TRANSACTIONS

app = FastAPI(title='SAHJONY Global Country Activation', version='1.2.0', docs_url=None, redoc_url=None)
Role = Literal['owner','employee']
Status = Literal['READY','LIMITED','BLOCKED']
ControlStatus = Literal['READY','LIMITED','BLOCKED','NOT_APPLICABLE']

FREE_CUBA_CODE = 'XCU'
FREE_CUBA_NAME = 'Free Cuba (Future Scenario)'

MANDATORY_CONTROLS = [
    ('legal_entity_trading_eligibility','Legal entity / trading eligibility'),
    ('importer_exporter_registration','Importer / exporter registration'),
    ('customs_broker_coverage','Customs broker coverage'),
    ('sanctions_export_controls','Sanctions / export controls'),
    ('product_restrictions','Product restrictions'),
    ('tax_vat_gst','Tax / VAT / GST'),
    ('banking_settlement','Banking / settlement'),
    ('currency_support','Supported currencies'),
    ('freight_carrier_coverage','Freight / carrier coverage'),
    ('cargo_liability_insurance','Cargo / liability insurance'),
    ('document_requirements','Document requirements'),
    ('translation_language','Translation / language'),
    ('local_contracts','Local contracts'),
    ('warehouse_3pl','Warehouse / 3PL'),
    ('data_privacy','Data / privacy'),
    ('accounting_reconciliation','Accounting / reconciliation'),
]
MANDATORY_CONTROL_KEYS = {key for key, _ in MANDATORY_CONTROLS}


class CountryCreate(BaseModel):
    country_code: str = Field(min_length=2,max_length=3)
    country_name: str = Field(min_length=2,max_length=120)
    region: str | None = Field(default=None,max_length=120)
    default_currency: str | None = Field(default=None,max_length=12)
    default_locale: str | None = Field(default=None,max_length=32)
    notes: str | None = Field(default=None,max_length=2000)


class ControlUpdate(BaseModel):
    status: ControlStatus
    evidence_summary: str | None = Field(default=None,max_length=4000)
    evidence_source: str | None = Field(default=None,max_length=300)
    evidence_reference: str | None = Field(default=None,max_length=1000)
    expires_at: str | None = None


class ApprovalRequest(BaseModel):
    operating_status: Status
    note: str | None = Field(default=None,max_length=2000)


class CorridorCreate(BaseModel):
    origin_country_code: str = Field(min_length=2,max_length=3)
    destination_country_code: str = Field(min_length=2,max_length=3)
    status: Status = 'BLOCKED'
    execution_mode: Literal['LIVE','SIMULATION'] = 'LIVE'
    allowed_incoterms: list[str] = Field(default_factory=list,max_length=20)
    supported_currencies: list[str] = Field(default_factory=list,max_length=20)
    carrier_coverage: bool = False
    broker_coverage: bool = False
    banking_coverage: bool = False
    insurance_coverage: bool = False
    tax_model_verified: bool = False


class CorridorApprovalRequest(BaseModel):
    status: Status
    note: str | None = Field(default=None,max_length=2000)


def now():
    return datetime.now(timezone.utc).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _evidence_expired(value: Any) -> bool:
    moment = _parse_time(value)
    return bool(value) and (moment is None or moment <= datetime.now(timezone.utc))


def employee_token():
    token=os.getenv('EMPLOYEE_TOKEN','').strip()
    if not token:
        raise HTTPException(503,'Employee country access is not configured')
    return token


def identity(role, authorization, employee_id):
    if role not in {'owner','employee'}:
        raise HTTPException(400,'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401,'Missing Authorization')
    token=authorization.removeprefix('Bearer ').strip()
    if role=='owner':
        if not verify_owner_token(token):
            raise HTTPException(403,'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if not secrets.compare_digest(token,employee_token()):
        raise HTTPException(403,'Invalid employee credential')
    return {'role':'employee','id':(employee_id or 'staff')[:160]}


async def audit(country_code, actor, event_type, summary, payload=None):
    row={'event_id':f'cae_{secrets.token_urlsafe(12)}','country_code':country_code,'actor_role':actor['role'],'actor_id':actor['id'],
         'event_type':event_type,'summary':summary,'payload':payload or {},'created_at':now()}
    await get_backend().insert('country_activation_audit',row)
    return row


async def controls_for(country_code: str):
    return await get_backend().select('country_activation_controls',params={'country_code':f'eq.{country_code}','order':'control_key.asc','limit':'100'}) or []


async def profile_for(country_code: str):
    rows=await get_backend().select('country_activation_profiles',params={'country_code':f'eq.{country_code}','limit':'1'}) or []
    return rows[0] if rows else None


async def corridor_for(corridor_id: str):
    rows=await get_backend().select('trade_corridor_activations',params={'corridor_id':f'eq.{corridor_id}','limit':'1'}) or []
    return rows[0] if rows else None


def governance_status(controls: list[dict], *, scenario_mode: str = 'LIVE') -> dict:
    by={str(c.get('control_key')):c for c in controls}
    failures={}
    states=[]
    live=scenario_mode.upper()=='LIVE'

    for key,_ in MANDATORY_CONTROLS:
        control=by.get(key)
        if not control:
            failures[key]='missing_control'; states.append('BLOCKED'); continue
        status=str(control.get('status') or 'BLOCKED').upper()
        if status=='BLOCKED':
            failures[key]='control_blocked'; states.append('BLOCKED'); continue
        if status not in {'READY','LIMITED','NOT_APPLICABLE'}:
            failures[key]='invalid_status'; states.append('BLOCKED'); continue
        if not str(control.get('evidence_summary') or '').strip():
            failures[key]='missing_evidence_summary'; states.append('BLOCKED'); continue
        if not str(control.get('evidence_source') or '').strip():
            failures[key]='missing_evidence_source'; states.append('BLOCKED'); continue
        if not control.get('reviewed_at'):
            failures[key]='not_reviewed'; states.append('BLOCKED'); continue
        if _evidence_expired(control.get('expires_at')):
            failures[key]='evidence_expired'; states.append('BLOCKED'); continue
        if status=='NOT_APPLICABLE':
            if live and not bool(control.get('owner_waiver')):
                failures[key]='not_applicable_without_owner_waiver'; states.append('BLOCKED'); continue
            if live and str(control.get('reviewed_by_role') or '').lower()!='owner':
                failures[key]='not_applicable_not_owner_reviewed'; states.append('BLOCKED'); continue
            states.append('READY'); continue
        states.append(status)

    if any(s=='BLOCKED' for s in states):
        derived='BLOCKED'
    elif any(s=='LIMITED' for s in states):
        derived='LIMITED'
    else:
        derived='READY'
    return {'derived_status':derived,'control_failures':failures,'mandatory_control_count':len(MANDATORY_CONTROLS)}


def derived_status(controls, scenario_mode: str = 'LIVE'):
    return governance_status(controls,scenario_mode=scenario_mode)['derived_status']


async def live_country_eligibility(country_code: str) -> dict:
    profile=await profile_for(country_code)
    if not profile:
        return {'eligible':False,'reason':'country_not_found'}
    if str(profile.get('scenario_mode') or 'LIVE').upper()!='LIVE':
        return {'eligible':False,'reason':'hypothetical_jurisdiction'}
    controls=await controls_for(country_code)
    governance=governance_status(controls,scenario_mode='LIVE')
    eligible=bool(
        profile.get('live_execution_allowed') is True
        and profile.get('owner_approved') is True
        and profile.get('approved_at')
        and str(profile.get('operating_status') or 'BLOCKED').upper()=='READY'
        and governance['derived_status']=='READY'
    )
    return {'eligible':eligible,'reason':None if eligible else 'country_not_fully_ready','profile':profile,'governance':governance}


def _corridor_coverage_ready(corridor: dict) -> bool:
    return all(bool(corridor.get(key)) for key in ('carrier_coverage','broker_coverage','banking_coverage','insurance_coverage','tax_model_verified'))


def _normalized_list(value: Any) -> list[str]:
    if isinstance(value,(list,tuple)):
        return [str(item).strip().upper() for item in value if str(item).strip()]
    return []


async def validate_ready_live_corridor(corridor: dict) -> dict:
    origin=str(corridor.get('origin_country_code') or '').upper()
    destination=str(corridor.get('destination_country_code') or '').upper()
    origin_state=await live_country_eligibility(origin)
    destination_state=await live_country_eligibility(destination)
    currencies=_normalized_list(corridor.get('supported_currencies'))
    incoterms=_normalized_list(corridor.get('allowed_incoterms'))
    currency_ok=not USD_ONLY_TRANSACTIONS or CANONICAL_TRANSACTION_CURRENCY in currencies
    failures=[]
    if not origin_state['eligible']: failures.append(f'origin:{origin_state["reason"]}')
    if not destination_state['eligible']: failures.append(f'destination:{destination_state["reason"]}')
    if not _corridor_coverage_ready(corridor): failures.append('coverage_incomplete')
    if not incoterms: failures.append('incoterms_missing')
    if not currency_ok: failures.append(f'{CANONICAL_TRANSACTION_CURRENCY}_settlement_not_supported')
    return {'ready':not failures,'failures':failures,'origin':origin_state,'destination':destination_state}


@app.get('/countries/health')
async def health():
    return {'status':'ok','service':'global-country-activation','version':'1.2.0','fail_closed':True,'mandatory_controls':len(MANDATORY_CONTROLS),
            'evidence_required_for_nonblocked_controls':True,'owner_waiver_required_for_live_not_applicable':True,
            'ready_live_corridor_requires_ready_owner_approved_countries':True,'hypothetical_live_execution_blocked':True}


@app.get('/countries')
async def list_countries(status: str|None=Query(default=None,max_length=20), x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    params={'order':'country_name.asc','limit':'300'}
    if status: params['operating_status']=f'eq.{status.upper()}'
    rows=await get_backend().select('country_activation_profiles',params=params) or []
    return {'countries':rows,'actor':actor}


@app.post('/countries')
async def create_country(payload: CountryCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    code=payload.country_code.upper(); ts=now()
    if code == FREE_CUBA_CODE:
        raise HTTPException(409,'XCU is reserved for the Free Cuba future-scenario sandbox endpoint')
    row={'country_code':code,'country_name':payload.country_name,'region':payload.region,'operating_status':'BLOCKED','scenario_mode':'LIVE','live_execution_allowed':True,'scenario_label':None,'default_currency':(payload.default_currency or '').upper() or None,
         'default_locale':payload.default_locale,'notes':payload.notes,'owner_approved':False,'created_at':ts,'updated_at':ts}
    await get_backend().insert('country_activation_profiles',row)
    control_rows=[]
    for key,label in MANDATORY_CONTROLS:
        control_rows.append({'control_id':f'cac_{secrets.token_urlsafe(12)}','country_code':code,'control_key':key,'control_label':label,'status':'BLOCKED','owner_waiver':False,'created_at':ts,'updated_at':ts})
    await get_backend().insert('country_activation_controls',control_rows)
    await audit(code,actor,'country_created',f'{payload.country_name} added in BLOCKED state')
    return {'country':row,'controls':control_rows}


@app.post('/countries/special/free-cuba')
async def activate_free_cuba_scenario(x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner': raise HTTPException(403,'Only owner may activate special jurisdiction scenarios')
    existing=await profile_for(FREE_CUBA_CODE)
    if existing:
        return {'country':existing,'scenario':'FREE_CUBA','sandbox_only':True,'live_execution_allowed':False}
    ts=now()
    row={'country_code':FREE_CUBA_CODE,'country_name':FREE_CUBA_NAME,'region':'Caribbean / Future Scenario','operating_status':'READY','scenario_mode':'HYPOTHETICAL','live_execution_allowed':False,
         'scenario_label':'A FREE CUBA · unrestricted future-state planning sandbox','default_currency':'USD','default_locale':'es-CU',
         'notes':'Hypothetical planning jurisdiction. Models a future Cuba without assumed trade restrictions. It is not the real CU jurisdiction and cannot authorize live shipments, payments, customs release, or legal/compliance bypass.',
         'owner_approved':True,'approved_by':actor['id'],'approved_at':ts,'created_at':ts,'updated_at':ts}
    await get_backend().insert('country_activation_profiles',row)
    controls=[]
    for key,label in MANDATORY_CONTROLS:
        controls.append({'control_id':f'cac_{secrets.token_urlsafe(12)}','country_code':FREE_CUBA_CODE,'control_key':key,'control_label':label,'status':'NOT_APPLICABLE','owner_waiver':False,
                         'evidence_summary':'Hypothetical unrestricted future-state assumption for scenario modeling only; not valid for live execution.',
                         'evidence_source':'SAHJONY scenario policy','reviewed_by_role':'owner','reviewed_by_id':actor['id'],'reviewed_at':ts,'created_at':ts,'updated_at':ts})
    await get_backend().insert('country_activation_controls',controls)
    await audit(FREE_CUBA_CODE,actor,'special_scenario_activated','Free Cuba future scenario activated as simulation-only READY',{'live_execution_allowed':False,'real_country_code':'CU'})
    return {'country':row,'controls':controls,'scenario':'FREE_CUBA','sandbox_only':True,'live_execution_allowed':False}


@app.get('/countries/{country_code}')
async def country_detail(country_code: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); code=country_code.upper()
    profile=await profile_for(code)
    if not profile: raise HTTPException(404,'Country not found')
    controls=await controls_for(code)
    governance=governance_status(controls,scenario_mode=str(profile.get('scenario_mode') or 'LIVE'))
    corridors=await get_backend().select('trade_corridor_activations',params={'or':f'(origin_country_code.eq.{code},destination_country_code.eq.{code})','limit':'100'}) or []
    live_state=await live_country_eligibility(code) if str(profile.get('scenario_mode') or 'LIVE').upper()=='LIVE' else {'eligible':False,'reason':'hypothetical_jurisdiction'}
    return {'country':profile,'controls':controls,'derived_status':governance['derived_status'],'governance':governance,'live_eligibility':live_state,'corridors':corridors,'actor':actor}


@app.patch('/countries/{country_code}/controls/{control_key}')
async def update_control(country_code: str, control_key: str, payload: ControlUpdate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); code=country_code.upper()
    profile=await profile_for(code)
    if not profile: raise HTTPException(404,'Country not found')
    if profile.get('scenario_mode')=='HYPOTHETICAL': raise HTTPException(409,'Hypothetical scenario controls are fixed scenario assumptions; create a LIVE jurisdiction for real-world verification')
    if control_key not in MANDATORY_CONTROL_KEYS: raise HTTPException(404,'Unknown country control')

    if payload.status in {'READY','LIMITED','NOT_APPLICABLE'}:
        if not (payload.evidence_summary or '').strip() or not (payload.evidence_source or '').strip():
            raise HTTPException(422,'READY/LIMITED/NOT_APPLICABLE controls require evidence_summary and evidence_source')
        if payload.expires_at and _evidence_expired(payload.expires_at):
            raise HTTPException(422,'Control evidence expiry must be a valid future timestamp')
    if payload.status=='NOT_APPLICABLE' and actor['role']!='owner':
        raise HTTPException(403,'Only owner may mark a LIVE jurisdiction control NOT_APPLICABLE')

    ts=now(); values={'status':payload.status,'evidence_summary':payload.evidence_summary,'evidence_source':payload.evidence_source,'evidence_reference':payload.evidence_reference,
                     'reviewed_by_role':actor['role'],'reviewed_by_id':actor['id'],'reviewed_at':ts,'expires_at':payload.expires_at,
                     'owner_waiver':payload.status=='NOT_APPLICABLE' and actor['role']=='owner','updated_at':ts}
    result=await get_backend().patch('country_activation_controls',values,params={'country_code':f'eq.{code}','control_key':f'eq.{control_key}'})
    controls=await controls_for(code); governance=governance_status(controls,scenario_mode='LIVE'); derived=governance['derived_status']
    await get_backend().patch('country_activation_profiles',{'operating_status':derived,'owner_approved':False,'approved_by':None,'approved_at':None,'updated_at':ts},params={'country_code':f'eq.{code}'})
    await audit(code,actor,'control_updated',f'{control_key} -> {payload.status}',{'derived_status':derived,'control_failures':governance['control_failures']})
    return {'country_code':code,'control_key':control_key,'status':payload.status,'derived_status':derived,'governance':governance,'persistence':result}


@app.post('/countries/{country_code}/approve')
async def approve_country(country_code: str, payload: ApprovalRequest, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner': raise HTTPException(403,'Only owner may approve country activation')
    code=country_code.upper(); profile=await profile_for(code)
    if not profile: raise HTTPException(404,'Country not found')
    scenario_mode=str(profile.get('scenario_mode') or 'LIVE').upper()
    if scenario_mode=='HYPOTHETICAL' and payload.operating_status!='READY': raise HTTPException(409,'Special hypothetical scenario is fixed as simulation READY')
    controls=await controls_for(code); governance=governance_status(controls,scenario_mode=scenario_mode); derived=governance['derived_status']
    if payload.operating_status=='READY' and derived!='READY':
        raise HTTPException(409,detail={'message':f'Country cannot be READY while governed control status is {derived}','control_failures':governance['control_failures']})
    if payload.operating_status=='LIMITED' and derived=='BLOCKED':
        raise HTTPException(409,detail={'message':'Country cannot be LIMITED while mandatory controls remain BLOCKED','control_failures':governance['control_failures']})
    ts=now(); values={'operating_status':payload.operating_status,'owner_approved':True,'approved_by':actor['id'],'approved_at':ts,'notes':payload.note,'updated_at':ts}
    await get_backend().patch('country_activation_profiles',values,params={'country_code':f'eq.{code}'})
    await audit(code,actor,'country_approved',f'Country approved as {payload.operating_status}',{'derived_status':derived,'note':payload.note})
    return {'country_code':code,'operating_status':payload.operating_status,'derived_status':derived,'owner_approved':True,'live_execution_allowed':scenario_mode=='LIVE' and bool(profile.get('live_execution_allowed',True)) and payload.operating_status=='READY'}


@app.post('/countries/corridors')
async def create_corridor(payload: CorridorCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    origin=payload.origin_country_code.upper(); destination=payload.destination_country_code.upper()
    if origin==destination: raise HTTPException(400,'Origin and destination must differ')
    origin_profile=await profile_for(origin); destination_profile=await profile_for(destination)
    if not origin_profile or not destination_profile: raise HTTPException(404,'Both corridor countries must exist')
    involves_hypothetical=origin_profile.get('scenario_mode')=='HYPOTHETICAL' or destination_profile.get('scenario_mode')=='HYPOTHETICAL'
    if involves_hypothetical and payload.execution_mode!='SIMULATION':
        raise HTTPException(409,'Corridors involving hypothetical jurisdictions must use SIMULATION execution mode')
    if payload.status=='READY' and actor['role']!='owner':
        raise HTTPException(403,'Only owner may create a READY corridor')

    normalized_currencies=[x.strip().upper() for x in payload.supported_currencies if x.strip()]
    normalized_incoterms=[x.strip().upper() for x in payload.allowed_incoterms if x.strip()]
    candidate={'origin_country_code':origin,'destination_country_code':destination,'status':payload.status,'execution_mode':payload.execution_mode,
               'allowed_incoterms':normalized_incoterms,'supported_currencies':normalized_currencies,'carrier_coverage':payload.carrier_coverage,
               'broker_coverage':payload.broker_coverage,'banking_coverage':payload.banking_coverage,'insurance_coverage':payload.insurance_coverage,
               'tax_model_verified':payload.tax_model_verified}
    validation={'ready':False,'failures':['not_live_ready_request']}
    if payload.status=='READY' and payload.execution_mode=='LIVE':
        validation=await validate_ready_live_corridor(candidate)
        if not validation['ready']:
            raise HTTPException(409,detail={'message':'READY live corridor failed governance validation','failures':validation['failures']})

    cid=f'corr_{origin}_{destination}_{secrets.token_urlsafe(6)}'; ts=now()
    row={**candidate,'corridor_id':cid,'owner_approved':actor['role']=='owner' and payload.status=='READY',
         'approval_note':'Simulation only' if involves_hypothetical else None,'created_at':ts,'updated_at':ts}
    await get_backend().insert('trade_corridor_activations',row)
    await audit(destination,actor,'corridor_created',f'{origin} -> {destination} corridor created as {payload.status} / {payload.execution_mode}',{'corridor_id':cid,'governance_validation':validation})
    live_allowed=bool(payload.status=='READY' and payload.execution_mode=='LIVE' and row['owner_approved'] and validation['ready'])
    return {'corridor':row,'governance_validation':validation,'live_execution_allowed':live_allowed}


@app.post('/countries/corridors/{corridor_id}/approve')
async def approve_corridor(corridor_id: str, payload: CorridorApprovalRequest, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner': raise HTTPException(403,'Only owner may approve a trade corridor')
    corridor=await corridor_for(corridor_id)
    if not corridor: raise HTTPException(404,'Corridor not found')

    validation={'ready':False,'failures':['not_live_ready_request']}
    if payload.status=='READY' and str(corridor.get('execution_mode') or 'LIVE').upper()=='LIVE':
        validation=await validate_ready_live_corridor(corridor)
        if not validation['ready']:
            raise HTTPException(409,detail={'message':'Corridor cannot be approved READY','failures':validation['failures']})

    ts=now(); values={'status':payload.status,'owner_approved':True,'approval_note':payload.note,'updated_at':ts}
    await get_backend().patch('trade_corridor_activations',values,params={'corridor_id':f'eq.{corridor_id}'})
    destination=str(corridor.get('destination_country_code') or 'UN').upper()
    await audit(destination,actor,'corridor_approved',f'{corridor_id} approved as {payload.status}',{'note':payload.note,'governance_validation':validation})
    live_allowed=bool(payload.status=='READY' and str(corridor.get('execution_mode') or 'LIVE').upper()=='LIVE' and validation['ready'])
    return {'corridor_id':corridor_id,'status':payload.status,'owner_approved':True,'governance_validation':validation,'live_execution_allowed':live_allowed}
