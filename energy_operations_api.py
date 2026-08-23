from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Energy Deal Operations', version='1.0.0', docs_url=None, redoc_url=None)

TaskStatus = Literal['OPEN','IN_PROGRESS','BLOCKED','WAITING_OWNER','DONE','CANCELLED']
Priority = Literal['CRITICAL','HIGH','MEDIUM','STANDARD']

STAGE_ACTIONS = {
    'LEAD': ('Qualify counterparties and commercial requirement', 'ENTITY_REVIEW'),
    'ENTITY_REVIEW': ('Complete KYB, ownership and corporate-contact evidence', 'MANDATE_REVIEW'),
    'MANDATE_REVIEW': ('Verify seller/buyer authority and mandate chain', 'PRODUCT_REVIEW'),
    'PRODUCT_REVIEW': ('Verify crude grade, quantity, specifications and source evidence', 'COMMERCIAL_FIT'),
    'COMMERCIAL_FIT': ('Validate executable pricing, Incoterm and transaction procedure', 'COMPLIANCE_REVIEW'),
    'COMPLIANCE_REVIEW': ('Complete sanctions, origin/destination and end-use review', 'BANKABILITY_REVIEW'),
    'BANKABILITY_REVIEW': ('Verify bankability and payment-instrument acceptability', 'LOGISTICS_REVIEW'),
    'LOGISTICS_REVIEW': ('Verify load/discharge, inspection, terminal and vessel plan', 'OWNER_REVIEW'),
    'OWNER_REVIEW': ('Prepare owner decision packet and resolve final exceptions', 'READY_FOR_TRANSACTION'),
    'READY_FOR_TRANSACTION': ('Maintain freshness of approvals and evidence until execution', 'READY_FOR_TRANSACTION'),
    'HOLD': ('Resolve hold reason before any further transaction progression', 'HOLD'),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


def cron_identity(auth: str | None) -> None:
    secret = os.getenv('CRON_SECRET', '').strip()
    if not secret:
        raise HTTPException(503, 'CRON_SECRET is not configured')
    if not auth or not secrets.compare_digest(auth, f'Bearer {secret}'):
        raise HTTPException(401, 'Invalid cron authorization')


def projected_fee(deal: dict) -> float:
    qty = float(deal.get('quantity_bbl') or 0)
    return float(deal.get('sahjony_fee_flat') or 0) + qty * float(deal.get('sahjony_fee_per_bbl') or 0)


def priority_for(deal: dict) -> Priority:
    if str(deal.get('stage') or '').upper() == 'HOLD' or int(deal.get('risk_score') or 0) >= 70:
        return 'CRITICAL'
    fee = projected_fee(deal)
    stage = str(deal.get('stage') or 'LEAD').upper()
    if fee >= 500_000 or stage in {'OWNER_REVIEW','READY_FOR_TRANSACTION'}:
        return 'HIGH'
    if fee >= 100_000 or stage in {'COMPLIANCE_REVIEW','BANKABILITY_REVIEW','LOGISTICS_REVIEW'}:
        return 'MEDIUM'
    return 'STANDARD'


def action_for(deal: dict) -> dict:
    stage = str(deal.get('stage') or 'LEAD').upper()
    action, next_stage = STAGE_ACTIONS.get(stage, ('Review deal state and define next controlled action', stage))
    if deal.get('screening_status') in {'HOLD','BLOCKED'}:
        action = 'Resolve sanctions/restricted-party screening before any progression'
        next_stage = 'HOLD'
    if int(deal.get('risk_score') or 0) >= 70:
        action = 'Resolve critical fraud/compliance risk flags before commercial progression'
        next_stage = 'HOLD'
    return {'action': action, 'recommended_next_stage': next_stage}


class TaskUpdateIn(BaseModel):
    status: TaskStatus
    assigned_to: str | None = Field(default=None, max_length=180)
    due_at: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=3000)


async def latest_task_map() -> dict[str, dict]:
    rows = await get_backend().select('energy_operations_tasks', params={'order':'updated_at.desc','limit':'3000'}) or []
    result = {}
    for row in rows:
        did = row.get('deal_id')
        if did and did not in result:
            result[str(did)] = row
    return result


async def reconcile(trigger: str) -> dict:
    backend = get_backend()
    deals = await backend.select('energy_deals', params={'order':'updated_at.desc','limit':'2000'}) or []
    latest = await latest_task_map()
    created = updated = skipped = 0
    for deal in deals:
        stage = str(deal.get('stage') or 'LEAD').upper()
        if stage == 'CLOSED':
            skipped += 1
            continue
        did = str(deal.get('deal_id') or '')
        if not did:
            continue
        recommended = action_for(deal)
        priority = priority_for(deal)
        existing = latest.get(did)
        task = {
            'deal_id': did,
            'crude_grade': deal.get('crude_grade'),
            'quantity_bbl': deal.get('quantity_bbl'),
            'stage': stage,
            'priority': priority,
            'projected_sahjony_fee': projected_fee(deal),
            'next_action': recommended['action'],
            'recommended_next_stage': recommended['recommended_next_stage'],
            'owner_decision_required': stage == 'OWNER_REVIEW',
            'release_allowed': bool(deal.get('release_allowed')),
            'risk_score': int(deal.get('risk_score') or 0),
            'trigger': trigger,
            'updated_at': now(),
        }
        if existing and existing.get('status') not in {'DONE','CANCELLED'}:
            await backend.patch('energy_operations_tasks', task, params={'task_id':f"eq.{existing.get('task_id')}"})
            updated += 1
        else:
            task.update({'task_id': f'eot_{secrets.token_urlsafe(12)}', 'status':'WAITING_OWNER' if stage == 'OWNER_REVIEW' else ('BLOCKED' if stage == 'HOLD' else 'OPEN'), 'assigned_to':None, 'due_at':None, 'note':None, 'created_at':now()})
            await backend.insert('energy_operations_tasks', task)
            created += 1
    event = {'event_id':f'eor_{secrets.token_urlsafe(12)}','trigger':trigger,'deals_seen':len(deals),'created':created,'updated':updated,'skipped':skipped,'created_at':now()}
    await backend.insert('energy_operations_reconciliations', event)
    return event


@app.get('/energy-operations/health')
async def health():
    p = persistent_backend_status()
    return {
        'status':'ok' if p['configured'] else 'configuration_required',
        'service':'sahjony-energy-deal-operations',
        'durable_action_queue':True,
        'automatic_reconciliation':True,
        'owner_decision_escalation':True,
        'hold_escalation':True,
        'automatic_contract_execution':False,
        'automatic_payment_authority':False,
        'automatic_compliance_clearance':False,
        'automatic_cargo_release':False,
        'fail_closed':True,
        'persistence_provider':p['provider'],
    }


@app.post('/energy-operations/reconcile')
async def owner_reconcile(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    return await reconcile('OWNER_MANUAL')


@app.get('/energy-operations/cron-reconcile')
async def cron_reconcile(authorization: str | None = Header(None, alias='Authorization')):
    cron_identity(authorization)
    return await reconcile('VERCEL_CRON')


@app.get('/energy-operations/tasks')
async def tasks(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_operations_tasks', params={'order':'updated_at.desc','limit':'2000'}) or []
    order = {'CRITICAL':0,'HIGH':1,'MEDIUM':2,'STANDARD':3}
    rows.sort(key=lambda r: (r.get('status') in {'DONE','CANCELLED'}, order.get(str(r.get('priority')),9), str(r.get('updated_at') or '')), reverse=False)
    return {'tasks':rows,'authority':'OPERATIONS_ORCHESTRATION_ONLY'}


@app.patch('/energy-operations/tasks/{task_id}')
async def update_task(task_id: str, payload: TaskUpdateIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_operations_tasks', params={'task_id':f'eq.{task_id}','limit':'1'}) or []
    if not rows:
        raise HTTPException(404, 'Energy operations task not found')
    patch = {**payload.model_dump(), 'updated_at':now()}
    await get_backend().patch('energy_operations_tasks', patch, params={'task_id':f'eq.{task_id}'})
    return {'task_id':task_id,'updated':True,'status':payload.status}


@app.get('/energy-operations/summary')
async def summary(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_operations_tasks', params={'order':'updated_at.desc','limit':'2000'}) or []
    open_rows = [r for r in rows if r.get('status') not in {'DONE','CANCELLED'}]
    return {
        'open_tasks':len(open_rows),
        'critical':sum(1 for r in open_rows if r.get('priority')=='CRITICAL'),
        'high':sum(1 for r in open_rows if r.get('priority')=='HIGH'),
        'waiting_owner':sum(1 for r in open_rows if r.get('status')=='WAITING_OWNER'),
        'blocked':sum(1 for r in open_rows if r.get('status')=='BLOCKED'),
        'projected_fee_under_active_management':sum(float(r.get('projected_sahjony_fee') or 0) for r in open_rows),
        'realized_revenue':None,
        'note':'Projected fees are not realized revenue and remain contingent on verified execution, closing, reconciliation and collection.',
    }
