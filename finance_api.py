from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(title='SAHJONY Global Trade Finance', version='1.0.0', docs_url=None, redoc_url=None)
Role = Literal['owner','employee']

class EntryIn(BaseModel):
    account_id: str = Field(min_length=1,max_length=120)
    debit: Decimal = Field(default=Decimal('0'), ge=0)
    credit: Decimal = Field(default=Decimal('0'), ge=0)
    memo: str | None = Field(default=None,max_length=500)

class JournalCreate(BaseModel):
    trade_case_id: str | None = Field(default=None,max_length=180)
    reference_type: str | None = Field(default=None,max_length=80)
    reference_id: str | None = Field(default=None,max_length=180)
    description: str = Field(min_length=2,max_length=1000)
    currency: str = Field(default='USD',min_length=3,max_length=12)
    source: str = Field(default='manual',max_length=80)
    entries: list[EntryIn] = Field(min_length=2,max_length=100)

class ReconciliationCreate(BaseModel):
    trade_case_id: str | None = Field(default=None,max_length=180)
    payment_id: str | None = Field(default=None,max_length=180)
    bank_reference: str | None = Field(default=None,max_length=240)
    invoice_reference: str | None = Field(default=None,max_length=180)
    purchase_order_reference: str | None = Field(default=None,max_length=180)
    expected_amount: Decimal | None = Field(default=None,ge=0)
    received_amount: Decimal | None = Field(default=None,ge=0)
    currency: str = Field(default='USD',max_length=12)
    status: Literal['unmatched','partial','matched','exception'] = 'unmatched'
    exception_reason: str | None = Field(default=None,max_length=1000)
    matched_journal_id: str | None = Field(default=None,max_length=180)

class BeneficiaryChangeCreate(BaseModel):
    counterparty_type: str = Field(min_length=2,max_length=80)
    counterparty_id: str = Field(min_length=1,max_length=180)
    old_bank_fingerprint: str | None = Field(default=None,max_length=180)
    new_bank_fingerprint: str = Field(min_length=8,max_length=180)
    verification_method: str | None = Field(default=None,max_length=240)

class BeneficiaryVerify(BaseModel):
    verification_method: str = Field(min_length=2,max_length=240)


def now(): return datetime.now(timezone.utc).isoformat()

def employee_token():
    token=os.getenv('EMPLOYEE_TOKEN','').strip()
    if not token: raise HTTPException(503,'Employee finance access is not configured')
    return token

def identity(role, authorization, employee_id):
    if role not in {'owner','employee'}: raise HTTPException(400,'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
    token=authorization.removeprefix('Bearer ').strip()
    if role=='owner':
        if not verify_owner_token(token): raise HTTPException(403,'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if not secrets.compare_digest(token,employee_token()): raise HTTPException(403,'Invalid employee credential')
    return {'role':'employee','id':(employee_id or 'staff')[:160]}

def money(v: Decimal): return str(v.quantize(Decimal('0.0001')))

def validate_entries(entries: list[EntryIn]):
    debits=sum((e.debit for e in entries),Decimal('0'))
    credits=sum((e.credit for e in entries),Decimal('0'))
    for e in entries:
        if (e.debit>0) == (e.credit>0):
            raise HTTPException(400,'Each ledger entry must contain exactly one positive debit or credit')
    if debits != credits:
        raise HTTPException(400,f'Journal is not balanced: debits={debits} credits={credits}')
    if debits <= 0:
        raise HTTPException(400,'Journal total must be greater than zero')
    return debits

@app.get('/finance/health')
async def health():
    return {'status':'ok','service':'trade-finance-ledger','double_entry':True,'owner_posting_only':True,'beneficiary_maker_checker':True}

@app.post('/finance/journals')
async def create_journal(payload: JournalCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); total=validate_entries(payload.entries)
    jid=f'jrnl_{secrets.token_urlsafe(12)}'; ts=now()
    row={'journal_id':jid,'trade_case_id':payload.trade_case_id,'reference_type':payload.reference_type,'reference_id':payload.reference_id,
         'description':payload.description,'currency':payload.currency.upper(),'status':'draft','source':payload.source,
         'owner_approved':False,'created_by_role':actor['role'],'created_by_id':actor['id'],'created_at':ts}
    await get_backend().insert('ledger_journals',row)
    entries=[]
    for e in payload.entries:
        entries.append({'entry_id':f'ent_{secrets.token_urlsafe(12)}','journal_id':jid,'account_id':e.account_id,
                        'debit':money(e.debit),'credit':money(e.credit),'memo':e.memo,'created_at':ts})
    await get_backend().insert('ledger_entries',entries)
    return {'journal':row,'entries':entries,'balanced_total':money(total)}

@app.post('/finance/journals/{journal_id}/post')
async def post_journal(journal_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner': raise HTTPException(403,'Only owner may post financial journals')
    rows=await get_backend().select('ledger_journals',params={'journal_id':f'eq.{journal_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Journal not found')
    if rows[0].get('status')!='draft': raise HTTPException(409,'Only draft journals can be posted')
    entries=await get_backend().select('ledger_entries',params={'journal_id':f'eq.{journal_id}','limit':'500'}) or []
    debits=sum((Decimal(str(e.get('debit') or 0)) for e in entries),Decimal('0')); credits=sum((Decimal(str(e.get('credit') or 0)) for e in entries),Decimal('0'))
    if not entries or debits!=credits or debits<=0: raise HTTPException(409,'Journal failed balance validation')
    ts=now(); values={'status':'posted','owner_approved':True,'approved_by':actor['id'],'approved_at':ts,'posted_at':ts}
    await get_backend().patch('ledger_journals',values,params={'journal_id':f'eq.{journal_id}'})
    return {'journal_id':journal_id,'status':'posted','posted_at':ts,'total':money(debits)}

@app.get('/finance/journals')
async def list_journals(trade_case_id: str|None=Query(default=None,max_length=180), status: str|None=Query(default=None,max_length=40), x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role,authorization,x_employee_id); params={'order':'created_at.desc','limit':'500'}
    if trade_case_id: params['trade_case_id']=f'eq.{trade_case_id}'
    if status: params['status']=f'eq.{status}'
    return {'journals':await get_backend().select('ledger_journals',params=params) or []}

@app.post('/finance/reconciliations')
async def create_reconciliation(payload: ReconciliationCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); rid=f'rec_{secrets.token_urlsafe(12)}'; ts=now()
    row={'reconciliation_id':rid,**payload.model_dump(mode='json'),'reconciled_by_role':actor['role'] if payload.status=='matched' else None,
         'reconciled_by_id':actor['id'] if payload.status=='matched' else None,'reconciled_at':ts if payload.status=='matched' else None,'created_at':ts,'updated_at':ts}
    await get_backend().insert('payment_reconciliations',row); return {'reconciliation':row}

@app.post('/finance/beneficiary-changes')
async def request_beneficiary_change(payload: BeneficiaryChangeCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); rid=f'bcr_{secrets.token_urlsafe(12)}'
    row={'request_id':rid,**payload.model_dump(),'status':'pending','requested_by_role':actor['role'],'requested_by_id':actor['id'],'created_at':now()}
    await get_backend().insert('beneficiary_change_requests',row); return {'request':row}

@app.post('/finance/beneficiary-changes/{request_id}/verify')
async def verify_beneficiary_change(request_id: str, payload: BeneficiaryVerify, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id); ts=now()
    await get_backend().patch('beneficiary_change_requests',{'status':'verified','verification_method':payload.verification_method,'verified_by':actor['id'],'verified_at':ts},params={'request_id':f'eq.{request_id}','status':'eq.pending'})
    return {'request_id':request_id,'status':'verified'}

@app.post('/finance/beneficiary-changes/{request_id}/approve')
async def approve_beneficiary_change(request_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner': raise HTTPException(403,'Only owner may approve bank-detail changes')
    rows=await get_backend().select('beneficiary_change_requests',params={'request_id':f'eq.{request_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Request not found')
    if rows[0].get('status')!='verified': raise HTTPException(409,'Beneficiary change must be independently verified before approval')
    ts=now(); await get_backend().patch('beneficiary_change_requests',{'status':'approved','approved_by':actor['id'],'approved_at':ts},params={'request_id':f'eq.{request_id}'})
    return {'request_id':request_id,'status':'approved'}
