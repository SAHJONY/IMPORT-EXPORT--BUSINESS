from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Energy Crude Oil OS', version='1.0.0', docs_url=None, redoc_url=None)

Role = Literal['owner','employee']
DealSide = Literal['BUY','SELL','MATCH','BROKER']
CounterpartyRole = Literal['BUYER','SELLER','REFINERY','PRODUCER','TRADER','MANDATE','BROKER','TERMINAL','OTHER']
DealStage = Literal['LEAD','ENTITY_REVIEW','MANDATE_REVIEW','PRODUCT_REVIEW','COMMERCIAL_FIT','COMPLIANCE_REVIEW','BANKABILITY_REVIEW','LOGISTICS_REVIEW','OWNER_REVIEW','READY_FOR_TRANSACTION','HOLD','CLOSED']

CRUDE_GRADES = [
    'WTI','WTI MIDLAND','BRENT-LINKED','MARS','LLS','WCS','MAYA','BONNY LIGHT','QUA IBOE',
    'FORCADOS','ESPO','URALS','ARAB LIGHT','ARAB MEDIUM','DUBAI','OMAN','MURBAN','BASRAH LIGHT',
    'BASRAH MEDIUM','DAS','AZERI LIGHT','SAHARAN BLEND','DJENO','CABINDA','DALIA','OTHER'
]

HIGH_RISK_FLAGS = {
    'UPFRONT_FEE': 28,
    'UNVERIFIABLE_ALLOCATION': 24,
    'NO_CORPORATE_DOMAIN': 8,
    'IMPOSSIBLE_DISCOUNT': 18,
    'UNVERIFIED_MANDATE_CHAIN': 18,
    'BANK_INSTRUMENT_BEFORE_DD': 18,
    'PAYMENT_TO_THIRD_PARTY': 30,
    'DOCUMENT_METADATA_CONFLICT': 18,
    'FREE_EMAIL_ONLY': 6,
    'NO_VERIFIABLE_TERMINAL_OR_REFINERY': 16,
    'RUSH_OR_SECRECY_PRESSURE': 12,
    'SANCTIONS_OR_RESTRICTED_PARTY_CONCERN': 40,
}

STAGE_REQUIREMENTS = {
    'ENTITY_REVIEW': ['legal_entity_evidence','beneficial_ownership_evidence','corporate_contact_evidence'],
    'MANDATE_REVIEW': ['mandate_or_authority_evidence'],
    'PRODUCT_REVIEW': ['product_specification','quantity','delivery_basis'],
    'COMMERCIAL_FIT': ['pricing_basis','commercial_terms'],
    'COMPLIANCE_REVIEW': ['party_screening','origin_destination_review','end_use_review'],
    'BANKABILITY_REVIEW': ['bankability_evidence','payment_instrument_review'],
    'LOGISTICS_REVIEW': ['load_discharge_plan','inspection_plan','terminal_or_vessel_plan'],
    'OWNER_REVIEW': ['counterparty_dd_pass','commercial_dd_pass','compliance_dd_pass','bank_dd_pass','logistics_dd_pass'],
    'READY_FOR_TRANSACTION': ['owner_approval'],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def employee_token() -> str:
    token = os.getenv('EMPLOYEE_TOKEN', '').strip()
    if not token:
        raise HTTPException(503, 'Employee Energy access is not configured')
    return token


def identity(role: str | None, authorization: str | None, employee_id: str | None) -> dict:
    if role not in {'owner','employee'}:
        raise HTTPException(400, 'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    token = authorization.removeprefix('Bearer ').strip()
    if role == 'owner':
        if not verify_owner_token(token):
            raise HTTPException(403, 'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if not secrets.compare_digest(token, employee_token()):
        raise HTTPException(403, 'Invalid employee credential')
    return {'role':'employee','id':(employee_id or 'staff')[:160]}


class CounterpartyIn(BaseModel):
    legal_name: str = Field(min_length=2,max_length=240)
    country: str = Field(min_length=2,max_length=100)
    role: CounterpartyRole
    website: str | None = Field(default=None,max_length=1200)
    contact_name: str | None = Field(default=None,max_length=160)
    email: str | None = Field(default=None,max_length=320)
    phone: str | None = Field(default=None,max_length=100)
    registration_reference: str | None = Field(default=None,max_length=240)
    beneficial_owner_summary: str | None = Field(default=None,max_length=2000)
    evidence_urls: list[str] = Field(default_factory=list,max_length=20)
    notes: str | None = Field(default=None,max_length=4000)


class DealIn(BaseModel):
    side: DealSide = 'BROKER'
    buyer_counterparty_id: str | None = Field(default=None,max_length=180)
    seller_counterparty_id: str | None = Field(default=None,max_length=180)
    crude_grade: str = Field(min_length=2,max_length=120)
    api_gravity: float | None = Field(default=None,ge=5,le=60)
    sulfur_pct: float | None = Field(default=None,ge=0,le=10)
    quantity_bbl: float = Field(gt=0,le=1_000_000_000)
    term: Literal['SPOT','TERM','TRIAL_PLUS_TERM']='SPOT'
    cargo_frequency: str | None = Field(default=None,max_length=240)
    origin_country: str | None = Field(default=None,max_length=100)
    destination_country: str | None = Field(default=None,max_length=100)
    load_port: str | None = Field(default=None,max_length=240)
    discharge_port: str | None = Field(default=None,max_length=240)
    incoterm: str | None = Field(default=None,max_length=30)
    pricing_basis: str | None = Field(default=None,max_length=500)
    differential_per_bbl: float | None = None
    seller_price_per_bbl: float | None = Field(default=None,ge=0)
    buyer_price_per_bbl: float | None = Field(default=None,ge=0)
    sahjony_fee_per_bbl: float | None = Field(default=None,ge=0)
    sahjony_fee_flat: float | None = Field(default=None,ge=0)
    currency: str = Field(default='USD',min_length=3,max_length=12)
    payment_instrument: str | None = Field(default=None,max_length=300)
    inspection_standard: str | None = Field(default='SGS or mutually approved equivalent',max_length=300)
    loading_window: str | None = Field(default=None,max_length=240)
    source_reference: str | None = Field(default=None,max_length=1200)
    notes: str | None = Field(default=None,max_length=5000)


class EvidenceIn(BaseModel):
    evidence_type: str = Field(min_length=2,max_length=120)
    reference: str = Field(min_length=2,max_length=1500)
    source: str | None = Field(default=None,max_length=500)
    verified: bool = False
    notes: str | None = Field(default=None,max_length=2500)


class RiskIn(BaseModel):
    flags: list[str] = Field(default_factory=list,max_length=30)
    notes: str | None = Field(default=None,max_length=3000)


class StageIn(BaseModel):
    stage: DealStage
    note: str | None = Field(default=None,max_length=3000)


class AgentLaunchIn(BaseModel):
    objective: Literal['ORIGINATE_BUYERS','ORIGINATE_SELLERS','MATCH_DEAL','DUE_DILIGENCE','COMMERCIAL_OPTIMIZATION','FULL_ORCHESTRATION']='FULL_ORCHESTRATION'
    target_countries: list[str] = Field(default_factory=list,max_length=40)
    target_grades: list[str] = Field(default_factory=list,max_length=30)
    notes: str | None = Field(default=None,max_length=4000)


async def audit(actor: dict, event: str, summary: str, deal_id: str | None = None, counterparty_id: str | None = None, payload: dict | None = None):
    await get_backend().insert('energy_audit_events', {
        'event_id': f'ena_{secrets.token_urlsafe(12)}', 'deal_id': deal_id, 'counterparty_id': counterparty_id,
        'actor_role': actor['role'], 'actor_id': actor['id'], 'event_type': event, 'summary': summary,
        'payload': payload or {}, 'created_at': now(),
    })


def economics(deal: dict) -> dict:
    qty = float(deal.get('quantity_bbl') or 0)
    seller = deal.get('seller_price_per_bbl')
    buyer = deal.get('buyer_price_per_bbl')
    fee_bbl = float(deal.get('sahjony_fee_per_bbl') or 0)
    fee_flat = float(deal.get('sahjony_fee_flat') or 0)
    spread = None
    gross_spread = None
    if seller is not None and buyer is not None:
        spread = float(buyer) - float(seller)
        gross_spread = spread * qty
    projected_fee = fee_flat + fee_bbl * qty
    return {
        'quantity_bbl': qty,
        'seller_notional': float(seller) * qty if seller is not None else None,
        'buyer_notional': float(buyer) * qty if buyer is not None else None,
        'gross_spread_per_bbl': spread,
        'gross_spread_value': gross_spread,
        'projected_sahjony_fee': projected_fee,
        'currency': deal.get('currency') or 'USD',
        'profit_guaranteed': False,
        'note': 'Projected economics are planning values only and require verified counterparties, executable terms, compliance, bankability, logistics, closing and reconciliation.',
    }


def risk_score(flags: list[str]) -> tuple[int,list[str]]:
    normalized = [str(x).strip().upper() for x in flags if str(x).strip()]
    score = min(100, sum(HIGH_RISK_FLAGS.get(x, 5) for x in normalized))
    return score, normalized


async def deal_evidence(deal_id: str) -> list[dict]:
    return await get_backend().select('energy_deal_evidence', params={'deal_id': f'eq.{deal_id}', 'limit':'500'}) or []


def verified_types(rows: list[dict]) -> set[str]:
    return {str(r.get('evidence_type') or '') for r in rows if r.get('verified') is True}


@app.get('/energy/health')
async def health():
    p = persistent_backend_status()
    return {
        'status': 'ok' if p['configured'] else 'configuration_required',
        'service': 'sahjony-energy-crude-oil-os',
        'vertical': 'CRUDE_OIL',
        'autonomous_origination': True,
        'autonomous_research': True,
        'autonomous_due_diligence_preparation': True,
        'autonomous_economic_analysis': True,
        'automatic_counterparty_approval': False,
        'automatic_payment_authority': False,
        'automatic_compliance_release': False,
        'automatic_contract_execution': False,
        'automatic_transaction_release': False,
        'fraud_risk_engine': True,
        'persistent_deal_rooms': p['configured'],
        'persistence_provider': p['provider'],
        'fail_closed': True,
    }


@app.get('/energy/grades')
async def grades():
    return {'grades': CRUDE_GRADES}


@app.post('/energy/counterparties')
async def create_counterparty(p: CounterpartyIn, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    cid = f'enc_{secrets.token_urlsafe(12)}'; ts = now()
    row = {'counterparty_id':cid, **p.model_dump(), 'status':'UNVERIFIED', 'kyb_status':'PENDING', 'screening_status':'PENDING', 'bankability_status':'PENDING', 'created_by':actor['id'], 'created_at':ts, 'updated_at':ts}
    await get_backend().insert('energy_counterparties', row)
    await audit(actor, 'counterparty_created', f'{p.role} counterparty entered Energy CRM', counterparty_id=cid)
    return {'counterparty': row}


@app.get('/energy/counterparties')
async def list_counterparties(x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role, authorization, x_employee_id)
    rows = await get_backend().select('energy_counterparties', params={'order':'updated_at.desc','limit':'1000'}) or []
    return {'counterparties': rows}


@app.post('/energy/deals')
async def create_deal(p: DealIn, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    did = f'end_{secrets.token_urlsafe(12)}'; ts = now()
    row = {'deal_id':did, **p.model_dump(), 'stage':'LEAD', 'risk_score':0, 'risk_flags':[], 'release_allowed':False, 'owner_approved':False, 'created_by':actor['id'], 'created_at':ts, 'updated_at':ts}
    row['economics'] = economics(row)
    await get_backend().insert('energy_deals', row)
    await audit(actor, 'deal_created', f'Crude oil opportunity created: {p.crude_grade} / {p.quantity_bbl:,.0f} bbl', deal_id=did, payload={'side':p.side})
    return {'deal': row}


@app.get('/energy/deals')
async def list_deals(x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role, authorization, x_employee_id)
    rows = await get_backend().select('energy_deals', params={'order':'updated_at.desc','limit':'1000'}) or []
    return {'deals': [{**r, 'economics': economics(r)} for r in rows]}


@app.get('/energy/deals/{deal_id}')
async def deal_detail(deal_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role, authorization, x_employee_id)
    rows = await get_backend().select('energy_deals', params={'deal_id':f'eq.{deal_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404, 'Energy deal not found')
    evidence = await deal_evidence(deal_id)
    jobs = await get_backend().select('energy_agent_jobs', params={'deal_id':f'eq.{deal_id}','order':'updated_at.desc','limit':'100'}) or []
    return {'deal':{**rows[0], 'economics':economics(rows[0])}, 'evidence':evidence, 'agent_jobs':jobs}


@app.post('/energy/deals/{deal_id}/evidence')
async def add_evidence(deal_id: str, p: EvidenceIn, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    if p.verified and actor['role'] != 'owner':
        raise HTTPException(403, 'Only owner may mark Energy evidence verified')
    eid = f'ene_{secrets.token_urlsafe(12)}'; ts=now()
    row = {'evidence_id':eid,'deal_id':deal_id,**p.model_dump(),'verified_by':actor['id'] if p.verified else None,'verified_at':ts if p.verified else None,'created_at':ts}
    await get_backend().insert('energy_deal_evidence', row)
    await audit(actor, 'evidence_added', f'Energy evidence added: {p.evidence_type}', deal_id=deal_id, payload={'verified':p.verified})
    return {'evidence':row}


@app.post('/energy/deals/{deal_id}/risk')
async def assess_risk(deal_id: str, p: RiskIn, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    score, flags = risk_score(p.flags)
    hold = score >= 35 or 'SANCTIONS_OR_RESTRICTED_PARTY_CONCERN' in flags or 'PAYMENT_TO_THIRD_PARTY' in flags
    values = {'risk_score':score,'risk_flags':flags,'risk_notes':p.notes,'updated_at':now()}
    if hold: values.update({'stage':'HOLD','release_allowed':False,'owner_approved':False})
    await get_backend().patch('energy_deals', values, params={'deal_id':f'eq.{deal_id}'})
    await audit(actor, 'risk_assessed', f'Fraud/counterparty risk score {score}/100', deal_id=deal_id, payload={'flags':flags,'hold':hold})
    return {'deal_id':deal_id,'risk_score':score,'risk_flags':flags,'hold':hold}


@app.post('/energy/deals/{deal_id}/stage')
async def set_stage(deal_id: str, p: StageIn, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    rows = await get_backend().select('energy_deals', params={'deal_id':f'eq.{deal_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404, 'Energy deal not found')
    deal = rows[0]
    if int(deal.get('risk_score') or 0) >= 35 and p.stage not in {'HOLD','CLOSED'}:
        raise HTTPException(409, 'Energy deal is risk-held; resolve and re-evaluate risk before advancement')
    required = STAGE_REQUIREMENTS.get(p.stage, [])
    evidence = await deal_evidence(deal_id)
    have = verified_types(evidence)
    missing = [x for x in required if x not in have]
    if missing:
        raise HTTPException(409, 'Stage blocked; verified evidence missing: ' + ', '.join(missing))
    if p.stage in {'OWNER_REVIEW','READY_FOR_TRANSACTION'} and actor['role'] != 'owner':
        raise HTTPException(403, 'Owner review and transaction readiness are owner-only')
    values = {'stage':p.stage,'stage_note':p.note,'updated_at':now()}
    if p.stage == 'READY_FOR_TRANSACTION': values.update({'owner_approved':True,'release_allowed':True,'owner_approved_at':now()})
    else: values.update({'release_allowed':False})
    await get_backend().patch('energy_deals', values, params={'deal_id':f'eq.{deal_id}'})
    await audit(actor, 'stage_changed', f'Energy deal stage -> {p.stage}', deal_id=deal_id, payload={'note':p.note})
    return {'deal_id':deal_id,'stage':p.stage,'release_allowed':p.stage=='READY_FOR_TRANSACTION'}


@app.post('/energy/deals/{deal_id}/agent-launch')
async def launch_agent(deal_id: str, p: AgentLaunchIn, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    deals = await get_backend().select('energy_deals', params={'deal_id':f'eq.{deal_id}','limit':'1'}) or []
    if not deals: raise HTTPException(404, 'Energy deal not found')
    job_id = f'enj_{secrets.token_urlsafe(12)}'; ts = now()
    tasks = [
        {'task':'VERIFY_ENTITY','authority':'RESEARCH_ONLY'},
        {'task':'VERIFY_MANDATE_CHAIN','authority':'RESEARCH_ONLY'},
        {'task':'VERIFY_PRODUCT_AND_GRADE','authority':'RESEARCH_ONLY'},
        {'task':'CHECK_PRICE_PLAUSIBILITY','authority':'ANALYSIS_ONLY'},
        {'task':'SCREEN_FRAUD_PATTERNS','authority':'ANALYSIS_ONLY'},
        {'task':'PREPARE_COMPLIANCE_PACKET','authority':'PREPARATION_ONLY'},
        {'task':'PREPARE_BANKABILITY_PACKET','authority':'PREPARATION_ONLY'},
        {'task':'PREPARE_LOGISTICS_PACKET','authority':'PREPARATION_ONLY'},
        {'task':'CALCULATE_DEAL_ECONOMICS','authority':'ANALYSIS_ONLY'},
        {'task':'PREPARE_NEGOTIATION_BRIEF','authority':'ADVISORY_ONLY'},
    ]
    row = {
        'job_id':job_id,'deal_id':deal_id,'objective':p.objective,'target_countries':p.target_countries,'target_grades':p.target_grades,
        'notes':p.notes,'status':'QUEUED','phase':'ENERGY_ORCHESTRATION','tasks':tasks,
        'cannot_execute':['supplier_commitment','buyer_commitment','contract_signature','bank_instruction','payment','compliance_release','shipment_release','title_transfer'],
        'created_by':actor['id'],'created_at':ts,'updated_at':ts,
    }
    await get_backend().insert('energy_agent_jobs', row)
    await audit(actor, 'energy_agent_launched', f'Crude Oil AI Agent launched: {p.objective}', deal_id=deal_id, payload={'job_id':job_id})
    return {'job':row}


@app.get('/energy/agent-jobs')
async def agent_jobs(x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role, authorization, x_employee_id)
    rows = await get_backend().select('energy_agent_jobs', params={'order':'updated_at.desc','limit':'500'}) or []
    return {'jobs':rows}


@app.get('/energy/command-summary')
async def command_summary(x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role, authorization, x_employee_id)
    backend = get_backend()
    deals = await backend.select('energy_deals', params={'limit':'5000'}) or []
    cps = await backend.select('energy_counterparties', params={'limit':'5000'}) or []
    jobs = await backend.select('energy_agent_jobs', params={'limit':'5000'}) or []
    active = [d for d in deals if d.get('stage') not in {'CLOSED'}]
    ready = [d for d in deals if d.get('stage') == 'READY_FOR_TRANSACTION']
    holds = [d for d in deals if d.get('stage') == 'HOLD' or int(d.get('risk_score') or 0) >= 35]
    projected_fee = sum(economics(d)['projected_sahjony_fee'] for d in active)
    volume = sum(float(d.get('quantity_bbl') or 0) for d in active)
    return {
        'status':'ok','active_deals':len(active),'ready_for_transaction':len(ready),'holds':len(holds),
        'counterparties':len(cps),'agent_jobs':len(jobs),'active_barrels':volume,
        'projected_sahjony_fees':round(projected_fee,2),'profit_guaranteed':False,
        'authority':'OWNER_GOVERNED','release_policy':'FAIL_CLOSED',
    }
