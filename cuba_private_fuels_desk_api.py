from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Cuba Private Sector Fuels Desk', version='1.1.0', docs_url=None, redoc_url=None)

FuelType = Literal['GASOLINE','DIESEL','KEROSENE','JET_FUEL','FUEL_OIL','LPG','LUBRICANTS','CRUDE_OIL','OTHER_PETROLEUM']
EndUserType = Literal['INDEPENDENT_PRIVATE_BUSINESS','INDIVIDUAL_CONSUMER','OTHER']
PaymentRail = Literal['THIRD_COUNTRY_BANK','NON_CUBAN_BANK','OTHER_NON_CUBAN_PAYMENT_SYSTEM','CUBAN_OWNED_BANK','UNDETERMINED']
GateStatus = Literal['PASS','FAIL','PENDING','NOT_APPLICABLE']
ConsumerStatus = Literal['PROSPECT','ACTIVE','HOLD','DO_NOT_CONTACT']

REQUIRED_GATES = [
    'private_sector_or_consumer_eligibility',
    'ear_classification_and_scp_eligibility',
    'restricted_party_and_ownership_screening',
    'private_sector_end_use',
    'payment_path_no_cuban_owned_bank_deposit',
    'carrier_forwarder_acceptance',
    'commercial_documents_and_recordkeeping',
    'cuba_trade_case_authorization',
]

AUTHORITY_NOTES = {
    'bis': 'BIS Cuba guidance states certain U.S.-origin gas and petroleum exports to eligible Cuban private-sector entities and individual Cuban consumers may use License Exception SCP when all conditions in 15 CFR 740.21 are met.',
    'individual_consumers': 'For the SCP individual-consumer pathway, the gas or petroleum product must be sold directly to the Cuban individual for the individual or immediate family personal use; prohibited or otherwise ineligible purchasers/end users are not eligible.',
    'ofac': 'OFAC FAQ 1238 states transactions ordinarily incident to Commerce-authorized exports of U.S.-origin oil, gas and petroleum products are generally authorized under 31 CFR 515.533(a), including qualifying SCP exports.',
    'banking_2026': 'BIS guidance updated March 4, 2026 suspends SCP for transactions involving deposit of foreign funds into a Cuban-owned bank; qualifying transactions using third-country banks or other payment systems that do not involve such deposits may proceed to transaction-specific review.',
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def owner(auth: str | None) -> None:
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()):
        raise HTTPException(403, 'Invalid or expired owner session')


class ConsumerIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=240)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=180)
    municipality: str | None = Field(default=None, max_length=180)
    delivery_address: str | None = Field(default=None, max_length=600)
    preferred_language: Literal['ES','EN'] = 'ES'
    household_size: int | None = Field(default=None, ge=1, le=50)
    intended_personal_use: str | None = Field(default=None, max_length=1500)
    source_reference: str | None = Field(default=None, max_length=1500)
    notes: str | None = Field(default=None, max_length=4000)


class ConsumerStatusIn(BaseModel):
    status: ConsumerStatus
    note: str | None = Field(default=None, max_length=3000)


class FuelCaseIn(BaseModel):
    fuel_type: FuelType
    product_description: str = Field(min_length=3, max_length=1200)
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=40)
    cuban_buyer_name: str = Field(min_length=2, max_length=300)
    customer_id: str | None = Field(default=None, max_length=180)
    private_business_id: str | None = Field(default=None, max_length=180)
    end_user_type: EndUserType = 'INDEPENDENT_PRIVATE_BUSINESS'
    end_user_name: str = Field(min_length=2, max_length=300)
    end_use: str = Field(min_length=3, max_length=1500)
    direct_sale_to_individual: bool = False
    personal_or_immediate_family_use: bool = False
    province: str | None = Field(default=None, max_length=180)
    municipality: str | None = Field(default=None, max_length=180)
    supplier_name: str | None = Field(default=None, max_length=300)
    supplier_country: str = 'US'
    us_origin: bool = True
    classification: str | None = Field(default=None, max_length=120)
    ear99: bool | None = None
    controlled_only_at: bool | None = None
    payment_rail: PaymentRail = 'UNDETERMINED'
    estimated_value: float | None = Field(default=None, ge=0)
    currency: str = Field(default='USD', min_length=3, max_length=12)
    source_reference: str | None = Field(default=None, max_length=1500)
    notes: str | None = Field(default=None, max_length=5000)


class GateIn(BaseModel):
    gate: str
    status: GateStatus
    evidence_reference: str | None = Field(default=None, max_length=1500)
    evidence_summary: str | None = Field(default=None, max_length=4000)


class LinkIn(BaseModel):
    cuba_trade_case_id: str = Field(min_length=3, max_length=180)
    cuba_energy_opportunity_id: str | None = Field(default=None, max_length=180)


async def get_case(case_id: str) -> dict:
    rows = await get_backend().select('cuba_private_fuel_cases', params={'fuel_case_id':f'eq.{case_id}','limit':'1'}) or []
    if not rows:
        raise HTTPException(404, 'Cuba private-sector fuel case not found')
    return rows[0]


async def get_consumer(customer_id: str) -> dict:
    rows = await get_backend().select('customer_accounts', params={'customer_id':f'eq.{customer_id}','limit':'1'}) or []
    if not rows or rows[0].get('customer_type') != 'INDIVIDUAL_CONSUMER' or rows[0].get('country_code') != 'CU':
        raise HTTPException(404, 'Cuban individual consumer customer not found')
    return rows[0]


async def gate_state(case_id: str) -> dict[str, str]:
    rows = await get_backend().select('cuba_private_fuel_gates', params={'fuel_case_id':f'eq.{case_id}','order':'updated_at.desc','limit':'500'}) or []
    out: dict[str, str] = {}
    for row in rows:
        key = str(row.get('gate') or '')
        if key and key not in out:
            out[key] = str(row.get('status') or 'PENDING')
    return out


@app.get('/cuba-fuels/health')
async def health():
    p = persistent_backend_status()
    return {
        'status':'ok' if p['configured'] else 'configuration_required',
        'service':'sahjony-cuba-private-sector-fuels-desk',
        'version':'1.1.0',
        'country':'CU',
        'us_origin_gas_petroleum_scp_workflow':True,
        'individual_consumer_customer_crm':True,
        'individual_consumer_direct_sale_control':True,
        'individual_consumer_personal_family_use_control':True,
        'supported_fuels':['GASOLINE','DIESEL','KEROSENE','JET_FUEL','FUEL_OIL','LPG','LUBRICANTS','CRUDE_OIL','OTHER_PETROLEUM'],
        'default_status':'HOLD',
        'cuban_owned_bank_scp_path_allowed':False,
        'transaction_specific_eligibility_required':True,
        'automatic_legal_clearance':False,
        'automatic_payment_authority':False,
        'automatic_cargo_release':False,
        'fail_closed':True,
        'persistence_provider':p['provider'],
        'authority_notes':AUTHORITY_NOTES,
    }


@app.post('/cuba-fuels/customers')
async def create_consumer(payload: ConsumerIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    backend = get_backend(); ts = now()
    email = (payload.email or '').strip().lower() or None
    phone = (payload.phone or '').strip() or None
    existing = []
    if email:
        existing = await backend.select('customer_accounts', params={'email':f'eq.{email}','country_code':'eq.CU','limit':'1'}) or []
    if not existing and phone:
        existing = await backend.select('customer_accounts', params={'phone':f'eq.{phone}','country_code':'eq.CU','limit':'1'}) or []
    if existing:
        cid = existing[0]['customer_id']
        patch = {
            'legal_name':payload.full_name,'contact_name':payload.full_name,'customer_type':'INDIVIDUAL_CONSUMER',
            'country_code':'CU','email':email or existing[0].get('email'),'phone':phone or existing[0].get('phone'),
            'province':payload.province,'municipality':payload.municipality,'delivery_address':payload.delivery_address,
            'preferred_language':payload.preferred_language,'household_size':payload.household_size,
            'intended_personal_use':payload.intended_personal_use,'source_reference':payload.source_reference,
            'notes':payload.notes,'status':existing[0].get('status') or 'PROSPECT','sales_status':existing[0].get('sales_status') or 'NEW',
            'updated_at':ts,
        }
        await backend.patch('customer_accounts', patch, params={'customer_id':f'eq.{cid}'})
        return {'customer':{**existing[0],**patch,'customer_id':cid},'created':False}
    cid = f'cus_{secrets.token_urlsafe(10)}'
    row = {
        'customer_id':cid,'legal_name':payload.full_name,'trade_name':None,'contact_name':payload.full_name,
        'customer_type':'INDIVIDUAL_CONSUMER','email':email,'phone':phone,'country_code':'CU','website':None,
        'province':payload.province,'municipality':payload.municipality,'delivery_address':payload.delivery_address,
        'preferred_language':payload.preferred_language,'household_size':payload.household_size,
        'intended_personal_use':payload.intended_personal_use,'source_reference':payload.source_reference,
        'notes':payload.notes,'status':'PROSPECT','sales_status':'NEW','source':'CUBA_PRIVATE_FUELS_CONSUMER',
        'restricted_party_screening_status':'PENDING','scp_consumer_eligibility_status':'PENDING',
        'created_at':ts,'updated_at':ts,
    }
    await backend.insert('customer_accounts', row)
    await backend.insert('customer_crm_audit', {
        'event_id':f'crm_{secrets.token_urlsafe(10)}','customer_id':cid,'intake_id':None,'actor_role':'owner','actor_id':'owner',
        'event_type':'cuba_individual_consumer_created','summary':'Cuban individual consumer added as a customer for governed fuels workflow',
        'payload':{'country':'CU','customer_type':'INDIVIDUAL_CONSUMER'},'created_at':ts,
    })
    return {'customer':row,'created':True}


@app.get('/cuba-fuels/customers')
async def list_consumers(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('customer_accounts', params={'country_code':'eq.CU','customer_type':'eq.INDIVIDUAL_CONSUMER','order':'updated_at.desc','limit':'1000'}) or []
    return {'customers':rows,'customer_type':'INDIVIDUAL_CONSUMER'}


@app.patch('/cuba-fuels/customers/{customer_id}/status')
async def update_consumer_status(customer_id: str, payload: ConsumerStatusIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    await get_consumer(customer_id)
    ts = now()
    await get_backend().patch('customer_accounts', {'status':payload.status,'status_note':payload.note,'updated_at':ts}, params={'customer_id':f'eq.{customer_id}'})
    return {'customer_id':customer_id,'status':payload.status}


@app.post('/cuba-fuels/cases')
async def create_case(payload: FuelCaseIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    backend = get_backend(); ts = now(); fid = f'cuf_{secrets.token_urlsafe(12)}'
    risk_flags = []
    linked_customer = None
    if payload.customer_id:
        linked_customer = await get_consumer(payload.customer_id)
    if payload.end_user_type == 'INDIVIDUAL_CONSUMER':
        if not payload.customer_id:
            raise HTTPException(409, 'Individual consumer fuel cases must be linked to a Cuban individual consumer customer')
        if payload.private_business_id:
            raise HTTPException(409, 'Individual consumer fuel cases cannot use a private_business_id')
        if not payload.direct_sale_to_individual:
            raise HTTPException(409, 'SCP individual-consumer pathway requires a direct sale to the Cuban individual purchaser')
        if not payload.personal_or_immediate_family_use:
            raise HTTPException(409, 'SCP individual-consumer pathway requires personal use by the purchaser or immediate family')
        if linked_customer and linked_customer.get('status') in {'HOLD','DO_NOT_CONTACT'}:
            raise HTTPException(409, 'Consumer customer is not active for a new fuel case')
    if payload.payment_rail == 'CUBAN_OWNED_BANK':
        risk_flags.append('SCP_CUBAN_OWNED_BANK_PAYMENT_PATH_BLOCKED')
    if payload.end_user_type == 'OTHER':
        risk_flags.append('END_USER_ELIGIBILITY_REVIEW_REQUIRED')
    if payload.fuel_type in {'JET_FUEL','CRUDE_OIL'}:
        risk_flags.append('ENHANCED_END_USE_AND_SECTOR_REVIEW')
    if payload.end_user_type == 'INDIVIDUAL_CONSUMER':
        risk_flags.append('INDIVIDUAL_CONSUMER_SCP_ELIGIBILITY_REVIEW')
    row = {
        'fuel_case_id':fid, **payload.model_dump(), 'destination_country':'CU', 'status':'HOLD',
        'release_allowed':False, 'owner_approved':False, 'risk_flags':risk_flags,
        'scp_eligibility_status':'PENDING', 'ofac_incident_transaction_status':'PENDING',
        'consumer_screening_status':'PENDING' if payload.end_user_type == 'INDIVIDUAL_CONSUMER' else 'NOT_APPLICABLE',
        'cuba_trade_case_id':None, 'cuba_energy_opportunity_id':None,
        'created_at':ts, 'updated_at':ts,
    }
    await backend.insert('cuba_private_fuel_cases', row)
    for gate in REQUIRED_GATES:
        await backend.insert('cuba_private_fuel_gates', {
            'gate_id':f'cufg_{secrets.token_urlsafe(10)}','fuel_case_id':fid,'gate':gate,
            'status':'PENDING','evidence_reference':None,'evidence_summary':None,
            'reviewed_by':None,'reviewed_at':None,'created_at':ts,'updated_at':ts,
        })
    if payload.customer_id:
        await backend.insert('customer_crm_audit', {
            'event_id':f'crm_{secrets.token_urlsafe(10)}','customer_id':payload.customer_id,'intake_id':None,'actor_role':'owner','actor_id':'owner',
            'event_type':'cuba_fuel_case_created','summary':'Governed Cuba fuel case created for customer',
            'payload':{'fuel_case_id':fid,'fuel_type':payload.fuel_type,'end_user_type':payload.end_user_type},'created_at':ts,
        })
    return {'case':row,'required_gates':REQUIRED_GATES,'authority_notes':AUTHORITY_NOTES}


@app.get('/cuba-fuels/cases')
async def list_cases(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('cuba_private_fuel_cases', params={'order':'updated_at.desc','limit':'1000'}) or []
    return {'cases':rows,'authority':'PRIVATE_SECTOR_AND_INDIVIDUAL_CONSUMER_FUEL_TRADE_PREPARATION_ONLY'}


@app.get('/cuba-fuels/cases/{case_id}')
async def detail(case_id: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    row = await get_case(case_id)
    gates = await get_backend().select('cuba_private_fuel_gates', params={'fuel_case_id':f'eq.{case_id}','order':'updated_at.desc','limit':'500'}) or []
    customer = None
    if row.get('customer_id'):
        try: customer = await get_consumer(str(row.get('customer_id')))
        except HTTPException: customer = None
    return {'case':row,'customer':customer,'gates':gates,'gate_state':await gate_state(case_id),'authority_notes':AUTHORITY_NOTES}


@app.post('/cuba-fuels/cases/{case_id}/gates')
async def review_gate(case_id: str, payload: GateIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    if payload.gate not in REQUIRED_GATES:
        raise HTTPException(400, 'Unknown Cuba fuels gate')
    row = await get_case(case_id)
    if payload.gate == 'payment_path_no_cuban_owned_bank_deposit' and row.get('payment_rail') == 'CUBAN_OWNED_BANK' and payload.status == 'PASS':
        raise HTTPException(409, 'SCP cannot be marked PASS with a Cuban-owned-bank deposit payment path under the March 4, 2026 BIS suspension')
    if payload.gate == 'private_sector_end_use' and row.get('end_user_type') == 'INDIVIDUAL_CONSUMER' and payload.status == 'PASS':
        if row.get('direct_sale_to_individual') is not True or row.get('personal_or_immediate_family_use') is not True:
            raise HTTPException(409, 'Individual consumer eligibility cannot pass without direct-sale and personal/immediate-family-use evidence')
    ts = now()
    await get_backend().insert('cuba_private_fuel_gates', {
        'gate_id':f'cufg_{secrets.token_urlsafe(10)}','fuel_case_id':case_id,**payload.model_dump(),
        'reviewed_by':'owner','reviewed_at':ts,'created_at':ts,'updated_at':ts,
    })
    patch = {'updated_at':ts}
    if payload.gate == 'ear_classification_and_scp_eligibility':
        patch['scp_eligibility_status'] = payload.status
    if payload.gate == 'restricted_party_and_ownership_screening' and row.get('end_user_type') == 'INDIVIDUAL_CONSUMER':
        patch['consumer_screening_status'] = payload.status
        if row.get('customer_id'):
            await get_backend().patch('customer_accounts', {'restricted_party_screening_status':payload.status,'updated_at':ts}, params={'customer_id':f"eq.{row.get('customer_id')}"})
    if payload.gate == 'private_sector_or_consumer_eligibility' and row.get('end_user_type') == 'INDIVIDUAL_CONSUMER' and row.get('customer_id'):
        await get_backend().patch('customer_accounts', {'scp_consumer_eligibility_status':payload.status,'updated_at':ts}, params={'customer_id':f"eq.{row.get('customer_id')}"})
    if payload.status == 'FAIL':
        patch.update({'status':'HOLD','release_allowed':False,'owner_approved':False})
    await get_backend().patch('cuba_private_fuel_cases', patch, params={'fuel_case_id':f'eq.{case_id}'})
    return {'fuel_case_id':case_id,'gate':payload.gate,'status':payload.status}


@app.post('/cuba-fuels/cases/{case_id}/link')
async def link(case_id: str, payload: LinkIn, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    await get_case(case_id)
    trade = await get_backend().select('cuba_trade_cases', params={'trade_case_id':f'eq.{payload.cuba_trade_case_id}','limit':'1'}) or []
    if not trade:
        raise HTTPException(404, 'Cuba trade case not found')
    if payload.cuba_energy_opportunity_id:
        energy = await get_backend().select('cuba_energy_opportunities', params={'opportunity_id':f'eq.{payload.cuba_energy_opportunity_id}','limit':'1'}) or []
        if not energy:
            raise HTTPException(404, 'Cuba Energy opportunity not found')
    ts = now()
    await get_backend().patch('cuba_private_fuel_cases', {
        'cuba_trade_case_id':payload.cuba_trade_case_id,
        'cuba_energy_opportunity_id':payload.cuba_energy_opportunity_id,
        'status':'COMPLIANCE_REVIEW','release_allowed':False,'updated_at':ts,
    }, params={'fuel_case_id':f'eq.{case_id}'})
    return {'fuel_case_id':case_id,'linked':True,**payload.model_dump()}


@app.post('/cuba-fuels/cases/{case_id}/approve-lawful-workflow')
async def approve(case_id: str, authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    row = await get_case(case_id)
    if row.get('payment_rail') == 'CUBAN_OWNED_BANK':
        raise HTTPException(409, 'Blocked for SCP workflow: payment path deposits foreign funds into a Cuban-owned bank')
    if row.get('end_user_type') == 'INDIVIDUAL_CONSUMER':
        if not row.get('customer_id') or row.get('direct_sale_to_individual') is not True or row.get('personal_or_immediate_family_use') is not True:
            raise HTTPException(409, 'Individual consumer case lacks required direct-sale/personal-use customer evidence')
        customer = await get_consumer(str(row.get('customer_id')))
        if customer.get('restricted_party_screening_status') != 'PASS' or customer.get('scp_consumer_eligibility_status') != 'PASS':
            raise HTTPException(409, 'Individual consumer customer has not passed screening and SCP consumer eligibility review')
    states = await gate_state(case_id)
    incomplete = [g for g in REQUIRED_GATES if states.get(g) not in {'PASS','NOT_APPLICABLE'}]
    if incomplete:
        raise HTTPException(409, {'message':'Cuba private-sector/consumer fuel gates incomplete','gates':incomplete})
    if not row.get('cuba_trade_case_id'):
        raise HTTPException(409, 'A governed Cuba trade case must be linked')
    trade = await get_backend().select('cuba_trade_cases', params={'trade_case_id':f"eq.{row.get('cuba_trade_case_id')}",'limit':'1'}) or []
    if not trade or trade[0].get('status') != 'AUTHORIZED' or trade[0].get('release_allowed') is not True:
        raise HTTPException(409, 'Linked Cuba trade case is not AUTHORIZED for release')
    ts = now()
    await get_backend().patch('cuba_private_fuel_cases', {
        'status':'APPROVED_FOR_LAWFUL_WORKFLOW','release_allowed':True,'owner_approved':True,'owner_approved_at':ts,'updated_at':ts,
    }, params={'fuel_case_id':f'eq.{case_id}'})
    return {'fuel_case_id':case_id,'status':'APPROVED_FOR_LAWFUL_WORKFLOW','release_allowed':True}


@app.get('/cuba-fuels/summary')
async def summary(authorization: str | None = Header(None, alias='Authorization')):
    owner(authorization)
    rows = await get_backend().select('cuba_private_fuel_cases', params={'limit':'2000'}) or []
    consumers = await get_backend().select('customer_accounts', params={'country_code':'eq.CU','customer_type':'eq.INDIVIDUAL_CONSUMER','limit':'5000'}) or []
    active = [r for r in rows if r.get('status') not in {'CLOSED','REJECTED'}]
    by_type = {}
    for row in active:
        key = str(row.get('fuel_type') or 'OTHER_PETROLEUM')
        by_type[key] = by_type.get(key,0)+1
    return {
        'cases':len(rows),'active':len(active),'on_hold':sum(1 for r in active if r.get('status')=='HOLD'),
        'approved':sum(1 for r in active if r.get('status')=='APPROVED_FOR_LAWFUL_WORKFLOW'),
        'individual_consumer_customers':len(consumers),
        'individual_consumer_cases':sum(1 for r in active if r.get('end_user_type')=='INDIVIDUAL_CONSUMER'),
        'blocked_cuban_owned_bank_path':sum(1 for r in active if r.get('payment_rail')=='CUBAN_OWNED_BANK'),
        'estimated_pipeline_value':round(sum(float(r.get('estimated_value') or 0) for r in active),2),
        'by_fuel_type':by_type,
        'note':'Eligibility is transaction-specific. This desk operationalizes current BIS/OFAC guidance; it does not replace legal/compliance review.',
    }
