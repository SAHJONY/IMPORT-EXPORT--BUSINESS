from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from ai_brain_api import call_openai, openai_configured, MODEL_STACK
from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY AI Trade Agent', version='1.0.0', docs_url=None, redoc_url=None)

Role = Literal['owner', 'employee']


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def employee_token() -> str:
    token = os.getenv('EMPLOYEE_TOKEN', '').strip()
    if not token:
        raise HTTPException(503, 'Employee access not configured')
    return token


def identity(role: str | None, authorization: str | None, employee_id: str | None) -> dict:
    if role not in {'owner', 'employee'}:
        raise HTTPException(400, 'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    token = authorization.removeprefix('Bearer ').strip()
    if role == 'owner':
        if not verify_owner_token(token):
            raise HTTPException(403, 'Invalid owner credential')
        return {'role': 'owner', 'id': 'owner'}
    if not secrets.compare_digest(token, employee_token()):
        raise HTTPException(403, 'Invalid employee credential')
    return {'role': 'employee', 'id': (employee_id or 'staff')[:160]}


class LaunchIn(BaseModel):
    use_ai_enhancement: bool = True
    allowed_origin_countries: list[str] = []
    excluded_origin_countries: list[str] = []
    sourcing_notes: str | None = Field(default=None, max_length=5000)


class JobStatusIn(BaseModel):
    status: Literal['RESEARCH_QUEUED', 'AWAITING_CANDIDATES', 'AWAITING_OWNER_REVIEW', 'PAUSED', 'CLOSED']
    note: str | None = Field(default=None, max_length=4000)


def deterministic_packet(intake: dict, customer: dict | None, sourcing_request_id: str, managed_trade_request_id: str, payload: LaunchIn) -> dict:
    business = (customer or {}).get('trade_name') or (customer or {}).get('legal_name') or intake.get('customer_id')
    product = intake.get('product_need') or 'Unspecified product'
    destination = (intake.get('destination_country') or 'UNKNOWN').upper()
    currency = (intake.get('currency') or 'USD').upper()
    quantity = intake.get('quantity')
    budget = intake.get('target_budget')
    specification = intake.get('specifications') or 'To be confirmed with buyer.'
    delivery = intake.get('target_delivery_date') or 'Not specified'
    incoterm = intake.get('preferred_incoterm') or 'To be proposed based on corridor and landed economics'
    allowed = [str(x).upper() for x in payload.allowed_origin_countries if str(x).strip()]
    excluded = [str(x).upper() for x in payload.excluded_origin_countries if str(x).strip()]
    rfq = (
        f'SAHJONY NON-BINDING RFQ DRAFT\n'
        f'Buyer/Project: {business}\n'
        f'Product: {product}\n'
        f'Specifications: {specification}\n'
        f'Quantity: {quantity if quantity is not None else "Please quote scalable MOQ options"}\n'
        f'Destination: {destination}\n'
        f'Target delivery: {delivery}\n'
        f'Preferred Incoterm: {incoterm}\n'
        f'Target budget: {budget if budget is not None else "Not disclosed"} {currency}\n\n'
        'Supplier response requested: manufacturer/legal entity name, manufacturing country, exact product match, unit price, MOQ, lead time, Incoterm, payment terms, packaging, certifications/test reports, warranty, production capacity, export experience, and quotation validity.\n\n'
        'This draft is for sourcing preparation only. It is not a purchase order, supplier commitment, payment authorization, compliance clearance, or shipment release.'
    )
    return {
        'business': business,
        'product_need': product,
        'specifications': specification,
        'quantity': quantity,
        'destination_country': destination,
        'target_budget': budget,
        'currency': currency,
        'target_delivery_date': delivery,
        'preferred_incoterm': incoterm,
        'allowed_origin_countries': allowed,
        'excluded_origin_countries': excluded,
        'worldwide_search': not bool(allowed),
        'managed_trade_request_id': managed_trade_request_id,
        'sourcing_request_id': sourcing_request_id,
        'research_requirements': [
            'Identify direct manufacturers and credible authorized distributors.',
            'Capture source URL/reference and evidence date for every candidate.',
            'Compare MOQ, unit economics, lead time, payment terms and Incoterm.',
            'Do not treat commercial attractiveness as trade authorization.',
            'Keep every supplier blocked until required origin/destination controls are verified.',
            'Calculate landed-cost inputs before commercial recommendation.',
        ],
        'rfq_draft': rfq,
        'sourcing_notes': payload.sourcing_notes,
    }


async def ensure_promotion(intake: dict, actor: dict, payload: LaunchIn) -> tuple[str, str]:
    backend = get_backend()
    mtr = intake.get('managed_trade_request_id')
    gsr = intake.get('sourcing_request_id')
    if mtr and gsr:
        return str(mtr), str(gsr)
    if intake.get('qualification_status') != 'QUALIFIED':
        raise HTTPException(409, 'AI Trade Agent may launch only from a QUALIFIED CRM intake')
    ts = now()
    mtr = str(mtr or f'mtr_{secrets.token_urlsafe(10)}')
    gsr = str(gsr or f'gsr_{secrets.token_urlsafe(10)}')
    common = {
        'product_need': intake['product_need'],
        'specifications': intake.get('specifications'),
        'quantity': intake.get('quantity'),
        'target_budget': intake.get('target_budget'),
        'currency': intake.get('currency') or 'USD',
        'destination_country': intake.get('destination_country'),
        'target_delivery_date': intake.get('target_delivery_date'),
    }
    if not intake.get('managed_trade_request_id'):
        await backend.insert('managed_trade_requests', {
            'request_id': mtr,
            'requester_type': 'BUYER',
            'requester_ref': intake['customer_id'],
            'private_business_id': None,
            'employee_id': intake.get('assigned_employee_id'),
            'assigned_owner_id': 'owner',
            'assigned_employee_id': intake.get('assigned_employee_id'),
            **common,
            'status': 'INTAKE',
            'created_at': ts,
            'updated_at': ts,
        })
    if not intake.get('sourcing_request_id'):
        await backend.insert('global_sourcing_requests', {
            'sourcing_request_id': gsr,
            'requester_type': 'BUYER',
            'requester_ref': intake['customer_id'],
            **common,
            'allowed_origin_countries': [str(x).upper() for x in payload.allowed_origin_countries if str(x).strip()],
            'excluded_origin_countries': [str(x).upper() for x in payload.excluded_origin_countries if str(x).strip()],
            'worldwide_search': not bool(payload.allowed_origin_countries),
            'status': 'SEARCHING',
            'assigned_owner_id': 'owner',
            'assigned_employee_id': intake.get('assigned_employee_id'),
            'created_by': actor['id'],
            'created_at': ts,
            'updated_at': ts,
        })
    await backend.patch('customer_trade_intakes', {
        'status': 'PROMOTED',
        'managed_trade_request_id': mtr,
        'sourcing_request_id': gsr,
        'updated_at': ts,
    }, params={'intake_id': f'eq.{intake["intake_id"]}'})
    return mtr, gsr


async def ai_enhance(packet: dict) -> dict:
    if not openai_configured():
        return {'status': 'SKIPPED', 'reason': 'OPENAI_API_KEY not configured'}
    prompt = (
        'Prepare a rigorous sourcing brief and supplier-research plan for this qualified trade intake. '
        'Do not name a supplier unless evidence is actually supplied in the context. Do not authorize payments, compliance, supplier selection, shipment release, or legal-party roles. '
        'Return practical research criteria, RFQ improvements, commercial questions, landed-cost inputs to collect, and missing evidence.\n\n'
        f'PACKET:\n{packet}'
    )
    try:
        result = await call_openai(prompt, MODEL_STACK['openai_primary'](), 2200)
        return {'status': 'COMPLETED', 'provider': result.get('provider'), 'model': result.get('model'), 'analysis': result.get('text', '')}
    except Exception as exc:
        return {'status': 'DEGRADED', 'error_type': type(exc).__name__, 'message': str(exc)[:500]}


async def write_audit(actor: dict, event_type: str, summary: str, job_id: str, intake_id: str, payload: dict | None = None) -> None:
    await get_backend().insert('trade_agent_audit', {
        'event_id': f'taa_{secrets.token_urlsafe(10)}',
        'job_id': job_id,
        'intake_id': intake_id,
        'actor_role': actor['role'],
        'actor_id': actor['id'],
        'event_type': event_type,
        'summary': summary,
        'payload': payload or {},
        'created_at': now(),
    })


@app.get('/trade-agent/health')
async def health():
    backend = persistent_backend_status()
    return {
        'status': 'ok' if backend['configured'] else 'configuration_required',
        'service': 'sahjony-ai-trade-agent',
        'crm_to_sourcing_orchestration': True,
        'durable_jobs': backend['configured'],
        'persistence_provider': backend['provider'],
        'ai_enhancement_available': openai_configured(),
        'automatic_supplier_commitment': False,
        'automatic_payment_authority': False,
        'automatic_compliance_release': False,
        'automatic_shipment_release': False,
        'outbound_supplier_send': 'APPROVAL_AND_PROVIDER_REQUIRED',
        'fail_closed': True,
    }


@app.post('/trade-agent/intakes/{intake_id}/launch')
async def launch(
    intake_id: str,
    payload: LaunchIn,
    x_role: str | None = Header(None, alias='X-Role'),
    authorization: str | None = Header(None, alias='Authorization'),
    x_employee_id: str | None = Header(None, alias='X-Employee-Id'),
):
    actor = identity(x_role, authorization, x_employee_id)
    backend = get_backend()
    rows = await backend.select('customer_trade_intakes', params={'intake_id': f'eq.{intake_id}', 'limit': '1'}) or []
    if not rows:
        raise HTTPException(404, 'CRM intake not found')
    intake = rows[0]
    if intake.get('qualification_status') != 'QUALIFIED':
        raise HTTPException(409, 'Qualify this CRM intake before launching the AI Trade Agent')

    existing = await backend.select('trade_agent_jobs', params={'intake_id': f'eq.{intake_id}', 'limit': '1'}) or []
    if existing and existing[0].get('status') not in {'CLOSED'}:
        return {'job': existing[0], 'already_launched': True}

    customer_rows = await backend.select('customer_accounts', params={'customer_id': f'eq.{intake.get("customer_id")}', 'limit': '1'}) or []
    customer = customer_rows[0] if customer_rows else None
    mtr, gsr = await ensure_promotion(intake, actor, payload)
    packet = deterministic_packet(intake, customer, gsr, mtr, payload)
    enhancement = await ai_enhance(packet) if payload.use_ai_enhancement else {'status': 'DISABLED'}
    job_id = f'taj_{secrets.token_urlsafe(10)}'
    ts = now()
    job = {
        'job_id': job_id,
        'intake_id': intake_id,
        'customer_id': intake.get('customer_id'),
        'managed_trade_request_id': mtr,
        'sourcing_request_id': gsr,
        'status': 'RESEARCH_QUEUED',
        'phase': 'SUPPLIER_RESEARCH',
        'packet': packet,
        'ai_enhancement': enhancement,
        'candidate_count': 0,
        'next_actions': [
            {'action': 'RESEARCH_SUPPLIERS', 'approval_required': False, 'execution': 'INTERNAL_RESEARCH'},
            {'action': 'ADD_EVIDENCED_CANDIDATES', 'approval_required': False, 'execution': 'GLOBAL_SOURCING'},
            {'action': 'SEND_RFQ_TO_SUPPLIERS', 'approval_required': True, 'execution': 'OUTBOUND_PROVIDER_REQUIRED'},
            {'action': 'VERIFY_TRADE_CONTROLS', 'approval_required': True, 'execution': 'OWNER_COMPLIANCE'},
            {'action': 'SELECT_SUPPLIER', 'approval_required': True, 'execution': 'OWNER_ONLY'},
        ],
        'authority': 'ADVISORY_AND_ORCHESTRATION_ONLY',
        'created_by_role': actor['role'],
        'created_by': actor['id'],
        'created_at': ts,
        'updated_at': ts,
    }
    await backend.insert('trade_agent_jobs', job)
    await write_audit(actor, 'trade_agent_launched', 'Qualified CRM intake promoted and sourcing preparation created', job_id, intake_id, {'sourcing_request_id': gsr, 'managed_trade_request_id': mtr})
    return {'job': job, 'already_launched': False}


@app.get('/trade-agent/jobs')
async def jobs(
    x_role: str | None = Header(None, alias='X-Role'),
    authorization: str | None = Header(None, alias='Authorization'),
    x_employee_id: str | None = Header(None, alias='X-Employee-Id'),
):
    actor = identity(x_role, authorization, x_employee_id)
    rows = await get_backend().select('trade_agent_jobs', params={'order': 'updated_at.desc', 'limit': '250'}) or []
    if actor['role'] == 'employee':
        rows = [r for r in rows if r.get('created_by') == actor['id'] or r.get('assigned_employee_id') == actor['id']]
    return {'jobs': rows}


@app.get('/trade-agent/jobs/{job_id}')
async def job_detail(
    job_id: str,
    x_role: str | None = Header(None, alias='X-Role'),
    authorization: str | None = Header(None, alias='Authorization'),
    x_employee_id: str | None = Header(None, alias='X-Employee-Id'),
):
    actor = identity(x_role, authorization, x_employee_id)
    backend = get_backend()
    rows = await backend.select('trade_agent_jobs', params={'job_id': f'eq.{job_id}', 'limit': '1'}) or []
    if not rows:
        raise HTTPException(404, 'Trade Agent job not found')
    job = rows[0]
    if actor['role'] == 'employee' and job.get('created_by') not in {actor['id'], None} and job.get('assigned_employee_id') != actor['id']:
        raise HTTPException(403, 'Job is outside employee scope')
    candidates = await backend.select('global_supplier_candidates', params={'sourcing_request_id': f'eq.{job.get("sourcing_request_id")}', 'order': 'updated_at.desc', 'limit': '500'}) or []
    return {'job': {**job, 'candidate_count': len(candidates)}, 'candidates': candidates}


@app.patch('/trade-agent/jobs/{job_id}/status')
async def set_job_status(
    job_id: str,
    payload: JobStatusIn,
    x_role: str | None = Header(None, alias='X-Role'),
    authorization: str | None = Header(None, alias='Authorization'),
    x_employee_id: str | None = Header(None, alias='X-Employee-Id'),
):
    actor = identity(x_role, authorization, x_employee_id)
    backend = get_backend()
    rows = await backend.select('trade_agent_jobs', params={'job_id': f'eq.{job_id}', 'limit': '1'}) or []
    if not rows:
        raise HTTPException(404, 'Trade Agent job not found')
    if payload.status in {'AWAITING_OWNER_REVIEW', 'CLOSED'} and actor['role'] != 'owner':
        raise HTTPException(403, 'Owner authority required for owner-review and close transitions')
    values = {'status': payload.status, 'updated_at': now()}
    await backend.patch('trade_agent_jobs', values, params={'job_id': f'eq.{job_id}'})
    await write_audit(actor, 'trade_agent_status_changed', f'Trade Agent job -> {payload.status}', job_id, rows[0]['intake_id'], {'note': payload.note})
    return {'job_id': job_id, 'status': payload.status, 'note': payload.note}
