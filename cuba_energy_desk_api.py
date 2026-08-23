from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Cuba Energy Desk', version='1.0.0', docs_url=None, redoc_url=None)

EnergyType = Literal['SOLAR','BATTERY_STORAGE','GENERATOR','ENERGY_EFFICIENCY','GRID_EQUIPMENT','FUEL','CRUDE_OIL','LPG','LNG','LOGISTICS','OTHER']
OpportunityStatus = Literal['HOLD','RESEARCH','COMPLIANCE_REVIEW','COMMERCIAL_REVIEW','OWNER_REVIEW','APPROVED_FOR_LAWFUL_WORKFLOW','CLOSED','REJECTED']

REQUIRED_GATES = [
    'independent_private_sector_eligibility',
    'restricted_party_screening',
    'product_export_classification',
    'legal_authorization_basis',
    'end_user_end_use_review',
    'banking_payment_path',
    'shipping_logistics_acceptance',
    'documents_recordkeeping',
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


class OpportunityIn(BaseModel):
    opportunity_type: EnergyType
    title: str = Field(min_length=3, max_length=240)
    cuban_counterparty_name: str = Field(min_length=2, max_length=240)
    private_business_id: str | None = Field(default=None, max_length=180)
    municipality: str | None = Field(default=None, max_length=180)
    province: str | None = Field(default=None, max_length=180)
    end_user: str | None = Field(default=None, max_length=300)
    end_use: str = Field(min_length=3, max_length=1200)
    product_or_service: str = Field(min_length=3, max_length=1200)
    estimated_value: float | None = Field(default=None, ge=0)
    currency: str = Field(default='USD', min_length=3, max_length=12)
    supplier_country: str | None = Field(default=None, max_length=100)
    state_entity_involved: bool = False
    source_reference: str | None = Field(default=None, max_length=1500)
    notes: str | None = Field(default=None, max_length=5000)


class GateIn(BaseModel):
    gate: str
    status: Literal['PASS','FAIL','PENDING','NOT_APPLICABLE']
    evidence_reference: str | None = Field(default=None, max_length=1500)
    evidence_summary: str | None = Field(default=None, max_length=3000)


class LinkCaseIn(BaseModel):
    cuba_trade_case_id: str = Field(min_length=3, max_length=180)
    energy_deal_id: str | None = Field(default=None, max_length=180)


async def get_opportunity(opportunity_id: str) -> dict:
    rows = await get_backend().select('cuba_energy_opportunities', params={'opportunity_id':f'eq.{opportunity_id}','limit':'1'}) or []
    if not rows:
        raise HTTPException(404, 'Cuba Energy opportunity not found')
    return rows[0]


async def gate_state(opportunity_id: str) -> dict[str, str]:
    rows = await get_backend().select('cuba_energy_gates', params={'opportunity_id':f'eq.{opportunity_id}','order':'updated_at.desc','limit':'500'}) or []
    out = {}
    for row in rows:
        key = str(row.get('gate') or '')
        if key and key not in out:
            out[key] = str(row.get('status') or 'PENDING')
    return out


@app.get('/cuba-energy/health')
async def health():
    p = persistent_backend_status()
    return {
        'status':'ok' if p['configured'] else 'configuration_required',
        'service':'sahjony-cuba-energy-desk',
        'country':'CU',
        'energy_vertical':True,
        'private_sector_first':True,
        'required_gates':REQUIRED_GATES,
        'default_status':'HOLD',
        'automatic_compliance_clearance':False,
        'automatic_contract_execution':False,
        'automatic_payment_authority':False,
        'automatic_cargo_release':False,
        'fail_closed':True,
        'persistence_provider':p['provider'],
    }


@app.post('/cuba-energy/opportunities')
async def create_opportunity(payload: OpportunityIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    ts = now(); oid = f'cue_{secrets.token_urlsafe(12)}'
    risk_flags = []
    if payload.state_entity_involved:
        risk_flags.append('STATE_ENTITY_REVIEW_REQUIRED')
    if payload.opportunity_type in {'FUEL','CRUDE_OIL','LPG','LNG'}:
        risk_flags.append('ENERGY_COMMODITY_ENHANCED_REVIEW')
    row = {
        'opportunity_id':oid, **payload.model_dump(), 'country_code':'CU', 'status':'HOLD',
        'release_allowed':False, 'owner_approved':False, 'risk_flags':risk_flags,
        'legal_basis_status':'PENDING', 'screening_status':'PENDING',
        'cuba_trade_case_id':None, 'energy_deal_id':None,
        'created_at':ts, 'updated_at':ts,
    }
    await get_backend().insert('cuba_energy_opportunities', row)
    for gate in REQUIRED_GATES:
        await get_backend().insert('cuba_energy_gates', {
            'gate_id':f'cug_{secrets.token_urlsafe(10)}','opportunity_id':oid,'gate':gate,
            'status':'PENDING','evidence_reference':None,'evidence_summary':None,
            'reviewed_by':None,'reviewed_at':None,'created_at':ts,'updated_at':ts,
        })
    return {'opportunity':row,'required_gates':REQUIRED_GATES,'note':'Cuba Energy opportunities remain HOLD until lawful-basis and compliance gates are completed.'}


@app.get('/cuba-energy/opportunities')
async def list_opportunities(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('cuba_energy_opportunities', params={'order':'updated_at.desc','limit':'1000'}) or []
    return {'opportunities':rows}


@app.get('/cuba-energy/opportunities/{opportunity_id}')
async def opportunity_detail(opportunity_id: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    row = await get_opportunity(opportunity_id)
    gates = await get_backend().select('cuba_energy_gates', params={'opportunity_id':f'eq.{opportunity_id}','order':'updated_at.desc','limit':'500'}) or []
    return {'opportunity':row,'gates':gates,'gate_state':await gate_state(opportunity_id)}


@app.post('/cuba-energy/opportunities/{opportunity_id}/gates')
async def review_gate(opportunity_id: str, payload: GateIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    if payload.gate not in REQUIRED_GATES:
        raise HTTPException(400, 'Unknown Cuba Energy gate')
    await get_opportunity(opportunity_id)
    ts = now()
    await get_backend().insert('cuba_energy_gates', {
        'gate_id':f'cug_{secrets.token_urlsafe(10)}','opportunity_id':opportunity_id,
        **payload.model_dump(),'reviewed_by':'owner','reviewed_at':ts,'created_at':ts,'updated_at':ts,
    })
    patch = {'updated_at':ts}
    if payload.gate == 'restricted_party_screening':
        patch['screening_status'] = 'PASS' if payload.status == 'PASS' else ('HOLD' if payload.status == 'FAIL' else payload.status)
    if payload.gate == 'legal_authorization_basis':
        patch['legal_basis_status'] = payload.status
    if payload.status == 'FAIL':
        patch.update({'status':'HOLD','release_allowed':False,'owner_approved':False})
    await get_backend().patch('cuba_energy_opportunities', patch, params={'opportunity_id':f'eq.{opportunity_id}'})
    return {'opportunity_id':opportunity_id,'gate':payload.gate,'status':payload.status}


@app.post('/cuba-energy/opportunities/{opportunity_id}/link-case')
async def link_case(opportunity_id: str, payload: LinkCaseIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    await get_opportunity(opportunity_id)
    cases = await get_backend().select('cuba_trade_cases', params={'trade_case_id':f'eq.{payload.cuba_trade_case_id}','limit':'1'}) or []
    if not cases:
        raise HTTPException(404, 'Linked Cuba trade case not found')
    if payload.energy_deal_id:
        deals = await get_backend().select('energy_deals', params={'deal_id':f'eq.{payload.energy_deal_id}','limit':'1'}) or []
        if not deals:
            raise HTTPException(404, 'Linked Energy deal not found')
    ts = now()
    await get_backend().patch('cuba_energy_opportunities', {
        'cuba_trade_case_id':payload.cuba_trade_case_id,'energy_deal_id':payload.energy_deal_id,
        'status':'COMPLIANCE_REVIEW','release_allowed':False,'updated_at':ts,
    }, params={'opportunity_id':f'eq.{opportunity_id}'})
    return {'opportunity_id':opportunity_id,'linked':True,'cuba_trade_case_id':payload.cuba_trade_case_id,'energy_deal_id':payload.energy_deal_id}


@app.post('/cuba-energy/opportunities/{opportunity_id}/approve-lawful-workflow')
async def approve_lawful_workflow(opportunity_id: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    row = await get_opportunity(opportunity_id)
    states = await gate_state(opportunity_id)
    incomplete = [g for g in REQUIRED_GATES if states.get(g) not in {'PASS','NOT_APPLICABLE'}]
    if incomplete:
        raise HTTPException(409, {'message':'Cuba Energy gates incomplete','gates':incomplete})
    if not row.get('cuba_trade_case_id'):
        raise HTTPException(409, 'A governed Cuba trade case must be linked before approval')
    cases = await get_backend().select('cuba_trade_cases', params={'trade_case_id':f"eq.{row.get('cuba_trade_case_id')}",'limit':'1'}) or []
    if not cases or cases[0].get('release_allowed') is not True or cases[0].get('status') != 'AUTHORIZED':
        raise HTTPException(409, 'Linked Cuba trade case is not AUTHORIZED for release')
    ts = now()
    await get_backend().patch('cuba_energy_opportunities', {
        'status':'APPROVED_FOR_LAWFUL_WORKFLOW','release_allowed':True,'owner_approved':True,
        'owner_approved_at':ts,'updated_at':ts,
    }, params={'opportunity_id':f'eq.{opportunity_id}'})
    return {'opportunity_id':opportunity_id,'status':'APPROVED_FOR_LAWFUL_WORKFLOW','release_allowed':True}


@app.get('/cuba-energy/summary')
async def summary(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('cuba_energy_opportunities', params={'limit':'2000'}) or []
    active = [r for r in rows if r.get('status') not in {'CLOSED','REJECTED'}]
    return {
        'opportunities':len(rows),
        'active':len(active),
        'on_hold':sum(1 for r in active if r.get('status')=='HOLD'),
        'compliance_review':sum(1 for r in active if r.get('status')=='COMPLIANCE_REVIEW'),
        'approved_for_lawful_workflow':sum(1 for r in active if r.get('status')=='APPROVED_FOR_LAWFUL_WORKFLOW'),
        'estimated_pipeline_value':round(sum(float(r.get('estimated_value') or 0) for r in active),2),
        'state_entity_review_required':sum(1 for r in active if r.get('state_entity_involved') is True),
        'energy_commodity_enhanced_review':sum(1 for r in active if 'ENERGY_COMMODITY_ENHANCED_REVIEW' in (r.get('risk_flags') or [])),
        'note':'Pipeline value is not revenue. Cuba Energy work remains subject to U.S. sanctions/export controls, transaction-specific legal basis, and Owner authorization.',
    }
