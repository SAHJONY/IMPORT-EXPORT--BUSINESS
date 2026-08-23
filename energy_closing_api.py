from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Energy Closing & Reconciliation', version='1.0.0', docs_url=None, redoc_url=None)

RoomStatus = Literal['OPEN','CLOSING','DELIVERY_REVIEW','FEE_RECONCILIATION','COMPLETED','HOLD','CANCELLED']
MilestoneStatus = Literal['PENDING','REVIEW','VERIFIED','FAILED','NOT_APPLICABLE']

REQUIRED_MILESTONES = [
    'executed_contract_evidence',
    'final_compliance_refresh',
    'buyer_payment_readiness',
    'seller_performance_readiness',
    'terminal_or_loading_confirmation',
    'vessel_or_logistics_confirmation',
    'inspection_evidence',
    'cargo_loading_evidence',
    'bill_of_lading_or_equivalent',
    'delivery_or_discharge_evidence',
    'fee_invoice_evidence',
    'fee_collection_evidence',
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


async def one(table: str, field: str, value: str) -> dict:
    rows = await get_backend().select(table, params={field: f'eq.{value}', 'limit': '1'}) or []
    if not rows:
        raise HTTPException(404, f'{table} record not found')
    return rows[0]


class RoomIn(BaseModel):
    deal_id: str = Field(min_length=3, max_length=180)
    closing_reference: str | None = Field(default=None, max_length=300)
    expected_loading_window: str | None = Field(default=None, max_length=240)
    expected_delivery_window: str | None = Field(default=None, max_length=240)
    notes: str | None = Field(default=None, max_length=4000)


class MilestoneIn(BaseModel):
    milestone: str = Field(min_length=3, max_length=140)
    status: MilestoneStatus = 'REVIEW'
    reference: str | None = Field(default=None, max_length=1600)
    source: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=3000)


class RoomStatusIn(BaseModel):
    status: RoomStatus
    note: str | None = Field(default=None, max_length=3000)


class FeeReconciliationIn(BaseModel):
    invoiced_amount: float | None = Field(default=None, ge=0)
    collected_amount: float = Field(ge=0)
    currency: str = Field(default='USD', min_length=3, max_length=12)
    collection_reference: str = Field(min_length=3, max_length=1200)
    collection_date: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=3000)


async def milestones(room_id: str) -> list[dict]:
    return await get_backend().select('energy_transaction_milestones', params={'room_id': f'eq.{room_id}', 'order': 'created_at.asc', 'limit': '500'}) or []


def milestone_summary(rows: list[dict]) -> dict:
    latest: dict[str, dict] = {}
    for row in rows:
        latest[str(row.get('milestone') or '')] = row
    verified = [m for m in REQUIRED_MILESTONES if (latest.get(m) or {}).get('status') == 'VERIFIED']
    failed = [m for m in REQUIRED_MILESTONES if (latest.get(m) or {}).get('status') == 'FAILED']
    pending = [m for m in REQUIRED_MILESTONES if m not in verified and m not in failed and (latest.get(m) or {}).get('status') != 'NOT_APPLICABLE']
    return {
        'required': len(REQUIRED_MILESTONES),
        'verified': len(verified),
        'failed': len(failed),
        'pending': len(pending),
        'verified_milestones': verified,
        'failed_milestones': failed,
        'pending_milestones': pending,
        'closing_evidence_complete': not pending and not failed,
    }


@app.get('/energy-closing/health')
async def health():
    p = persistent_backend_status()
    return {
        'status': 'ok' if p['configured'] else 'configuration_required',
        'service': 'sahjony-energy-closing-reconciliation',
        'transaction_rooms': True,
        'delivery_evidence_tracking': True,
        'fee_reconciliation': True,
        'realized_revenue_requires_collection_evidence': True,
        'automatic_contract_execution': False,
        'automatic_payment_authority': False,
        'automatic_cargo_release': False,
        'automatic_compliance_clearance': False,
        'fail_closed': True,
        'persistence_provider': p['provider'],
    }


@app.post('/energy-closing/rooms')
async def create_room(payload: RoomIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    deal = await one('energy_deals', 'deal_id', payload.deal_id)
    if str(deal.get('stage') or '').upper() != 'READY_FOR_TRANSACTION':
        raise HTTPException(409, 'Deal must be READY_FOR_TRANSACTION before a closing room can be opened')
    if deal.get('owner_approved') is not True or deal.get('release_allowed') is not True:
        raise HTTPException(409, 'Owner approval and release_allowed are required before opening a closing room')
    if str(deal.get('stage') or '').upper() == 'HOLD' or float(deal.get('risk_score') or 0) >= 80:
        raise HTTPException(409, 'High-risk or HOLD deal cannot enter closing')
    existing = await get_backend().select('energy_transaction_rooms', params={'deal_id': f'eq.{payload.deal_id}', 'limit': '1'}) or []
    if existing:
        return {'room': existing[0], 'created': False}
    rid = f'etr_{secrets.token_urlsafe(12)}'; ts = now()
    row = {
        'room_id': rid,
        'deal_id': payload.deal_id,
        'status': 'OPEN',
        'closing_reference': payload.closing_reference,
        'expected_loading_window': payload.expected_loading_window,
        'expected_delivery_window': payload.expected_delivery_window,
        'notes': payload.notes,
        'realized_revenue': 0.0,
        'currency': deal.get('currency') or 'USD',
        'created_at': ts,
        'updated_at': ts,
    }
    await get_backend().insert('energy_transaction_rooms', row)
    for milestone in REQUIRED_MILESTONES:
        await get_backend().insert('energy_transaction_milestones', {
            'milestone_id': f'etm_{secrets.token_urlsafe(12)}', 'room_id': rid, 'deal_id': payload.deal_id,
            'milestone': milestone, 'status': 'PENDING', 'reference': None, 'source': None,
            'notes': None, 'verified_by': None, 'verified_at': None, 'created_at': ts, 'updated_at': ts,
        })
    return {'room': row, 'created': True, 'required_milestones': REQUIRED_MILESTONES}


@app.get('/energy-closing/rooms')
async def list_rooms(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('energy_transaction_rooms', params={'order': 'updated_at.desc', 'limit': '1000'}) or []
    out = []
    for room in rows:
        ms = await milestones(str(room.get('room_id')))
        out.append({**room, 'milestone_summary': milestone_summary(ms)})
    return {'rooms': out}


@app.get('/energy-closing/rooms/{room_id}')
async def room_detail(room_id: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    room = await one('energy_transaction_rooms', 'room_id', room_id)
    ms = await milestones(room_id)
    recs = await get_backend().select('energy_fee_reconciliations', params={'room_id': f'eq.{room_id}', 'order': 'created_at.desc', 'limit': '50'}) or []
    return {'room': room, 'milestones': ms, 'milestone_summary': milestone_summary(ms), 'fee_reconciliations': recs}


@app.post('/energy-closing/rooms/{room_id}/milestones')
async def record_milestone(room_id: str, payload: MilestoneIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    room = await one('energy_transaction_rooms', 'room_id', room_id)
    if payload.milestone not in REQUIRED_MILESTONES:
        raise HTTPException(400, 'Unknown closing milestone')
    ts = now()
    row = {
        'milestone_id': f'etm_{secrets.token_urlsafe(12)}', 'room_id': room_id, 'deal_id': room.get('deal_id'),
        **payload.model_dump(), 'verified_by': 'owner' if payload.status == 'VERIFIED' else None,
        'verified_at': ts if payload.status == 'VERIFIED' else None, 'created_at': ts, 'updated_at': ts,
    }
    await get_backend().insert('energy_transaction_milestones', row)
    if payload.status == 'FAILED':
        await get_backend().patch('energy_transaction_rooms', {'status': 'HOLD', 'updated_at': ts}, params={'room_id': f'eq.{room_id}'})
    return {'milestone': row}


@app.patch('/energy-closing/rooms/{room_id}/status')
async def set_room_status(room_id: str, payload: RoomStatusIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    room = await one('energy_transaction_rooms', 'room_id', room_id)
    ms = await milestones(room_id)
    summary = milestone_summary(ms)
    if payload.status == 'COMPLETED' and not summary['closing_evidence_complete']:
        raise HTTPException(409, {'message': 'Closing evidence is incomplete', 'summary': summary})
    ts = now()
    await get_backend().patch('energy_transaction_rooms', {'status': payload.status, 'status_note': payload.note, 'updated_at': ts}, params={'room_id': f'eq.{room_id}'})
    if payload.status == 'COMPLETED':
        await get_backend().patch('energy_deals', {'stage': 'CLOSED', 'release_allowed': False, 'updated_at': ts}, params={'deal_id': f"eq.{room.get('deal_id')}"})
    return {'room_id': room_id, 'status': payload.status, 'milestone_summary': summary}


@app.post('/energy-closing/rooms/{room_id}/fee-reconciliation')
async def reconcile_fee(room_id: str, payload: FeeReconciliationIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    room = await one('energy_transaction_rooms', 'room_id', room_id)
    ms = await milestones(room_id)
    summary = milestone_summary(ms)
    if 'fee_collection_evidence' not in summary['verified_milestones']:
        raise HTTPException(409, 'Verified fee_collection_evidence is required before realized revenue can be recorded')
    if payload.collected_amount <= 0:
        raise HTTPException(409, 'Collected amount must be greater than zero to recognize realized revenue')
    ts = now(); rid = f'efr_{secrets.token_urlsafe(12)}'
    rec = {
        'reconciliation_id': rid, 'room_id': room_id, 'deal_id': room.get('deal_id'), **payload.model_dump(),
        'recognized_as_realized_revenue': True, 'confirmed_by': 'owner', 'created_at': ts,
    }
    await get_backend().insert('energy_fee_reconciliations', rec)
    previous = float(room.get('realized_revenue') or 0)
    await get_backend().patch('energy_transaction_rooms', {
        'realized_revenue': round(previous + payload.collected_amount, 2), 'currency': payload.currency,
        'status': 'FEE_RECONCILIATION' if room.get('status') != 'COMPLETED' else 'COMPLETED', 'updated_at': ts,
    }, params={'room_id': f'eq.{room_id}'})
    return {'reconciliation': rec, 'realized_revenue_total': round(previous + payload.collected_amount, 2)}


@app.get('/energy-closing/revenue-summary')
async def revenue_summary(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rooms = await get_backend().select('energy_transaction_rooms', params={'limit': '2000'}) or []
    recs = await get_backend().select('energy_fee_reconciliations', params={'limit': '5000'}) or []
    realized = sum(float(x.get('collected_amount') or 0) for x in recs if x.get('recognized_as_realized_revenue') is True)
    return {
        'transaction_rooms': len(rooms),
        'completed_rooms': sum(1 for x in rooms if x.get('status') == 'COMPLETED'),
        'rooms_on_hold': sum(1 for x in rooms if x.get('status') == 'HOLD'),
        'realized_revenue': round(realized, 2),
        'reconciled_fee_events': len(recs),
        'note': 'Realized revenue is recorded only from owner-confirmed fee collection evidence. Projected pipeline values are excluded.',
    }
