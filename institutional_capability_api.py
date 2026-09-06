from __future__ import annotations

import inspect
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from auth import verify_owner_token
from customer_crm_api import data_health as crm_data_health
from global_supplier_sourcing_api import health as supplier_health
from pricing_api import health as pricing_health
from compliance_api import health as compliance_health
from shipment_api import health as logistics_health
from document_storage_api import health as document_health
from profit_machine_api import profit_machine_health
from gmail_transport_api import native_email_health
from google_calendar_transport_api import calendar_health
from telegram_api import telegram_health
from sofia_crm_growth_engine import growth_health

app = FastAPI(title='SAHJONY Institutional Capability Control', version='10.0.0', docs_url=None, redoc_url=None)

CAPABILITIES = [
    ('crm_sync','CRM synchronization','customer_accounts + trade intakes + verified engagement evidence'),
    ('supplier_intelligence','Supplier intelligence','supplier identity + quote + capacity + lead time + documentation'),
    ('rfq_qualification','Buyer/RFQ qualification','evidence-gated demand progression; no outreach-created RFQs'),
    ('pricing_margin','Pricing and margin','landed cost + margin floor + customer/internal isolation'),
    ('kyb_compliance','KYB/compliance','counterparty verification + sanctions/compliance controls'),
    ('logistics','Logistics intelligence','shipment/container/port/carrier evidence'),
    ('executive_comms','Executive communications','Gmail + WhatsApp + Telegram relationship context + calendar coordination'),
    ('deal_room','Deal room/document control','durable document storage + trade-document traceability'),
    ('production_health','Production health','fail-closed module health + reversible recovery'),
    ('business_intelligence','Business intelligence','qualified demand -> quote -> PO -> collected GP truth'),
]


def _owner(auth: str | None, role: str | None) -> None:
    if role != 'owner': raise HTTPException(403,'Owner role required')
    if not auth or not auth.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()): raise HTTPException(403,'Invalid owner credential')


async def _safe(fn) -> dict[str, Any]:
    try:
        value = fn()
        if inspect.isawaitable(value): value = await value
        return value if isinstance(value, dict) else {'status':'unknown'}
    except Exception as exc:
        return {'status':'degraded','error_type':type(exc).__name__}


def _ok(value: dict[str, Any]) -> bool:
    return str(value.get('status') or '').lower() in {'ok','ready','healthy','active'}


@app.get('/owner/capabilities/health')
async def capability_health(authorization: str|None=Header(None,alias='Authorization'), x_role: str|None=Header(None,alias='X-Role')):
    _owner(authorization,x_role)
    crm,supplier,pricing,compliance,logistics,documents,profit,email,calendar,telegram = await __import__('asyncio').gather(
        _safe(crm_data_health),_safe(supplier_health),_safe(pricing_health),_safe(compliance_health),_safe(logistics_health),
        _safe(document_health),_safe(profit_machine_health),_safe(native_email_health),_safe(calendar_health),_safe(telegram_health),
    )
    growth=growth_health()
    checks={
        'crm_sync': _ok(crm) and growth.get('commercial_stage_fail_closed') is True,
        'supplier_intelligence': _ok(supplier),
        'rfq_qualification': growth.get('commercial_stage_fail_closed') is True and growth.get('unsolicited_autonomous_outreach') is False,
        'pricing_margin': _ok(pricing) and pricing.get('cost_basis_private') is True and pricing.get('owner_approval_required') is True,
        'kyb_compliance': _ok(compliance),
        'logistics': _ok(logistics),
        'executive_comms': _ok(email) and _ok(calendar) and _ok(telegram) and telegram.get('bot_token_configured') is True and telegram.get('channel_configured') is True,
        'deal_room': _ok(documents),
        'production_health': all(str(x.get('status') or '').lower() not in {'error','failed'} for x in (crm,supplier,pricing,compliance,logistics,documents)),
        'business_intelligence': _ok(profit),
    }
    rows=[]
    for key,name,evidence in CAPABILITIES:
        rows.append({'key':key,'name':name,'passed':bool(checks[key]),'evidence_contract':evidence,'fail_closed':True})
    passed=sum(1 for row in rows if row['passed'])
    collected=float(profit.get('verified_collected_fee_usd') or profit.get('collected_fee_usd') or 0)
    return {
        'status':'ok' if passed==len(rows) else 'attention',
        'score':round(passed/len(rows)*10,1),'target':10.0,'passed':passed,'total':len(rows),
        'capabilities':rows,'verified_collected_gross_profit_usd':collected,
        'truth_rules':{'research_is_not_revenue':True,'outreach_is_not_demand':True,'invoice_is_not_collected':True,'binding_actions_owner_gated':True},
        'sources':{'crm':crm,'supplier':supplier,'pricing':pricing,'compliance':compliance,'logistics':logistics,'documents':documents,'profit':profit,'email':email,'calendar':calendar,'telegram':telegram},
    }
