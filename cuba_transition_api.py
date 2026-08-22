from __future__ import annotations

import secrets
from datetime import datetime, timezone, date
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Cuba Transition Governance', version='1.0.0', docs_url=None, redoc_url=None)

GateStatus = Literal['READY','LIMITED','BLOCKED','NOT_APPLICABLE']
EvidenceStatus = Literal['PENDING','VERIFIED','REJECTED','SUPERSEDED']
ChangeType = Literal['OFAC_CACR','EXECUTIVE_ORDER','STATUTE','BIS_PART_746','STATE_RESTRICTED_LIST','BANKING','CUSTOMS','OTHER']

REQUIRED_GATES = [
    'ofac_cacr_status','statutory_embargo_status','executive_sanctions_status','bis_part_746_status',
    'restricted_party_framework','banking_settlement_normalized','customs_trade_normalized',
    'carrier_insurance_normalized','country_controls_reverified','corridor_controls_reverified',
    'legal_effective_dates_passed','production_safety_test'
]

class EvidenceIn(BaseModel):
    authority: str = Field(min_length=2,max_length=160)
    legal_instrument: str = Field(min_length=2,max_length=300)
    reference_url: str | None = Field(default=None,max_length=1000)
    effective_date: str | None = None
    change_type: ChangeType
    removes_restriction: bool = False
    scope_summary: str = Field(min_length=3,max_length=4000)

class EvidenceReview(BaseModel):
    status: EvidenceStatus

class GateUpdate(BaseModel):
    status: GateStatus
    evidence_summary: str | None = Field(default=None,max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list,max_length=100)

class PromoteRequest(BaseModel):
    note: str = Field(min_length=3,max_length=4000)


def now(): return datetime.now(timezone.utc).isoformat()

def owner(authorization: str | None):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
    token=authorization.removeprefix('Bearer ').strip()
    if not verify_owner_token(token): raise HTTPException(403,'Invalid owner credential')
    return {'id':'owner'}

async def gates():
    return await get_backend().select('cuba_transition_gates',params={'order':'gate_key.asc','limit':'100'}) or []

async def state():
    rows=await get_backend().select('cuba_transition_state',params={'singleton_key':'eq.CU','limit':'1'}) or []
    return rows[0] if rows else {'country_code':'CU','current_operating_status':'LIMITED','transition_candidate':False,'owner_approved':False}

def evaluate(gate_rows):
    by={r.get('gate_key'):r for r in gate_rows}
    blockers=[]
    for key in REQUIRED_GATES:
        row=by.get(key)
        if not row or row.get('status')!='READY': blockers.append(key)
    return {'candidate_ready':not blockers,'blockers':blockers,'required_gate_count':len(REQUIRED_GATES),'ready_gate_count':len(REQUIRED_GATES)-len(blockers)}

@app.get('/cuba-transition/health')
async def health():
    return {'status':'ok','country_code':'CU','fail_closed':True,'promotion_requires_all_gates':True,'required_gates':len(REQUIRED_GATES)}

@app.get('/cuba-transition/status')
async def transition_status(authorization: str | None=Header(None,alias='Authorization')):
    owner(authorization)
    g=await gates(); s=await state(); ev=evaluate(g)
    evidence=await get_backend().select('cuba_transition_evidence',params={'order':'created_at.desc','limit':'200'}) or []
    return {'state':s,'evaluation':ev,'gates':g,'evidence':evidence}

@app.post('/cuba-transition/evidence')
async def add_evidence(payload: EvidenceIn, authorization: str | None=Header(None,alias='Authorization')):
    actor=owner(authorization); ts=now(); eid=f'cuev_{secrets.token_urlsafe(12)}'
    row={'evidence_id':eid,'authority':payload.authority,'legal_instrument':payload.legal_instrument,'reference_url':payload.reference_url,
         'effective_date':payload.effective_date,'evidence_status':'PENDING','change_type':payload.change_type,'removes_restriction':payload.removes_restriction,
         'scope_summary':payload.scope_summary,'created_at':ts,'updated_at':ts}
    await get_backend().insert('cuba_transition_evidence',row)
    await get_backend().insert('cuba_transition_events',{'event_id':f'cute_{secrets.token_urlsafe(12)}','event_type':'evidence_added','actor_id':actor['id'],'summary':f'Evidence added: {payload.legal_instrument}','payload':{'evidence_id':eid},'created_at':ts})
    return {'evidence':row}

@app.patch('/cuba-transition/evidence/{evidence_id}')
async def review_evidence(evidence_id: str, payload: EvidenceReview, authorization: str | None=Header(None,alias='Authorization')):
    actor=owner(authorization); ts=now()
    rows=await get_backend().select('cuba_transition_evidence',params={'evidence_id':f'eq.{evidence_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Evidence not found')
    values={'evidence_status':payload.status,'verified_by':actor['id'] if payload.status=='VERIFIED' else None,'verified_at':ts if payload.status=='VERIFIED' else None,'updated_at':ts}
    await get_backend().patch('cuba_transition_evidence',values,params={'evidence_id':f'eq.{evidence_id}'})
    return {'evidence_id':evidence_id,'status':payload.status}

@app.patch('/cuba-transition/gates/{gate_key}')
async def update_gate(gate_key: str, payload: GateUpdate, authorization: str | None=Header(None,alias='Authorization')):
    actor=owner(authorization)
    if gate_key not in REQUIRED_GATES: raise HTTPException(404,'Unknown transition gate')
    ts=now()
    if payload.status=='READY':
        if not payload.evidence_ids: raise HTTPException(409,'READY gate requires verified evidence')
        ev=await get_backend().select('cuba_transition_evidence',params={'evidence_id':f'in.({",".join(payload.evidence_ids)})','limit':'200'}) or []
        verified={r.get('evidence_id') for r in ev if r.get('evidence_status')=='VERIFIED'}
        missing=[x for x in payload.evidence_ids if x not in verified]
        if missing: raise HTTPException(409,f'Gate evidence is not verified: {missing}')
    values={'status':payload.status,'evidence_summary':payload.evidence_summary,'evidence_ids':payload.evidence_ids,'reviewed_by':actor['id'],'reviewed_at':ts,'updated_at':ts}
    await get_backend().patch('cuba_transition_gates',values,params={'gate_key':f'eq.{gate_key}'})
    g=await gates(); ev=evaluate(g)
    await get_backend().patch('cuba_transition_state',{'transition_candidate':ev['candidate_ready'],'last_evaluated_at':ts,'last_evaluation_summary':f"{ev['ready_gate_count']}/{ev['required_gate_count']} gates ready",'updated_at':ts},params={'singleton_key':'eq.CU'})
    return {'gate_key':gate_key,'status':payload.status,'evaluation':ev}

@app.post('/cuba-transition/promote')
async def promote(payload: PromoteRequest, authorization: str | None=Header(None,alias='Authorization')):
    actor=owner(authorization); ts=now(); g=await gates(); ev=evaluate(g)
    if not ev['candidate_ready']: raise HTTPException(409,{'message':'Cuba cannot be promoted while transition gates remain blocked','blockers':ev['blockers']})
    # Additional legal-time safeguard: every relied-upon verified restriction-removal instrument with an effective date must already be effective.
    evidence=await get_backend().select('cuba_transition_evidence',params={'evidence_status':'eq.VERIFIED','removes_restriction':'eq.true','limit':'200'}) or []
    future=[]
    for item in evidence:
        raw=item.get('effective_date')
        if raw:
            try:
                if date.fromisoformat(str(raw)[:10])>date.today(): future.append(item.get('evidence_id'))
            except ValueError:
                future.append(item.get('evidence_id'))
    if future: raise HTTPException(409,{'message':'One or more relied-upon legal changes are not yet effective','evidence_ids':future})
    profile_rows=await get_backend().select('country_activation_profiles',params={'country_code':'eq.CU','limit':'1'}) or []
    if not profile_rows: raise HTTPException(409,'Activate the real Cuba current-law profile first')
    prior=profile_rows[0].get('operating_status') or 'LIMITED'
    await get_backend().patch('country_activation_profiles',{'operating_status':'READY','owner_approved':True,'approved_by':actor['id'],'approved_at':ts,
        'notes':'CU promoted to LIVE/READY only after all Cuba transition gates and effective-date checks passed. Normal transaction/product/counterparty controls still apply.','updated_at':ts},params={'country_code':'eq.CU'})
    await get_backend().patch('cuba_transition_state',{'current_operating_status':'READY','transition_candidate':True,'owner_approved':True,'owner_approved_at':ts,'updated_at':ts},params={'singleton_key':'eq.CU'})
    await get_backend().insert('cuba_transition_events',{'event_id':f'cute_{secrets.token_urlsafe(12)}','event_type':'country_promoted','actor_id':actor['id'],'prior_status':prior,'new_status':'READY','summary':payload.note,'payload':{'evaluation':ev},'created_at':ts})
    return {'country_code':'CU','prior_status':prior,'new_status':'READY','mode':'LIVE','owner_approved':True,'evaluation':ev}

@app.post('/cuba-transition/rollback')
async def rollback(authorization: str | None=Header(None,alias='Authorization')):
    actor=owner(authorization); ts=now(); profile_rows=await get_backend().select('country_activation_profiles',params={'country_code':'eq.CU','limit':'1'}) or []
    if not profile_rows: raise HTTPException(404,'CU profile not found')
    prior=profile_rows[0].get('operating_status') or 'LIMITED'
    await get_backend().patch('country_activation_profiles',{'operating_status':'LIMITED','owner_approved':False,'approved_by':None,'approved_at':None,'updated_at':ts},params={'country_code':'eq.CU'})
    await get_backend().patch('cuba_transition_state',{'current_operating_status':'LIMITED','transition_candidate':False,'owner_approved':False,'owner_approved_at':None,'updated_at':ts},params={'singleton_key':'eq.CU'})
    await get_backend().insert('cuba_transition_events',{'event_id':f'cute_{secrets.token_urlsafe(12)}','event_type':'rollback','actor_id':actor['id'],'prior_status':prior,'new_status':'LIMITED','summary':'Cuba transition rolled back to fail-closed LIMITED state','created_at':ts})
    return {'country_code':'CU','prior_status':prior,'new_status':'LIMITED','release_gate':'HOLD'}
