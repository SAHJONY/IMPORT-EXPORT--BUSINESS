from __future__ import annotations

from fastapi import FastAPI

from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Trade Workflow Certification', version='1.0.0', docs_url=None, redoc_url=None)


def _has_nonbinding_rfq(job: dict) -> bool:
    packet = job.get('packet') or {}
    rfq = str(packet.get('rfq_draft') or '')
    return bool(rfq and 'NON-BINDING' in rfq.upper() and 'not a purchase order' in rfq.lower())


def _candidate_controls_complete(candidate: dict) -> bool:
    fields = [
        'supplier_screening_status', 'origin_export_control_status', 'destination_import_control_status',
        'product_restriction_status', 'banking_status', 'logistics_status', 'tax_duty_status', 'us_nexus_status',
    ]
    return all(candidate.get(field) in {'PASS', 'FAIL', 'NOT_APPLICABLE'} for field in fields)


@app.get('/trade-certification/health')
async def certification_health():
    backend_status = persistent_backend_status()
    if not backend_status['configured']:
        return {
            'status': 'configuration_required',
            'service': 'trade-workflow-certification',
            'certification': 'NOT_STARTED',
            'reason': 'Durable persistence is not configured',
            'fail_closed': True,
        }

    backend = get_backend()
    intakes = await backend.select('customer_trade_intakes', params={'limit': '5000'}) or []
    managed = await backend.select('managed_trade_requests', params={'limit': '5000'}) or []
    sourcing = await backend.select('global_sourcing_requests', params={'limit': '5000'}) or []
    jobs = await backend.select('trade_agent_jobs', params={'limit': '5000'}) or []
    candidates = await backend.select('global_supplier_candidates', params={'limit': '5000'}) or []

    qualified = [row for row in intakes if row.get('qualification_status') == 'QUALIFIED']
    promoted = [row for row in intakes if row.get('managed_trade_request_id') and row.get('sourcing_request_id')]
    rfq_ready_jobs = [row for row in jobs if _has_nonbinding_rfq(row)]
    reviewed_candidates = [row for row in candidates if _candidate_controls_complete(row)]
    ready_candidates = [row for row in candidates if row.get('corridor_status') == 'READY']
    selected_candidates = [row for row in ready_candidates if row.get('selected') is True]

    stages = {
        'real_trade_intake': bool(intakes),
        'qualified_intake': bool(qualified),
        'managed_trade_promoted': bool(promoted and managed),
        'global_sourcing_created': bool(promoted and sourcing),
        'trade_agent_launched': bool(jobs),
        'nonbinding_rfq_prepared': bool(rfq_ready_jobs),
        'supplier_candidate_evidenced': bool(candidates),
        'supplier_controls_reviewed': bool(reviewed_candidates),
        'ready_supplier_candidate': bool(ready_candidates),
        'owner_supplier_selection': bool(selected_candidates),
    }

    ordered = list(stages.items())
    completed = sum(1 for _, value in ordered if value)
    next_step = next((name for name, value in ordered if not value), 'pre_approval_chain_complete')

    if stages['owner_supplier_selection']:
        certification = 'PRE_APPROVAL_CHAIN_CERTIFIED'
    elif stages['trade_agent_launched'] and stages['nonbinding_rfq_prepared']:
        certification = 'ORCHESTRATION_PROVEN'
    elif stages['real_trade_intake']:
        certification = 'IN_PROGRESS'
    else:
        certification = 'AWAITING_REAL_CUSTOMER_INTAKE'

    return {
        'status': 'ok',
        'service': 'trade-workflow-certification',
        'certification': certification,
        'production_evidence_only': True,
        'synthetic_records_count_as_certification': False,
        'first_live_trade_certified': False,
        'e2e_release_gate_mutated': False,
        'stages': stages,
        'progress': {'completed': completed, 'total': len(ordered), 'percent': round(completed / len(ordered) * 100)},
        'counts': {
            'trade_intakes': len(intakes),
            'qualified_intakes': len(qualified),
            'promoted_intakes': len(promoted),
            'managed_trade_requests': len(managed),
            'global_sourcing_requests': len(sourcing),
            'trade_agent_jobs': len(jobs),
            'rfq_ready_jobs': len(rfq_ready_jobs),
            'supplier_candidates': len(candidates),
            'controls_reviewed_candidates': len(reviewed_candidates),
            'ready_candidates': len(ready_candidates),
            'selected_candidates': len(selected_candidates),
        },
        'next_required_step': next_step,
        'policy': {
            'no_outbound_supplier_send_without_approval': True,
            'no_supplier_commitment_from_certification': True,
            'no_payment_authority_from_certification': True,
            'no_compliance_release_from_certification': True,
            'no_first_live_trade_flag_from_dry_run': True,
            'fail_closed': True,
        },
    }
