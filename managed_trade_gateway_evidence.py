from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row


_REQUIRED_TABLES = {
    'managed_trade_requests',
    'managed_supplier_candidates',
    'managed_trade_cases',
    'managed_trade_milestones',
    'trade_corridor_activations',
    'country_activation_profiles',
    'trade_compliance_cases',
    'trade_documents',
    'trade_payment_ledger',
    'shipments',
    'payment_reconciliations',
    'ledger_journals',
}

_MILESTONE_KEYS = {
    'request_qualified', 'private_business_eligible', 'supplier_sourced',
    'supplier_due_diligence', 'product_classified', 'authorization_matched',
    'commercial_terms', 'payment_path', 'documents_ready', 'logistics_ready',
    'compliance_release', 'owner_release', 'delivery', 'reconciliation',
}

_NON_WAIVABLE = _MILESTONE_KEYS - {'private_business_eligible', 'authorization_matched'}
_ACTIVE_RELEASE_STATES = {'READY_FOR_EXECUTION', 'EXECUTING', 'DELIVERED', 'RECONCILED'}


def _database_url() -> str:
    for name in ('DATABASE_URL', 'POSTGRES_URL', 'NEON_DATABASE_URL', 'NEON_POSTGRES_URL', 'POSTGRES_PRISMA_URL'):
        value = os.getenv(name, '').strip()
        if value:
            return value
    raise RuntimeError('Production database URL is not configured')


def _refs(case: dict[str, Any]) -> list[str]:
    values = [case.get('cuba_trade_case_id'), case.get('managed_case_id'), case.get('request_id')]
    result: list[str] = []
    for value in values:
        if value and str(value) not in result:
            result.append(str(value))
    return result


def _first_by_refs(rows: list[dict[str, Any]], field: str, refs: list[str]) -> dict[str, Any] | None:
    for ref in refs:
        for row in rows:
            if str(row.get(field) or '') == ref:
                return row
    return None


def _all_by_refs(rows: list[dict[str, Any]], field: str, refs: list[str]) -> list[dict[str, Any]]:
    wanted = set(refs)
    return [row for row in rows if str(row.get(field) or '') in wanted]


def _country_profile_ok(profile: dict[str, Any] | None) -> bool:
    return bool(
        profile
        and str(profile.get('scenario_mode') or 'LIVE').upper() == 'LIVE'
        and str(profile.get('operating_status') or 'BLOCKED').upper() == 'READY'
        and profile.get('owner_approved') is True
        and profile.get('live_execution_allowed') is True
    )


def _case_evidence(case: dict[str, Any], data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    case_id = str(case.get('managed_case_id') or '')
    request_id = str(case.get('request_id') or '')
    refs = _refs(case)
    blockers: list[str] = []

    request = next((r for r in data['managed_trade_requests'] if str(r.get('request_id') or '') == request_id), None)
    if not request:
        blockers.append('request_missing')

    candidate_id = str(case.get('supplier_candidate_id') or '')
    supplier = next((r for r in data['managed_supplier_candidates'] if str(r.get('candidate_id') or '') == candidate_id and str(r.get('request_id') or '') == request_id), None)
    supplier_ok = bool(
        supplier and supplier.get('selected') is True
        and all(supplier.get(k) == 'PASS' for k in ('compliance_status', 'quality_status', 'bank_status'))
        and str(supplier.get('supplier_country') or '').strip()
        and supplier.get('unit_cost') is not None
        and str(supplier.get('incoterm') or '').strip()
        and str(supplier.get('payment_terms') or '').strip()
    )
    if not supplier_ok:
        blockers.append('selected_supplier_invalid')

    origin = str((supplier or {}).get('supplier_country') or '').upper()
    destination = str((request or {}).get('destination_country') or '').upper()
    corridor = next((r for r in data['trade_corridor_activations'] if str(r.get('origin_country_code') or '').upper() == origin and str(r.get('destination_country_code') or '').upper() == destination), None)
    profiles = {str(r.get('country_code') or '').upper(): r for r in data['country_activation_profiles']}
    corridor_ok = bool(
        corridor and corridor.get('status') == 'READY' and corridor.get('execution_mode') == 'LIVE'
        and corridor.get('owner_approved') is True
        and all(bool(corridor.get(k)) for k in ('carrier_coverage', 'broker_coverage', 'banking_coverage', 'insurance_coverage', 'tax_model_verified'))
        and _country_profile_ok(profiles.get(origin)) and _country_profile_ok(profiles.get(destination))
    )
    if not corridor_ok:
        blockers.append('country_corridor_not_governed')

    compliance = None
    if case.get('compliance_case_id'):
        compliance = next((r for r in data['trade_compliance_cases'] if r.get('compliance_id') == case.get('compliance_case_id')), None)
    if not compliance:
        compliance = _first_by_refs(data['trade_compliance_cases'], 'trade_case_id', refs)
    compliance_ok = bool(
        compliance and compliance.get('sanctions_status') == 'clear'
        and compliance.get('export_control_status') in {'nrl', 'licensed'}
        and compliance.get('customs_status') in {'ready', 'filed', 'released'}
        and compliance.get('agency_status') in {'not_applicable', 'ready', 'approved'}
        and compliance.get('legal_status') in {'ready', 'approved'}
        and compliance.get('release_status') in {'ready', 'released'}
    )
    if not compliance_ok:
        blockers.append('compliance_not_released')

    docs = _all_by_refs(data['trade_documents'], 'trade_case_id', refs)
    clean_approved = [d for d in docs if d.get('status') in {'approved', 'released'} and d.get('storage_status') == 'clean' and d.get('malware_scan_status') in {'clean', 'waived'}]
    unsafe_docs = [d for d in docs if d.get('storage_status') in {'quarantined', 'rejected'} or d.get('malware_scan_status') in {'infected', 'error'}]
    documents_ok = bool(docs and clean_approved and not unsafe_docs)
    if not documents_ok:
        blockers.append('documents_not_clean_approved')

    payment = _first_by_refs(data['trade_payment_ledger'], 'source_reference', refs)
    payment_ok = bool(
        payment and payment.get('currency') == 'USD' and payment.get('payment_allowed') is True
        and payment.get('payment_status') == 'PAID'
        and float(payment.get('outstanding_balance') or 0) == 0
        and payment.get('shipment_release_allowed') is True
    )
    if not payment_ok:
        blockers.append('payment_not_fully_released')

    logistics_parties_ok = bool(str(case.get('customs_broker') or '').strip() and str(case.get('freight_forwarder') or '').strip())
    if not logistics_parties_ok:
        blockers.append('logistics_parties_missing')

    shipments = _all_by_refs(data['shipments'], 'trade_case_id', refs)
    delivered_shipments = [s for s in shipments if s.get('actual_delivery_at') and not s.get('exception_code')]
    delivery_ok = bool(delivered_shipments)

    reconciliations = _all_by_refs(data['payment_reconciliations'], 'trade_case_id', refs)
    matched = next((r for r in reconciliations if r.get('status') == 'matched' and r.get('matched_journal_id') and r.get('reconciled_at')), None)
    journal = next((j for j in data['ledger_journals'] if matched and j.get('journal_id') == matched.get('matched_journal_id')), None)
    reconciliation_ok = bool(journal and journal.get('status') == 'posted' and journal.get('owner_approved') is True and journal.get('posted_at'))

    milestones = [m for m in data['managed_trade_milestones'] if str(m.get('managed_case_id') or '') == case_id]
    by_key = {str(m.get('milestone_key') or ''): m for m in milestones}
    milestone_blockers: list[str] = []
    for key in _MILESTONE_KEYS:
        row = by_key.get(key) or {}
        status = row.get('status')
        if status not in {'PASS', 'NOT_APPLICABLE'}:
            milestone_blockers.append(f'{key}:incomplete')
        elif key in _NON_WAIVABLE and status != 'PASS':
            milestone_blockers.append(f'{key}:non_waivable')
        elif not str(row.get('evidence_reference') or '').strip():
            milestone_blockers.append(f'{key}:missing_evidence')
    if milestone_blockers:
        blockers.append('milestones_incomplete')

    state = str(case.get('status') or 'OPEN')
    if state in _ACTIVE_RELEASE_STATES and not (case.get('release_allowed') is True and case.get('owner_approved') is True):
        blockers.append('active_state_without_owner_release')
    if state == 'HOLD' and case.get('release_allowed') is True:
        blockers.append('hold_case_still_released')
    if state == 'CLOSED':
        if case.get('release_allowed') is True:
            blockers.append('closed_case_still_released')
        if not delivery_ok:
            blockers.append('closed_without_delivery')
        if not reconciliation_ok:
            blockers.append('closed_without_reconciliation')

    pre_execution_ok = bool(supplier_ok and corridor_ok and compliance_ok and documents_ok and payment_ok and logistics_parties_ok)
    fully_closed_valid = bool(state == 'CLOSED' and pre_execution_ok and delivery_ok and reconciliation_ok and not milestone_blockers and not blockers)

    return {
        'managed_case_id': case_id,
        'status': state,
        'pre_execution_verified': pre_execution_ok,
        'delivery_verified': delivery_ok,
        'reconciliation_verified': reconciliation_ok,
        'milestone_blockers': milestone_blockers,
        'blockers': blockers,
        'fully_closed_valid': fully_closed_valid,
    }


def _probe() -> dict[str, Any]:
    with psycopg.connect(_database_url(), connect_timeout=10, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            present: set[str] = set()
            for table in sorted(_REQUIRED_TABLES):
                cur.execute('SELECT to_regclass(%s) AS relation', (f'public.{table}',))
                row = cur.fetchone()
                if row and row['relation'] is not None:
                    present.add(table)
            missing = sorted(_REQUIRED_TABLES - present)
            if missing:
                return {
                    'verified': False,
                    'provider': 'neon_postgres',
                    'canonical_database': 'active_vercel_database_url',
                    'required_table_count': len(_REQUIRED_TABLES),
                    'present_table_count': len(present),
                    'missing_tables': missing,
                    'managed_case_count': 0,
                    'valid_closed_case_count': 0,
                    'reason': 'Managed trade gateway evidence schema is incomplete',
                    'fail_closed': True,
                }
            data: dict[str, list[dict[str, Any]]] = {}
            for table in sorted(_REQUIRED_TABLES):
                cur.execute(f'SELECT * FROM public.{table}')
                data[table] = [dict(row) for row in cur.fetchall()]

    cases = [_case_evidence(case, data) for case in data['managed_trade_cases']]
    invalid_active = [c['managed_case_id'] for c in cases if c['status'] in _ACTIVE_RELEASE_STATES and c['blockers']]
    invalid_closed = [c['managed_case_id'] for c in cases if c['status'] == 'CLOSED' and not c['fully_closed_valid']]
    valid_closed = [c['managed_case_id'] for c in cases if c['fully_closed_valid']]
    verified = bool(valid_closed and not invalid_active and not invalid_closed)
    return {
        'verified': verified,
        'provider': 'neon_postgres',
        'canonical_database': 'active_vercel_database_url',
        'required_table_count': len(_REQUIRED_TABLES),
        'present_table_count': len(_REQUIRED_TABLES),
        'missing_tables': [],
        'managed_case_count': len(cases),
        'valid_closed_case_count': len(valid_closed),
        'valid_closed_case_ids': valid_closed[:20],
        'invalid_active_case_ids': invalid_active[:20],
        'invalid_closed_case_ids': invalid_closed[:20],
        'reason': None if verified else 'No fully governed CLOSED managed trade case, or active/closed cases violate the state machine',
        'fail_closed': True,
    }


def managed_trade_gateway_evidence() -> dict[str, Any]:
    try:
        return _probe()
    except Exception as exc:
        detail = str(exc).strip().splitlines()[0][:240] if str(exc).strip() else 'unknown database error'
        return {
            'verified': False,
            'provider': 'neon_postgres',
            'canonical_database': 'active_vercel_database_url',
            'managed_case_count': 0,
            'valid_closed_case_count': 0,
            'reason': f'{type(exc).__name__}: {detail}',
            'fail_closed': True,
        }
