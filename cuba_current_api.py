from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Current Cuba Jurisdiction', version='1.0.0', docs_url=None, redoc_url=None)

CUBA_CODE = 'CU'
CUBA_NAME = 'Cuba'
AS_OF = '2026-08-22'

CONTROLS = [
    ('legal_entity_trading_eligibility','LIMITED','Real Cuba trade is subject to current U.S. sanctions and other applicable laws; eligibility must be determined per transaction.'),
    ('importer_exporter_registration','LIMITED','Importer/exporter registration and licensing requirements depend on transaction structure and applicable authority.'),
    ('customs_broker_coverage','LIMITED','Broker coverage must be verified for the specific lawful transaction and route.'),
    ('sanctions_export_controls','LIMITED','OFAC Cuba sanctions remain active; BIS Part 746 imposes broad Cuba licensing requirements.'),
    ('product_restrictions','LIMITED','Products must be screened for EAR/other agency restrictions and any required license or authorization.'),
    ('tax_vat_gst','LIMITED','Tax and duty treatment must be verified for the specific transaction and jurisdictions involved.'),
    ('banking_settlement','LIMITED','Payment path must be supported by participating financial institutions and comply with applicable sanctions rules.'),
    ('currency_support','LIMITED','Currency support depends on lawful banking and settlement availability.'),
    ('freight_carrier_coverage','LIMITED','Carrier availability and sanctions/compliance acceptance must be verified per shipment.'),
    ('cargo_liability_insurance','LIMITED','Insurance availability and exclusions must be verified per shipment.'),
    ('document_requirements','LIMITED','Required customs, export-control, commercial and transport documents must be verified per transaction.'),
    ('translation_language','READY','Spanish-language operating support is available in the platform.'),
    ('local_contracts','LIMITED','Contract enforceability and applicable restrictions must be reviewed for the transaction.'),
    ('warehouse_3pl','LIMITED','Warehouse/3PL coverage must be verified for the lawful route and product.'),
    ('data_privacy','LIMITED','Applicable privacy/data rules must be verified for parties and systems involved.'),
    ('accounting_reconciliation','LIMITED','Transaction accounting must retain sanctions, customs, payment and landed-cost evidence.'),
]


def now():
    return datetime.now(timezone.utc).isoformat()


def owner(authorization: str | None):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    token = authorization.removeprefix('Bearer ').strip()
    if not verify_owner_token(token):
        raise HTTPException(403, 'Invalid owner credential')
    return {'role':'owner','id':'owner'}


@app.get('/cuba/health')
async def health():
    return {
        'status':'ok',
        'country_code':'CU',
        'mode':'LIVE',
        'operating_status':'LIMITED',
        'legal_snapshot_as_of':AS_OF,
        'fail_closed':True,
    }


@app.post('/cuba/current/activate')
async def activate_current_cuba(authorization: str | None = Header(None, alias='Authorization')):
    actor = owner(authorization)
    backend = get_backend()
    existing = await backend.select('country_activation_profiles', params={'country_code':'eq.CU','limit':'1'}) or []
    ts = now()
    profile = {
        'country_code':CUBA_CODE,
        'country_name':CUBA_NAME,
        'region':'Caribbean',
        'operating_status':'LIMITED',
        'scenario_mode':'LIVE',
        'live_execution_allowed':True,
        'scenario_label':None,
        'default_currency':'CUP',
        'default_locale':'es-CU',
        'notes':'Real Cuba current-law profile. Lawful trade only. No sanctions, export-control, customs, banking, or licensing override is created by this profile.',
        'owner_approved':True,
        'approved_by':actor['id'],
        'approved_at':ts,
        'updated_at':ts,
    }
    if existing:
        await backend.patch('country_activation_profiles', profile, params={'country_code':'eq.CU'})
    else:
        profile['created_at'] = ts
        await backend.insert('country_activation_profiles', profile)

    existing_controls = await backend.select('country_activation_controls', params={'country_code':'eq.CU','limit':'100'}) or []
    by_key = {r.get('control_key'): r for r in existing_controls}
    controls = []
    for key, status, summary in CONTROLS:
        values = {
            'status':status,
            'evidence_summary':summary,
            'evidence_source':'Official U.S. government regulatory baseline',
            'reviewed_by_role':'owner',
            'reviewed_by_id':actor['id'],
            'reviewed_at':ts,
            'updated_at':ts,
        }
        if key in by_key:
            await backend.patch('country_activation_controls', values, params={'country_code':'eq.CU','control_key':f'eq.{key}'})
            row = {**by_key[key], **values}
        else:
            row = {
                'control_id':f'cac_{secrets.token_urlsafe(12)}',
                'country_code':'CU',
                'control_key':key,
                'control_label':key.replace('_',' ').title(),
                **values,
                'created_at':ts,
            }
            await backend.insert('country_activation_controls', row)
        controls.append(row)

    snapshots = [
        ('OFAC','https://ofac.treasury.gov/sanctions-programs-and-country-information/cuba-sanctions','Cuba sanctions program remains in force under the Cuban Assets Control Regulations, 31 CFR Part 515.'),
        ('BIS','https://www.bis.gov/regulations/ear/746','EAR Part 746 maintains broad licensing requirements for exports/reexports to Cuba, including all CCL items and most EAR99 items.'),
        ('OFAC','https://ofac.treasury.gov/recent-actions/20260806','OFAC issued Cuba-related designations on 2026-08-06; current screening must use live sanctions data.'),
    ]
    for authority, ref, summary in snapshots:
        sid = f'cu_{AS_OF.replace("-","")}_{authority.lower()}_{secrets.token_hex(3)}'
        await backend.insert('cuba_current_compliance_snapshot', {
            'snapshot_id':sid,
            'as_of_date':AS_OF,
            'authority':authority,
            'authority_reference':ref,
            'summary':summary,
            'created_at':ts,
        })

    return {
        'country':profile,
        'controls':controls,
        'real_jurisdiction':True,
        'mode':'LIVE',
        'operating_status':'LIMITED',
        'legal_snapshot_as_of':AS_OF,
        'live_execution_policy':'Lawful transactions only; per-transaction compliance gates still apply.',
    }
