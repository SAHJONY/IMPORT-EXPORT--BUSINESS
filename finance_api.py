from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import verify_owner_token
from physical_postgres import database_health, insert_row, select_rows, update_rows

app = FastAPI(title='SAHJONY Global Trade Finance', version='2.0.0', docs_url=None, redoc_url=None)
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
    currency: Literal['USD'] = 'USD'
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
    currency: Literal['USD'] = 'USD'
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


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def employee_token() -> str:
    token=os.getenv('EMPLOYEE_TOKEN','').strip()
    if not token:
        raise HTTPException(503,'Employee finance access is not configured')
    return token


def identity(role, authorization, employee_id):
    if role not in {'owner','employee'}:
        raise HTTPException(400,'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401,'Missing Authorization')
    token=authorization.removeprefix('Bearer ').strip()
    if role=='owner':
        if not verify_owner_token(token):
            raise HTTPException(403,'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if not secrets.compare_digest(token,employee_token()):
        raise HTTPException(403,'Invalid employee credential')
    return {'role':'employee','id':(employee_id or 'staff')[:160]}


def money(v: Decimal) -> str:
    return str(v.quantize(Decimal('0.0001')))


def validate_entries(entries: list[EntryIn]) -> Decimal:
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


async def validate_accounts(entries: list[EntryIn]) -> None:
    accounts = await select_rows('ledger_accounts', limit=500)
    active = {str(a.get('account_id')) for a in accounts if a.get('active') is True}
    missing = sorted({e.account_id for e in entries if e.account_id not in active})
    if missing:
        raise HTTPException(400, f'Unknown or inactive ledger account(s): {", ".join(missing)}')


async def journal_rows(journal_id: str) -> tuple[dict, list[dict]]:
    rows=await select_rows('ledger_journals',filters={'journal_id':journal_id},limit=1)
    if not rows:
        raise HTTPException(404,'Journal not found')
    entries=await select_rows('ledger_entries',filters={'journal_id':journal_id},limit=500)
    return rows[0], entries


@app.get('/finance/health')
async def health():
    dependency = await database_health()
    body = {
        'status': dependency['status'],
        'service':'trade-finance-ledger',
        'storage':'physical_postgres',
        'dependency': dependency,
        'currency':'USD',
        'double_entry':True,
        'owner_posting_only':True,
        'posted_journal_edits':False,
        'reversal_required_for_corrections':True,
        'beneficiary_maker_checker':True,
        'beneficiary_requester_cannot_verify':True,
        'beneficiary_verifier_cannot_approve':True,
    }
    if dependency['status'] != 'ok':
        return JSONResponse(status_code=503, content=body)
    return body


@app.get('/finance/accounts')
async def list_accounts(x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role,authorization,x_employee_id)
    return {'accounts':await select_rows('ledger_accounts',filters={'active':True},order_by='code',limit=500)}


@app.post('/finance/journals')
async def create_journal(payload: JournalCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    total=validate_entries(payload.entries)
    await validate_accounts(payload.entries)
    jid=f'jrnl_{secrets.token_urlsafe(12)}'
    ts=now()
    row={
        'journal_id':jid,'trade_case_id':payload.trade_case_id,'reference_type':payload.reference_type,'reference_id':payload.reference_id,
        'description':payload.description,'currency':'USD','status':'draft','source':payload.source,
        'owner_approved':False,'created_by_role':actor['role'],'created_by_id':actor['id'],'created_at':ts,
    }
    journal=await insert_row('ledger_journals',row)
    entries=[]
    for e in payload.entries:
        entry=await insert_row('ledger_entries',{
            'entry_id':f'ent_{secrets.token_urlsafe(12)}','journal_id':jid,'account_id':e.account_id,
            'debit':e.debit,'credit':e.credit,'memo':e.memo,'created_at':ts,
        })
        entries.append(entry)
    return {'journal':journal,'entries':entries,'balanced_total':money(total),'currency':'USD'}


@app.post('/finance/journals/{journal_id}/post')
async def post_journal(journal_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner':
        raise HTTPException(403,'Only owner may post financial journals')
    journal, entries=await journal_rows(journal_id)
    if journal.get('status')!='draft':
        raise HTTPException(409,'Only draft journals can be posted')
    debits=sum((Decimal(str(e.get('debit') or 0)) for e in entries),Decimal('0'))
    credits=sum((Decimal(str(e.get('credit') or 0)) for e in entries),Decimal('0'))
    if not entries or debits!=credits or debits<=0:
        raise HTTPException(409,'Journal failed balance validation')
    ts=now()
    updated=await update_rows('ledger_journals',{
        'status':'posted','owner_approved':True,'approved_by':actor['id'],'approved_at':ts,'posted_at':ts,
    },filters={'journal_id':journal_id,'status':'draft'})
    if not updated:
        raise HTTPException(409,'Journal state changed before posting')
    return {'journal_id':journal_id,'status':'posted','posted_at':ts,'total':money(debits),'currency':'USD'}


@app.post('/finance/journals/{journal_id}/reverse')
async def reverse_journal(journal_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner':
        raise HTTPException(403,'Only owner may reverse posted financial journals')
    journal, entries=await journal_rows(journal_id)
    if journal.get('status')!='posted':
        raise HTTPException(409,'Only posted journals can be reversed')
    reverse_id=f'jrnl_{secrets.token_urlsafe(12)}'
    ts=now()
    reversal=await insert_row('ledger_journals',{
        'journal_id':reverse_id,
        'trade_case_id':journal.get('trade_case_id'),
        'reference_type':'REVERSAL',
        'reference_id':journal_id,
        'description':f"Reversal of {journal_id}: {journal.get('description') or ''}"[:1000],
        'currency':'USD','status':'posted','source':'system_reversal','owner_approved':True,
        'approved_by':actor['id'],'approved_at':ts,'posted_at':ts,
        'created_by_role':actor['role'],'created_by_id':actor['id'],'created_at':ts,
    })
    total=Decimal('0')
    for e in entries:
        debit=Decimal(str(e.get('debit') or 0))
        credit=Decimal(str(e.get('credit') or 0))
        total += debit
        await insert_row('ledger_entries',{
            'entry_id':f'ent_{secrets.token_urlsafe(12)}','journal_id':reverse_id,'account_id':e.get('account_id'),
            'debit':credit,'credit':debit,'memo':f'Reversal of {e.get("entry_id") or "entry"}','created_at':ts,
        })
    changed=await update_rows('ledger_journals',{'status':'reversed'},filters={'journal_id':journal_id,'status':'posted'})
    if not changed:
        raise HTTPException(409,'Original journal state changed before reversal')
    return {'journal_id':journal_id,'status':'reversed','reversal_journal':reversal,'reversal_total':money(total),'currency':'USD'}


@app.get('/finance/journals')
async def list_journals(trade_case_id: str|None=Query(default=None,max_length=180), status: str|None=Query(default=None,max_length=40), x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role,authorization,x_employee_id)
    filters={}
    if trade_case_id:
        filters['trade_case_id']=trade_case_id
    if status:
        filters['status']=status
    return {'journals':await select_rows('ledger_journals',filters=filters,order_by='created_at',descending=True,limit=500)}


@app.post('/finance/reconciliations')
async def create_reconciliation(payload: ReconciliationCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if payload.status=='matched' and not payload.matched_journal_id:
        raise HTTPException(400,'Matched reconciliation requires a matched journal ID')
    if payload.matched_journal_id:
        journal,_=await journal_rows(payload.matched_journal_id)
        if journal.get('status') not in {'posted','reversed'}:
            raise HTTPException(409,'Reconciliation journal must be posted')
    rid=f'rec_{secrets.token_urlsafe(12)}'
    ts=now()
    row={
        'reconciliation_id':rid,
        'trade_case_id':payload.trade_case_id,
        'payment_id':payload.payment_id,
        'bank_reference':payload.bank_reference,
        'invoice_reference':payload.invoice_reference,
        'purchase_order_reference':payload.purchase_order_reference,
        'expected_amount':payload.expected_amount,
        'received_amount':payload.received_amount,
        'currency':'USD',
        'status':payload.status,
        'exception_reason':payload.exception_reason,
        'matched_journal_id':payload.matched_journal_id,
        'reconciled_by_role':actor['role'] if payload.status=='matched' else None,
        'reconciled_by_id':actor['id'] if payload.status=='matched' else None,
        'reconciled_at':ts if payload.status=='matched' else None,
        'created_at':ts,'updated_at':ts,
    }
    return {'reconciliation':await insert_row('payment_reconciliations',row)}


@app.post('/finance/beneficiary-changes')
async def request_beneficiary_change(payload: BeneficiaryChangeCreate, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    rid=f'bcr_{secrets.token_urlsafe(12)}'
    row={
        'request_id':rid,
        'counterparty_type':payload.counterparty_type,
        'counterparty_id':payload.counterparty_id,
        'old_bank_fingerprint':payload.old_bank_fingerprint,
        'new_bank_fingerprint':payload.new_bank_fingerprint,
        'verification_method':payload.verification_method,
        'status':'pending','requested_by_role':actor['role'],'requested_by_id':actor['id'],'created_at':now(),
    }
    return {'request':await insert_row('beneficiary_change_requests',row)}


@app.post('/finance/beneficiary-changes/{request_id}/verify')
async def verify_beneficiary_change(request_id: str, payload: BeneficiaryVerify, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    rows=await select_rows('beneficiary_change_requests',filters={'request_id':request_id},limit=1)
    if not rows:
        raise HTTPException(404,'Request not found')
    request=rows[0]
    if request.get('status')!='pending':
        raise HTTPException(409,'Only pending beneficiary changes can be verified')
    if str(request.get('requested_by_role'))==actor['role'] and str(request.get('requested_by_id'))==actor['id']:
        raise HTTPException(409,'Beneficiary change requester cannot verify their own request')
    ts=now()
    updated=await update_rows('beneficiary_change_requests',{
        'status':'verified','verification_method':payload.verification_method,'verified_by':actor['id'],'verified_at':ts,
    },filters={'request_id':request_id,'status':'pending'})
    if not updated:
        raise HTTPException(409,'Beneficiary change state changed before verification')
    return {'request_id':request_id,'status':'verified','verified_by':actor['id']}


@app.post('/finance/beneficiary-changes/{request_id}/approve')
async def approve_beneficiary_change(request_id: str, x_role: str|None=Header(None,alias='X-Role'), authorization: str|None=Header(None,alias='Authorization'), x_employee_id: str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if actor['role']!='owner':
        raise HTTPException(403,'Only owner may approve bank-detail changes')
    rows=await select_rows('beneficiary_change_requests',filters={'request_id':request_id},limit=1)
    if not rows:
        raise HTTPException(404,'Request not found')
    request=rows[0]
    if request.get('status')!='verified':
        raise HTTPException(409,'Beneficiary change must be independently verified before approval')
    if str(request.get('verified_by') or '')==actor['id']:
        raise HTTPException(409,'Beneficiary verifier cannot also approve the change')
    ts=now()
    updated=await update_rows('beneficiary_change_requests',{
        'status':'approved','approved_by':actor['id'],'approved_at':ts,
    },filters={'request_id':request_id,'status':'verified'})
    if not updated:
        raise HTTPException(409,'Beneficiary change state changed before approval')
    return {'request_id':request_id,'status':'approved','approved_by':actor['id']}
