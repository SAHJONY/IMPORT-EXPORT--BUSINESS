from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Managed Trade Gateway', version='2.0.0', docs_url=None, redoc_url=None)
Role = Literal['owner', 'employee']

MILESTONES = [
    ('request_qualified', 'Business request qualified'),
    ('private_business_eligible', 'Cuban private business eligibility verified'),
    ('supplier_sourced', 'Supplier sourced'),
    ('supplier_due_diligence', 'Supplier due diligence passed'),
    ('product_classified', 'Product classification verified'),
    ('authorization_matched', 'Government authorization scope matched'),
    ('commercial_terms', 'Commercial terms approved'),
    ('payment_path', 'Lawful payment path approved'),
    ('documents_ready', 'Documents complete'),
    ('logistics_ready', 'Broker/forwarder/carrier path ready'),
    ('compliance_release', 'Compliance release approved'),
    ('owner_release', 'Owner final release'),
    ('delivery', 'Delivery confirmed'),
    ('reconciliation', 'Final financial reconciliation complete'),
]

PRE_RELEASE_KEYS = {
    'request_qualified', 'private_business_eligible', 'supplier_sourced',
    'supplier_due_diligence', 'product_classified', 'authorization_matched',
    'commercial_terms', 'payment_path', 'documents_ready', 'logistics_ready',
    'compliance_release',
}
SYSTEM_MANAGED_KEYS = {'owner_release', 'delivery', 'reconciliation'}
NON_WAIVABLE_KEYS = {
    'request_qualified', 'supplier_sourced', 'supplier_due_diligence',
    'product_classified', 'commercial_terms', 'payment_path',
    'documents_ready', 'logistics_ready', 'compliance_release',
    'owner_release', 'delivery', 'reconciliation',
}
ACTIVE_RELEASE_STATES = {'READY_FOR_EXECUTION', 'EXECUTING', 'DELIVERED', 'RECONCILED'}
TERMINAL_STATES = {'CLOSED', 'CANCELLED'}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emp_token() -> str:
    token = os.getenv('EMPLOYEE_TOKEN', '').strip()
    if not token:
        raise HTTPException(503, 'Employee access not configured')
    return token


def identity(role, authorization, employee_id):
    if role not in {'owner', 'employee'}:
        raise HTTPException(400, 'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    token = authorization.removeprefix('Bearer ').strip()
    if role == 'owner':
        if not verify_owner_token(token):
            raise HTTPException(403, 'Invalid owner credential')
        return {'role': 'owner', 'id': 'owner'}
    if not secrets.compare_digest(token, emp_token()):
        raise HTTPException(403, 'Invalid employee credential')
    return {'role': 'employee', 'id': (employee_id or 'staff')[:160]}


class RequestIn(BaseModel):
    requester_type: Literal['PRIVATE_BUSINESS', 'BUYER', 'EMPLOYEE', 'OTHER'] = 'PRIVATE_BUSINESS'
    requester_ref: str | None = None
    private_business_id: str | None = None
    employee_id: str | None = None
    product_need: str = Field(min_length=2, max_length=1000)
    specifications: str | None = None
    quantity: float | None = None
    target_budget: float | None = None
    currency: str = 'USD'
    destination_country: str = 'CU'
    target_delivery_date: str | None = None


class SupplierCandidateIn(BaseModel):
    supplier_id: str | None = None
    supplier_name: str = Field(min_length=2, max_length=240)
    supplier_country: str | None = None
    product_match: str | None = None
    unit_cost: float | None = None
    moq: float | None = None
    lead_time_days: int | None = None
    payment_terms: str | None = None
    incoterm: str | None = None
    score: float | None = None
    evidence: dict = {}


class CaseIn(BaseModel):
    request_id: str
    private_business_id: str | None = None
    supplier_candidate_id: str
    supplier_id: str | None = None
    sahjony_role: Literal[
        'MANAGED_TRADE_ORCHESTRATOR', 'AGENT', 'DISTRIBUTOR',
        'EXPORTER_OF_RECORD', 'IMPORTER_OF_RECORD', 'PRINCIPAL'
    ] = 'MANAGED_TRADE_ORCHESTRATOR'
    exporter_of_record: str | None = None
    importer_of_record: str | None = None
    customs_broker: str | None = None
    freight_forwarder: str | None = None
    settlement_provider: str | None = None


class MilestoneIn(BaseModel):
    status: Literal['PASS', 'FAIL', 'NOT_APPLICABLE']
    evidence_reference: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)


async def audit(actor, event, summary, request_id=None, case_id=None, payload=None):
    await get_backend().insert('managed_trade_audit', {
        'event_id': f'mta_{secrets.token_urlsafe(10)}',
        'managed_case_id': case_id,
        'request_id': request_id,
        'actor_role': actor['role'],
        'actor_id': actor['id'],
        'event_type': event,
        'summary': summary,
        'payload': payload or {},
        'created_at': now(),
    })


async def _one(table: str, params: dict[str, str]) -> dict[str, Any] | None:
    rows = await get_backend().select(table, params={**params, 'limit': '1'}) or []
    return rows[0] if rows else None


async def _case(case_id: str) -> dict[str, Any]:
    row = await _one('managed_trade_cases', {'managed_case_id': f'eq.{case_id}'})
    if not row:
        raise HTTPException(404, 'Managed trade case not found')
    return row


async def _request(request_id: str) -> dict[str, Any]:
    row = await _one('managed_trade_requests', {'request_id': f'eq.{request_id}'})
    if not row:
        raise HTTPException(404, 'Managed trade request not found')
    return row


def _trade_refs(case: dict[str, Any]) -> list[str]:
    values = [case.get('cuba_trade_case_id'), case.get('managed_case_id'), case.get('request_id')]
    return [str(v) for i, v in enumerate(values) if v and str(v) not in {str(x) for x in values[:i] if x}]


async def _rows_for_refs(table: str, field: str, refs: list[str], limit: int = 200) -> list[dict[str, Any]]:
    for ref in refs:
        rows = await get_backend().select(table, params={field: f'eq.{ref}', 'limit': str(limit)}) or []
        if rows:
            return rows
    return []


async def _selected_supplier(case: dict[str, Any]) -> dict[str, Any] | None:
    cid = case.get('supplier_candidate_id')
    if not cid:
        return None
    return await _one('managed_supplier_candidates', {
        'candidate_id': f'eq.{cid}',
        'request_id': f'eq.{case.get("request_id")}',
        'selected': 'eq.true',
    })


async def _corridor_evidence(case: dict[str, Any], request: dict[str, Any], supplier: dict[str, Any] | None) -> dict[str, Any]:
    origin = str((supplier or {}).get('supplier_country') or '').upper().strip()
    destination = str(request.get('destination_country') or '').upper().strip()
    if len(origin) not in {2, 3} or len(destination) not in {2, 3}:
        return {'verified': False, 'reason': 'Supplier origin and destination must use 2-3 character country codes'}
    corridor = await _one('trade_corridor_activations', {
        'origin_country_code': f'eq.{origin}',
        'destination_country_code': f'eq.{destination}',
    })
    origin_profile = await _one('country_activation_profiles', {'country_code': f'eq.{origin}'})
    destination_profile = await _one('country_activation_profiles', {'country_code': f'eq.{destination}'})
    coverage = corridor and all(bool(corridor.get(k)) for k in (
        'carrier_coverage', 'broker_coverage', 'banking_coverage', 'insurance_coverage', 'tax_model_verified'
    ))
    profiles_ok = all(
        p and p.get('scenario_mode') == 'LIVE' and p.get('operating_status') == 'READY'
        and bool(p.get('owner_approved')) and bool(p.get('live_execution_allowed', True))
        for p in (origin_profile, destination_profile)
    )
    verified = bool(
        corridor and corridor.get('status') == 'READY' and corridor.get('execution_mode') == 'LIVE'
        and bool(corridor.get('owner_approved')) and coverage and profiles_ok
    )
    return {
        'verified': verified,
        'origin': origin,
        'destination': destination,
        'corridor_id': (corridor or {}).get('corridor_id'),
        'reason': None if verified else 'Country/corridor governance is not LIVE/READY/owner-approved with all required coverage',
    }


async def _compliance_evidence(case: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if case.get('compliance_case_id'):
        exact = await _one('trade_compliance_cases', {'compliance_id': f'eq.{case["compliance_case_id"]}'})
        rows = [exact] if exact else []
    if not rows:
        rows = await _rows_for_refs('trade_compliance_cases', 'trade_case_id', refs, 50)
    if not rows:
        return {'verified': False, 'reason': 'No linked trade compliance case'}
    c = rows[0]
    verified = (
        c.get('sanctions_status') == 'clear'
        and c.get('export_control_status') in {'nrl', 'licensed'}
        and c.get('customs_status') in {'ready', 'filed', 'released'}
        and c.get('agency_status') in {'not_applicable', 'ready', 'approved'}
        and c.get('legal_status') in {'ready', 'approved'}
        and c.get('release_status') in {'ready', 'released'}
    )
    return {
        'verified': verified,
        'compliance_id': c.get('compliance_id'),
        'release_status': c.get('release_status'),
        'reason': None if verified else 'Compliance case has unresolved sanctions/export/customs/agency/legal/release controls',
    }


async def _document_evidence(refs: list[str]) -> dict[str, Any]:
    docs = await _rows_for_refs('trade_documents', 'trade_case_id', refs, 250)
    approved = [d for d in docs if d.get('status') in {'approved', 'released'}]
    unsafe = [d for d in docs if d.get('storage_status') in {'quarantined', 'rejected'} or d.get('malware_scan_status') in {'infected', 'error'}]
    clean_approved = [
        d for d in approved
        if d.get('storage_status') == 'clean' and d.get('malware_scan_status') in {'clean', 'waived'}
    ]
    verified = bool(docs and clean_approved and not unsafe)
    return {
        'verified': verified,
        'document_count': len(docs),
        'approved_clean_count': len(clean_approved),
        'unsafe_count': len(unsafe),
        'reason': None if verified else 'Trade documents are missing, not approved/clean, or contain quarantine/scan blockers',
    }


async def _payment_evidence(refs: list[str]) -> dict[str, Any]:
    payments = await _rows_for_refs('trade_payment_ledger', 'source_reference', refs, 20)
    if not payments:
        return {'verified': False, 'reason': 'No linked owner payment-control case; source_reference must link to managed case/request'}
    p = payments[0]
    verified = bool(
        p.get('currency') == 'USD'
        and bool(p.get('payment_allowed'))
        and p.get('payment_status') == 'PAID'
        and float(p.get('outstanding_balance') or 0) == 0
        and bool(p.get('shipment_release_allowed'))
    )
    return {
        'verified': verified,
        'payment_case_id': p.get('payment_case_id'),
        'payment_status': p.get('payment_status'),
        'shipment_release_allowed': bool(p.get('shipment_release_allowed')),
        'supplier_payout_allowed': bool(p.get('supplier_payout_allowed')),
        'reason': None if verified else 'USD payment case is not fully paid and separately owner-authorized for shipment release',
    }


async def _logistics_evidence(case: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    parties_ready = bool(str(case.get('customs_broker') or '').strip() and str(case.get('freight_forwarder') or '').strip())
    shipments = await _rows_for_refs('shipments', 'trade_case_id', refs, 50)
    active = [s for s in shipments if s.get('current_status') not in {'cancelled', 'exception', 'blocked'} and not s.get('exception_code')]
    verified = parties_ready and (not shipments or bool(active))
    return {
        'verified': verified,
        'parties_ready': parties_ready,
        'shipment_count': len(shipments),
        'active_shipment_count': len(active),
        'reason': None if verified else 'Broker/forwarder assignments are incomplete or linked shipment has an exception/cancellation',
    }


async def _delivery_evidence(case: dict[str, Any], refs: list[str]) -> dict[str, Any]:
    shipments = await _rows_for_refs('shipments', 'trade_case_id', refs, 50)
    if case.get('shipment_id'):
        shipments = [s for s in shipments if s.get('shipment_id') == case.get('shipment_id')] or shipments
    delivered = [s for s in shipments if s.get('actual_delivery_at') and not s.get('exception_code')]
    return {
        'verified': bool(delivered),
        'shipment_id': delivered[0].get('shipment_id') if delivered else None,
        'actual_delivery_at': delivered[0].get('actual_delivery_at') if delivered else None,
        'reason': None if delivered else 'No linked shipment has confirmed actual delivery without an exception',
    }


async def _reconciliation_evidence(refs: list[str]) -> dict[str, Any]:
    recs = await _rows_for_refs('payment_reconciliations', 'trade_case_id', refs, 50)
    matched = [r for r in recs if r.get('status') == 'matched' and r.get('matched_journal_id') and r.get('reconciled_at')]
    if not matched:
        return {'verified': False, 'reason': 'No matched payment reconciliation linked to this trade case'}
    journal = await _one('ledger_journals', {'journal_id': f'eq.{matched[0]["matched_journal_id"]}'})
    verified = bool(journal and journal.get('status') == 'posted' and bool(journal.get('owner_approved')) and journal.get('posted_at'))
    return {
        'verified': verified,
        'reconciliation_id': matched[0].get('reconciliation_id'),
        'journal_id': (journal or {}).get('journal_id'),
        'reason': None if verified else 'Matched reconciliation is not backed by an owner-approved posted ledger journal',
    }


async def _milestone_evidence(case_id: str) -> dict[str, Any]:
    rows = await get_backend().select('managed_trade_milestones', params={'managed_case_id': f'eq.{case_id}', 'limit': '100'}) or []
    by = {m.get('milestone_key'): m for m in rows}
    blockers = []
    for key in PRE_RELEASE_KEYS:
        m = by.get(key) or {}
        status = m.get('status')
        if status not in {'PASS', 'NOT_APPLICABLE'}:
            blockers.append(f'{key}: status={status or "MISSING"}')
        elif status == 'NOT_APPLICABLE' and key in NON_WAIVABLE_KEYS:
            blockers.append(f'{key}: NOT_APPLICABLE is prohibited')
        elif not str(m.get('evidence_reference') or '').strip():
            blockers.append(f'{key}: evidence_reference required')
    return {'verified': not blockers, 'blockers': blockers, 'by_key': by}


async def execution_evidence(case: dict[str, Any]) -> dict[str, Any]:
    request = await _request(str(case.get('request_id')))
    supplier = await _selected_supplier(case)
    refs = _trade_refs(case)
    supplier_ok = bool(
        supplier
        and supplier.get('compliance_status') == 'PASS'
        and supplier.get('quality_status') == 'PASS'
        and supplier.get('bank_status') == 'PASS'
        and str(supplier.get('supplier_country') or '').strip()
        and supplier.get('unit_cost') is not None
        and str(supplier.get('incoterm') or '').strip()
        and str(supplier.get('payment_terms') or '').strip()
    )
    corridor = await _corridor_evidence(case, request, supplier)
    compliance = await _compliance_evidence(case, refs)
    documents = await _document_evidence(refs)
    payment = await _payment_evidence(refs)
    logistics = await _logistics_evidence(case, refs)
    milestones = await _milestone_evidence(str(case.get('managed_case_id')))
    checks = {
        'supplier': {'verified': supplier_ok, 'candidate_id': (supplier or {}).get('candidate_id'), 'reason': None if supplier_ok else 'Selected supplier is missing PASS due diligence or commercial terms'},
        'corridor': corridor,
        'compliance': compliance,
        'documents': documents,
        'payment': payment,
        'logistics': logistics,
        'milestones': {'verified': milestones['verified'], 'blockers': milestones['blockers']},
    }
    blockers = [f'{name}: {item.get("reason") or "; ".join(item.get("blockers", []))}' for name, item in checks.items() if not item.get('verified')]
    return {'verified': not blockers, 'trade_references': refs, 'checks': checks, 'blockers': blockers}


async def _set_system_milestone(case_id: str, key: str, actor: dict[str, str], evidence_reference: str, notes: str):
    ts = now()
    await get_backend().patch('managed_trade_milestones', {
        'status': 'PASS', 'evidence_reference': evidence_reference, 'notes': notes,
        'reviewed_by': actor['id'], 'reviewed_at': ts, 'updated_at': ts,
    }, params={'managed_case_id': f'eq.{case_id}', 'milestone_key': f'eq.{key}'})


@app.get('/managed-trade/health')
async def health():
    return {
        'status': 'ok', 'service': 'managed-trade-gateway', 'version': '2.0.0',
        'operator': 'SAHJONY LLC.', 'default_role': 'MANAGED_TRADE_ORCHESTRATOR',
        'fail_closed': True, 'milestones': len(MILESTONES),
        'state_machine': ['OPEN', 'READY_FOR_EXECUTION', 'EXECUTING', 'DELIVERED', 'RECONCILED', 'CLOSED'],
        'system_managed_milestones': sorted(SYSTEM_MANAGED_KEYS),
        'release_revalidates_live_evidence': True,
    }


@app.get('/managed-trade/requests')
async def list_requests(x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    params = {'order': 'updated_at.desc', 'limit': '250'}
    if actor['role'] == 'employee':
        params['assigned_employee_id'] = f'eq.{actor["id"]}'
    return {'requests': await get_backend().select('managed_trade_requests', params=params) or []}


@app.post('/managed-trade/requests')
async def create_request(p: RequestIn, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    if p.currency.upper() != 'USD':
        raise HTTPException(409, 'Managed trade execution currently requires canonical USD settlement')
    rid = f'mtr_{secrets.token_urlsafe(10)}'
    ts = now()
    assigned = actor['id'] if actor['role'] == 'employee' else p.employee_id
    row = {'request_id': rid, **p.model_dump(), 'currency': 'USD', 'destination_country': p.destination_country.upper(), 'status': 'INTAKE', 'assigned_owner_id': 'owner', 'assigned_employee_id': assigned, 'created_at': ts, 'updated_at': ts}
    await get_backend().insert('managed_trade_requests', row)
    await audit(actor, 'request_created', 'Managed trade request entered SAHJONY gateway', rid)
    return {'request': row}


@app.post('/managed-trade/requests/{request_id}/suppliers')
async def add_supplier(request_id: str, p: SupplierCandidateIn, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    await _request(request_id)
    cid = f'msc_{secrets.token_urlsafe(10)}'
    ts = now()
    row = {'candidate_id': cid, 'request_id': request_id, **p.model_dump(), 'supplier_country': (p.supplier_country or '').upper() or None, 'incoterm': (p.incoterm or '').upper() or None, 'compliance_status': 'PENDING', 'quality_status': 'PENDING', 'bank_status': 'PENDING', 'selected': False, 'created_at': ts, 'updated_at': ts}
    await get_backend().insert('managed_supplier_candidates', row)
    await get_backend().patch('managed_trade_requests', {'status': 'SOURCING', 'updated_at': ts}, params={'request_id': f'eq.{request_id}'})
    await audit(actor, 'supplier_candidate_added', f'Supplier candidate {p.supplier_name} added', request_id, payload={'candidate_id': cid})
    return {'supplier_candidate': row}


@app.post('/managed-trade/requests/{request_id}/suppliers/{candidate_id}/select')
async def select_supplier(request_id: str, candidate_id: str, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    if actor['role'] != 'owner':
        raise HTTPException(403, 'Only owner may select the supplier for commitment')
    await _request(request_id)
    c = await _one('managed_supplier_candidates', {'candidate_id': f'eq.{candidate_id}', 'request_id': f'eq.{request_id}'})
    if not c:
        raise HTTPException(404, 'Supplier candidate not found')
    if any(c.get(k) != 'PASS' for k in ('compliance_status', 'quality_status', 'bank_status')):
        raise HTTPException(409, 'Supplier cannot be selected until compliance, quality and bank due diligence pass')
    if not all((str(c.get('supplier_country') or '').strip(), c.get('unit_cost') is not None, str(c.get('incoterm') or '').strip(), str(c.get('payment_terms') or '').strip())):
        raise HTTPException(409, 'Supplier cannot be selected without origin, unit cost, Incoterm and payment terms')
    await get_backend().patch('managed_supplier_candidates', {'selected': False}, params={'request_id': f'eq.{request_id}'})
    await get_backend().patch('managed_supplier_candidates', {'selected': True, 'updated_at': now()}, params={'candidate_id': f'eq.{candidate_id}'})
    await get_backend().patch('managed_trade_requests', {'status': 'SUPPLIER_SHORTLIST', 'updated_at': now()}, params={'request_id': f'eq.{request_id}'})
    active_cases = await get_backend().select('managed_trade_cases', params={'request_id': f'eq.{request_id}', 'limit': '100'}) or []
    for case in active_cases:
        if case.get('status') not in TERMINAL_STATES:
            await get_backend().patch('managed_trade_cases', {'status': 'HOLD', 'release_allowed': False, 'owner_approved': False, 'updated_at': now()}, params={'managed_case_id': f'eq.{case["managed_case_id"]}'})
    await audit(actor, 'supplier_selected', 'Owner selected supplier after due diligence; active execution cases require re-release', request_id, payload={'candidate_id': candidate_id})
    return {'request_id': request_id, 'selected_supplier_candidate_id': candidate_id, 'active_case_release_revoked': True}


@app.post('/managed-trade/cases')
async def create_case(p: CaseIn, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    if actor['role'] != 'owner':
        raise HTTPException(403, 'Only owner may open a managed execution case')
    await _request(p.request_id)
    if p.sahjony_role in {'EXPORTER_OF_RECORD', 'IMPORTER_OF_RECORD', 'PRINCIPAL'} and not (p.exporter_of_record or p.importer_of_record):
        raise HTTPException(409, 'Principal/EOR/IOR role requires explicit legal-party assignment')
    cand = await _one('managed_supplier_candidates', {'candidate_id': f'eq.{p.supplier_candidate_id}', 'request_id': f'eq.{p.request_id}', 'selected': 'eq.true'})
    if not cand:
        raise HTTPException(409, 'Selected supplier candidate for this request is required')
    if any(cand.get(k) != 'PASS' for k in ('compliance_status', 'quality_status', 'bank_status')):
        raise HTTPException(409, 'Selected supplier due diligence is no longer PASS')
    mid = f'mtc_{secrets.token_urlsafe(10)}'
    ts = now()
    row = {'managed_case_id': mid, **p.model_dump(), 'orchestrator_name': 'SAHJONY LLC.', 'status': 'OPEN', 'release_allowed': False, 'owner_approved': False, 'created_at': ts, 'updated_at': ts}
    await get_backend().insert('managed_trade_cases', row)
    ms = [{'milestone_id': f'mtm_{secrets.token_urlsafe(10)}', 'managed_case_id': mid, 'milestone_key': k, 'label': label, 'status': 'PENDING', 'created_at': ts, 'updated_at': ts} for k, label in MILESTONES]
    await get_backend().insert('managed_trade_milestones', ms)
    await audit(actor, 'managed_case_opened', 'SAHJONY LLC. opened governed managed execution case', p.request_id, mid, {'role': p.sahjony_role})
    return {'case': row, 'milestones': ms, 'trade_reference_policy': 'Use managed_case_id/request_id (or linked cuba_trade_case_id) as source_reference/trade_case_id across payment, compliance, documents and shipment records.'}


@app.get('/managed-trade/cases')
async def list_cases(x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    identity(x_role, authorization, x_employee_id)
    return {'cases': await get_backend().select('managed_trade_cases', params={'order': 'updated_at.desc', 'limit': '250'}) or []}


@app.get('/managed-trade/cases/{case_id}/evidence')
async def case_evidence(case_id: str, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    identity(x_role, authorization, x_employee_id)
    case = await _case(case_id)
    evidence = await execution_evidence(case)
    delivery = await _delivery_evidence(case, _trade_refs(case))
    reconciliation = await _reconciliation_evidence(_trade_refs(case))
    return {'managed_case_id': case_id, 'status': case.get('status'), 'release_allowed': bool(case.get('release_allowed')), 'pre_execution': evidence, 'delivery': delivery, 'reconciliation': reconciliation}


@app.patch('/managed-trade/cases/{case_id}/milestones/{key}')
async def milestone(case_id: str, key: str, p: MilestoneIn, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    case = await _case(case_id)
    if case.get('status') in TERMINAL_STATES:
        raise HTTPException(409, 'Terminal managed trade cases cannot be edited')
    if key not in {k for k, _ in MILESTONES}:
        raise HTTPException(404, 'Unknown milestone')
    if key in SYSTEM_MANAGED_KEYS:
        raise HTTPException(409, f'{key} is system-managed and can only be set by its governed transition endpoint')
    if key == 'compliance_release' and actor['role'] != 'owner':
        raise HTTPException(403, 'Only owner may record the compliance-release review milestone')
    if p.status == 'NOT_APPLICABLE':
        if key in NON_WAIVABLE_KEYS:
            raise HTTPException(409, f'{key} cannot be marked NOT_APPLICABLE')
        if actor['role'] != 'owner' or not p.evidence_reference or not p.notes:
            raise HTTPException(409, 'NOT_APPLICABLE requires owner review, evidence_reference and rationale')
    if p.status == 'PASS' and not str(p.evidence_reference or '').strip():
        raise HTTPException(409, 'PASS requires evidence_reference')
    ts = now()
    await get_backend().patch('managed_trade_milestones', {'status': p.status, 'evidence_reference': p.evidence_reference, 'notes': p.notes, 'reviewed_by': actor['id'], 'reviewed_at': ts, 'updated_at': ts}, params={'managed_case_id': f'eq.{case_id}', 'milestone_key': f'eq.{key}'})
    revoke = p.status == 'FAIL' or (key in PRE_RELEASE_KEYS and case.get('status') in ACTIVE_RELEASE_STATES)
    if revoke:
        await get_backend().patch('managed_trade_cases', {'status': 'HOLD', 'release_allowed': False, 'owner_approved': False, 'updated_at': ts}, params={'managed_case_id': f'eq.{case_id}'})
    await audit(actor, 'milestone_reviewed', f'{key} -> {p.status}', case_id=case_id, payload={'release_revoked': revoke})
    return {'managed_case_id': case_id, 'milestone_key': key, 'status': p.status, 'release_revoked': revoke}


@app.post('/managed-trade/cases/{case_id}/release')
async def release(case_id: str, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    if actor['role'] != 'owner':
        raise HTTPException(403, 'Only owner may release a managed trade case')
    case = await _case(case_id)
    if case.get('status') in TERMINAL_STATES:
        raise HTTPException(409, 'Terminal managed trade case cannot be released')
    evidence = await execution_evidence(case)
    if not evidence['verified']:
        raise HTTPException(409, {'message': 'Managed trade release blocked by live evidence', 'blockers': evidence['blockers']})
    ts = now()
    await _set_system_milestone(case_id, 'owner_release', actor, f'owner-release:{ts}', 'Owner release generated only after all live pre-execution evidence passed.')
    await get_backend().patch('managed_trade_cases', {'status': 'READY_FOR_EXECUTION', 'release_allowed': True, 'owner_approved': True, 'updated_at': ts}, params={'managed_case_id': f'eq.{case_id}'})
    await audit(actor, 'managed_case_released', 'Owner released managed trade case after live evidence revalidation', request_id=case.get('request_id'), case_id=case_id, payload={'trade_references': evidence['trade_references']})
    return {'managed_case_id': case_id, 'status': 'READY_FOR_EXECUTION', 'release_allowed': True, 'evidence': evidence}


@app.post('/managed-trade/cases/{case_id}/execute')
async def execute(case_id: str, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    if actor['role'] != 'owner':
        raise HTTPException(403, 'Only owner may start governed trade execution')
    case = await _case(case_id)
    if case.get('status') != 'READY_FOR_EXECUTION' or not case.get('release_allowed') or not case.get('owner_approved'):
        raise HTTPException(409, 'Case must be READY_FOR_EXECUTION with current owner release')
    evidence = await execution_evidence(case)
    if not evidence['verified']:
        await get_backend().patch('managed_trade_cases', {'status': 'HOLD', 'release_allowed': False, 'owner_approved': False, 'updated_at': now()}, params={'managed_case_id': f'eq.{case_id}'})
        raise HTTPException(409, {'message': 'Execution evidence changed after release; case moved to HOLD', 'blockers': evidence['blockers']})
    ts = now()
    await get_backend().patch('managed_trade_cases', {'status': 'EXECUTING', 'updated_at': ts}, params={'managed_case_id': f'eq.{case_id}'})
    await get_backend().patch('managed_trade_requests', {'status': 'EXECUTION', 'updated_at': ts}, params={'request_id': f'eq.{case.get("request_id")}'})
    await audit(actor, 'execution_started', 'Governed execution started after second live-evidence check', request_id=case.get('request_id'), case_id=case_id)
    return {'managed_case_id': case_id, 'status': 'EXECUTING', 'release_allowed': True}


@app.post('/managed-trade/cases/{case_id}/delivered')
async def delivered(case_id: str, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    case = await _case(case_id)
    if case.get('status') != 'EXECUTING':
        raise HTTPException(409, 'Delivery can only be confirmed from EXECUTING state')
    evidence = await _delivery_evidence(case, _trade_refs(case))
    if not evidence['verified']:
        raise HTTPException(409, evidence['reason'])
    ts = now()
    await _set_system_milestone(case_id, 'delivery', actor, f'shipment:{evidence["shipment_id"]}', f'Actual delivery confirmed at {evidence["actual_delivery_at"]}.')
    await get_backend().patch('managed_trade_cases', {'status': 'DELIVERED', 'shipment_id': evidence['shipment_id'], 'updated_at': ts}, params={'managed_case_id': f'eq.{case_id}'})
    await audit(actor, 'delivery_confirmed', 'Delivery state derived from shipment actual_delivery_at', request_id=case.get('request_id'), case_id=case_id, payload=evidence)
    return {'managed_case_id': case_id, 'status': 'DELIVERED', 'delivery': evidence}


@app.post('/managed-trade/cases/{case_id}/reconcile')
async def reconcile_case(case_id: str, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    if actor['role'] != 'owner':
        raise HTTPException(403, 'Only owner may certify final trade reconciliation')
    case = await _case(case_id)
    if case.get('status') != 'DELIVERED':
        raise HTTPException(409, 'Reconciliation can only be certified after DELIVERED')
    evidence = await _reconciliation_evidence(_trade_refs(case))
    if not evidence['verified']:
        raise HTTPException(409, evidence['reason'])
    ts = now()
    await _set_system_milestone(case_id, 'reconciliation', actor, f'reconciliation:{evidence["reconciliation_id"]}', f'Owner-approved posted journal {evidence["journal_id"]} backs final matched reconciliation.')
    await get_backend().patch('managed_trade_cases', {'status': 'RECONCILED', 'updated_at': ts}, params={'managed_case_id': f'eq.{case_id}'})
    await audit(actor, 'trade_reconciled', 'Final financial reconciliation verified against posted owner-approved ledger journal', request_id=case.get('request_id'), case_id=case_id, payload=evidence)
    return {'managed_case_id': case_id, 'status': 'RECONCILED', 'reconciliation': evidence}


@app.post('/managed-trade/cases/{case_id}/close')
async def close_case(case_id: str, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization'), x_employee_id: str | None = Header(None, alias='X-Employee-Id')):
    actor = identity(x_role, authorization, x_employee_id)
    if actor['role'] != 'owner':
        raise HTTPException(403, 'Only owner may close a managed trade case')
    case = await _case(case_id)
    if case.get('status') != 'RECONCILED':
        raise HTTPException(409, 'Case must be RECONCILED before CLOSED')
    delivery_ev = await _delivery_evidence(case, _trade_refs(case))
    reconciliation_ev = await _reconciliation_evidence(_trade_refs(case))
    if not delivery_ev['verified'] or not reconciliation_ev['verified']:
        raise HTTPException(409, {'message': 'Close blocked because delivery/reconciliation evidence no longer verifies', 'delivery': delivery_ev, 'reconciliation': reconciliation_ev})
    milestones = await get_backend().select('managed_trade_milestones', params={'managed_case_id': f'eq.{case_id}', 'limit': '100'}) or []
    by = {m.get('milestone_key'): m.get('status') for m in milestones}
    missing = [key for key, _ in MILESTONES if by.get(key) not in {'PASS', 'NOT_APPLICABLE'}]
    if missing:
        raise HTTPException(409, 'Close blocked by incomplete milestones: ' + ', '.join(missing))
    ts = now()
    await get_backend().patch('managed_trade_cases', {'status': 'CLOSED', 'release_allowed': False, 'updated_at': ts}, params={'managed_case_id': f'eq.{case_id}'})
    await get_backend().patch('managed_trade_requests', {'status': 'CLOSED', 'updated_at': ts}, params={'request_id': f'eq.{case.get("request_id")}'})
    await audit(actor, 'managed_case_closed', 'Managed trade case closed only after delivery and owner-certified financial reconciliation', request_id=case.get('request_id'), case_id=case_id)
    return {'managed_case_id': case_id, 'status': 'CLOSED', 'release_allowed': False, 'delivery_verified': True, 'reconciliation_verified': True}
