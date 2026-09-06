from __future__ import annotations

import os, secrets
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from auth import verify_owner_token
from insforge_backend import get_backend
from crm_campaign_bootstrap import CAMPAIGN, bootstrap_cuba_mipyme_outreach, load_seed
from sofia_crm_growth_engine import build_growth_queue, growth_health

app=FastAPI(title='SAHJONY Customer CRM',version='1.5.0',docs_url=None,redoc_url=None)
Role=Literal['owner','employee']
_BOOTSTRAP_STATUS={'campaign':CAMPAIGN,'seed_count':len(load_seed()),'status':'PENDING','result':None}

def now(): return datetime.now(timezone.utc).isoformat()
def employee_token():
    token=os.getenv('EMPLOYEE_TOKEN','').strip()
    if not token: raise HTTPException(503,'Employee access not configured')
    return token

def identity(role,authorization,employee_id):
    if role not in {'owner','employee'}: raise HTTPException(400,'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
    token=authorization.removeprefix('Bearer ').strip()
    if role=='owner':
        if not verify_owner_token(token): raise HTTPException(403,'Invalid owner credential')
        return {'role':'owner','id':'owner'}
    if not secrets.compare_digest(token,employee_token()): raise HTTPException(403,'Invalid employee credential')
    return {'role':'employee','id':(employee_id or 'staff')[:160]}

async def ensure_campaign_bootstrap():
    global _BOOTSTRAP_STATUS
    if _BOOTSTRAP_STATUS.get('status')=='IMPORTED':
        return _BOOTSTRAP_STATUS
    try:
        result=await bootstrap_cuba_mipyme_outreach()
        _BOOTSTRAP_STATUS={'campaign':CAMPAIGN,'seed_count':len(load_seed()),'status':'IMPORTED','result':result}
    except Exception as exc:
        _BOOTSTRAP_STATUS={'campaign':CAMPAIGN,'seed_count':len(load_seed()),'status':'WAITING_FOR_DURABLE_BACKEND','result':{'error_type':type(exc).__name__}}
    return _BOOTSTRAP_STATUS

@app.on_event('startup')
async def bootstrap_campaign_leads():
    await ensure_campaign_bootstrap()

class IntakeIn(BaseModel):
    legal_name:str=Field(min_length=2,max_length=240)
    trade_name:str|None=None
    contact_name:str=Field(min_length=2,max_length=160)
    email:str=Field(min_length=5,max_length=320)
    phone:str|None=None
    country_code:str|None=None
    website:str|None=None
    product_need:str=Field(min_length=2,max_length=1000)
    specifications:str|None=None
    quantity:float|None=None
    target_budget:float|None=None
    currency:str='USD'
    destination_country:str=Field(min_length=2,max_length=3)
    target_delivery_date:str|None=None
    preferred_incoterm:str|None=None
    notes:str|None=None

    @field_validator('email')
    @classmethod
    def validate_email(cls,v:str)->str:
        value=v.strip().lower()
        if '@' not in value or value.startswith('@') or value.endswith('@') or '.' not in value.split('@',1)[1]:
            raise ValueError('Valid email required')
        return value

class ProspectIntakeIn(BaseModel):
    product_need:str=Field(min_length=2,max_length=1000)
    specifications:str|None=None
    quantity:float|None=None
    target_budget:float|None=None
    currency:str='USD'
    destination_country:str=Field(min_length=2,max_length=3)
    target_delivery_date:str|None=None
    preferred_incoterm:str|None=None
    notes:str|None=None

class ProspectStatusIn(BaseModel):
    status:Literal['NEW','CONTACTED','FOLLOW_UP_DUE','REPLIED','QUALIFIED_LEAD','DO_NOT_CONTACT']
    next_follow_up_at:str|None=None
    notes:str|None=None

class SofiaPursuitIn(BaseModel):
    limit:int=Field(default=50,ge=1,le=250)
    execute_reversible_steps:bool=False

class EngagementEvidenceIn(BaseModel):
    channel:Literal['gmail','whatsapp','website','calendar','other']
    interaction_at:str=Field(min_length=10,max_length=80)
    evidence_ref:str=Field(min_length=3,max_length=512)
    summary:str=Field(min_length=3,max_length=1200)
    genuine_counterparty_reply:bool=True
    transactional_context:bool=True

class QualifyIn(BaseModel):
    status:Literal['QUALIFIED','NEEDS_INFO','DISQUALIFIED']
    assigned_employee_id:str|None=None
    notes:str|None=None

async def audit(actor,event,summary,customer_id=None,intake_id=None,payload=None):
    await get_backend().insert('customer_crm_audit',{
        'event_id':f'crm_{secrets.token_urlsafe(10)}','customer_id':customer_id,'intake_id':intake_id,
        'actor_role':actor['role'],'actor_id':actor['id'],'event_type':event,'summary':summary,
        'payload':payload or {},'created_at':now()
    })

@app.get('/crm/health')
async def health():
    bootstrap=await ensure_campaign_bootstrap()
    return {'status':'ok','service':'customer-crm','public_intake':True,'fail_closed_promotion':True,'campaign_bootstrap':bootstrap,'external_trade_research_visible':True,'full_record_detail':True,'sofia_growth_engine':growth_health()}

@app.get('/crm/sofia/health')
async def sofia_crm_health():
    return growth_health()

async def _sofia_growth_queue():
    backend=get_backend()
    accounts=await backend.select('customer_accounts',params={'limit':'5000'}) or []
    intakes=await backend.select('customer_trade_intakes',params={'limit':'5000'}) or []
    audits=await backend.select('customer_crm_audit',params={'limit':'5000'}) or []
    verified_replies={}
    for event in audits:
        if event.get('event_type')!='counterparty_reply_verified' or not event.get('customer_id'):
            continue
        payload=event.get('payload') or {}
        if not payload.get('genuine_counterparty_reply') or not payload.get('transactional_context'):
            continue
        cid=str(event['customer_id'])
        current=verified_replies.get(cid)
        if current is None or str(event.get('created_at') or '')>str(current.get('created_at') or ''):
            verified_replies[cid]=event
    enriched=[]
    for row in accounts:
        item=dict(row)
        event=verified_replies.get(str(item.get('customer_id') or ''))
        if event:
            payload=event.get('payload') or {}
            item['sales_status']='REPLIED'
            item['consent_status']='TRANSACTIONAL_ONLY'
            item['last_reply_at']=payload.get('interaction_at') or event.get('created_at')
            item['engagement_evidence']=payload.get('evidence_ref') or event.get('event_id')
        enriched.append(item)
    try: external=await backend.select('external_trade_prospects',params={'organization_id':'eq.org_sahjony_global_trade','limit':'5000'}) or []
    except Exception: external=[]
    try: whatsapp=await backend.select('whatsapp_leads',params={'limit':'5000'}) or []
    except Exception: whatsapp=[]
    return build_growth_queue(enriched,intakes,external,whatsapp)


@app.post('/crm/prospects/{customer_id}/engagement-evidence')
async def record_engagement_evidence(customer_id:str,p:EngagementEvidenceIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if not p.genuine_counterparty_reply or not p.transactional_context:
        raise HTTPException(400,'Only genuine counterparty replies in an existing transactional context qualify as engagement evidence')
    rows=await get_backend().select('customer_accounts',params={'customer_id':f'eq.{customer_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Prospect not found')
    payload=p.model_dump()|{'contact_basis':'TRANSACTIONAL_ONLY','marketing_consent':False}
    await audit(actor,'counterparty_reply_verified',p.summary,customer_id,payload=payload)
    return {'status':'recorded','customer_id':customer_id,'sales_status':'REPLIED','contact_basis':'TRANSACTIONAL_ONLY','marketing_consent':False,'intake_created':False,'message_sent':False}

@app.get('/crm/sofia/growth-queue')
async def sofia_growth_queue(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    identity(x_role,authorization,x_employee_id)
    queue=await _sofia_growth_queue()
    return {'status':'ok','count':len(queue),'queue':queue,'autonomous_messages_sent':0}

@app.post('/crm/sofia/pursue')
async def sofia_pursue(p:SofiaPursuitIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    queue=(await _sofia_growth_queue())[:p.limit]
    selected=[row for row in queue if not row['assessment']['blocked'] and row['assessment']['autonomous_outreach_allowed']]
    if p.execute_reversible_steps:
        for row in selected:
            customer_id=row['lead_ref'] if row['source']=='customer_crm' else None
            await audit(actor,'sofia_lead_pursuit_queued',row['assessment']['next_best_action'],customer_id,payload={
                'lead_ref':row['lead_ref'],'source':row['source'],'score':row['assessment']['score'],'company':row['company'],
                'autonomous_outreach_allowed':row['assessment']['autonomous_outreach_allowed'],
                'message_sent':False,'owner_review_required':not row['assessment']['autonomous_outreach_allowed'],
            })
    return {
        'status':'queued' if p.execute_reversible_steps else 'planned',
        'evaluated':len(queue),'selected':len(selected),'blocked_or_ineligible':len(queue)-len(selected),
        'actions':selected,'messages_sent':0,
        'rule':'Sofia may queue pursuit only for prospects explicitly assessed as autonomous_outreach_allowed; actual outreach still requires a consent-compatible route and channel execution evidence.',
    }

@app.get('/crm/data-health')
async def data_health():
    bootstrap=await ensure_campaign_bootstrap()
    backend=get_backend()
    accounts=await backend.select('customer_accounts',params={'limit':'5000'}) or []
    intakes=await backend.select('customer_trade_intakes',params={'limit':'5000'}) or []
    audits=await backend.select('customer_crm_audit',params={'limit':'5000'}) or []
    try:
        external=await backend.select('external_trade_prospects',params={'organization_id':'eq.org_sahjony_global_trade','limit':'5000'}) or []
    except Exception:
        external=[]
    campaign_accounts=[row for row in accounts if row.get('source')==CAMPAIGN]
    campaign_audits=[row for row in audits if (row.get('payload') or {}).get('campaign')==CAMPAIGN]
    return {
        'status':'ok','service':'customer-crm-data','bootstrap_status':bootstrap.get('status'),'bootstrap_result':bootstrap.get('result'),'seed_count':len(load_seed()),
        'customer_account_count':len(accounts),'trade_intake_count':len(intakes),'external_trade_prospect_count':len(external),'crm_audit_count':len(audits),
        'campaign_account_count':len(campaign_accounts),'campaign_audit_count':len(campaign_audits),'pii_exposed':False,
    }

@app.get('/crm/growth-summary')
async def growth_summary(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    await ensure_campaign_bootstrap()
    backend=get_backend()
    account_params={'limit':'5000'}
    intake_params={'limit':'5000'}
    if actor['role']=='employee':
        account_params['assigned_employee_id']=f'eq.{actor["id"]}'
        intake_params['assigned_employee_id']=f'eq.{actor["id"]}'
    accounts=await backend.select('customer_accounts',params=account_params) or []
    intakes=await backend.select('customer_trade_intakes',params=intake_params) or []
    audits=await backend.select('customer_crm_audit',params={'limit':'5000'}) or []
    intake_customer_ids={row.get('customer_id') for row in intakes}
    prospects=[row for row in accounts if row.get('customer_id') not in intake_customer_ids]
    qualified=[row for row in intakes if row.get('qualification_status')=='QUALIFIED']
    promoted=[row for row in intakes if row.get('managed_trade_request_id') or row.get('status')=='PROMOTED']
    replied=[row for row in accounts if row.get('sales_status') in {'REPLIED','QUALIFIED_LEAD'}]
    follow_up=[row for row in accounts if row.get('sales_status')=='FOLLOW_UP_DUE']
    do_not_contact=[row for row in accounts if row.get('sales_status')=='DO_NOT_CONTACT']
    outreach_events=[row for row in audits if row.get('event_type')=='outreach_sent']
    total_accounts=len(accounts)
    real_intakes=len(intakes)
    def rate(numerator:int,denominator:int)->float:
        return round((numerator/denominator)*100,1) if denominator else 0.0
    return {'status':'ok','scope':actor['role'],'total_accounts':total_accounts,'prospects':len(prospects),'outreach_events':len(outreach_events),'replied':len(replied),'follow_up_due':len(follow_up),'do_not_contact':len(do_not_contact),'real_intakes':real_intakes,'qualified_intakes':len(qualified),'promoted_intakes':len(promoted),'conversion':{'account_to_intake_pct':rate(real_intakes,total_accounts),'intake_to_qualified_pct':rate(len(qualified),real_intakes),'qualified_to_promoted_pct':rate(len(promoted),len(qualified)),'account_to_promoted_pct':rate(len(promoted),total_accounts)},'next_actions':['Work follow-up-due prospects' if follow_up else 'Capture replies and new trade requirements','Qualify new intakes' if real_intakes>len(qualified) else 'Generate more qualified demand','Promote qualified intakes into sourcing' if len(qualified)>len(promoted) else 'Build sourcing pipeline from promoted demand']}

@app.post('/crm/intake')
async def public_intake(p:IntakeIn):
    backend=get_backend(); ts=now(); email=p.email
    existing=await backend.select('customer_accounts',params={'email':f'eq.{email}','limit':'1'}) or []
    if existing:
        customer_id=existing[0]['customer_id']
        await backend.patch('customer_accounts',{'legal_name':p.legal_name,'trade_name':p.trade_name,'contact_name':p.contact_name,'phone':p.phone,'country_code':(p.country_code or '').upper() or None,'website':p.website,'sales_status':'REPLIED','updated_at':ts},params={'customer_id':f'eq.{customer_id}'})
    else:
        customer_id=f'cus_{secrets.token_urlsafe(10)}'
        await backend.insert('customer_accounts',{'customer_id':customer_id,'legal_name':p.legal_name,'trade_name':p.trade_name,'contact_name':p.contact_name,'email':email,'phone':p.phone,'country_code':(p.country_code or '').upper() or None,'website':p.website,'status':'PROSPECT','sales_status':'REPLIED','source':'WEB','created_at':ts,'updated_at':ts})
    intake_id=f'int_{secrets.token_urlsafe(10)}'
    row={'intake_id':intake_id,'customer_id':customer_id,'product_need':p.product_need,'specifications':p.specifications,'quantity':p.quantity,'target_budget':p.target_budget,'currency':p.currency.upper(),'destination_country':p.destination_country.upper(),'target_delivery_date':p.target_delivery_date,'preferred_incoterm':p.preferred_incoterm,'notes':p.notes,'status':'NEW','qualification_status':'PENDING','created_at':ts,'updated_at':ts}
    await backend.insert('customer_trade_intakes',row)
    await audit({'role':'customer','id':customer_id},'intake_created','Customer submitted a new trade sourcing request',customer_id,intake_id)
    return {'intake':row,'customer':{'customer_id':customer_id,'legal_name':p.legal_name,'contact_name':p.contact_name,'email':email}}

@app.get('/crm/customers')
async def list_customers(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    await ensure_campaign_bootstrap()
    params={'order':'updated_at.desc','limit':'250'}
    if actor['role']=='employee': params['assigned_employee_id']=f'eq.{actor["id"]}'
    return {'customers':await get_backend().select('customer_accounts',params=params) or []}

@app.patch('/crm/prospects/{customer_id}/status')
async def update_prospect_status(customer_id:str,p:ProspectStatusIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    backend=get_backend()
    rows=await backend.select('customer_accounts',params={'customer_id':f'eq.{customer_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Prospect not found')
    values={'sales_status':p.status,'next_follow_up_at':p.next_follow_up_at,'updated_at':now()}
    if actor['role']=='employee' and not rows[0].get('assigned_employee_id'): values['assigned_employee_id']=actor['id']
    await backend.patch('customer_accounts',values,params={'customer_id':f'eq.{customer_id}'})
    await audit(actor,'prospect_status_changed',f'Prospect sales status -> {p.status}',customer_id,payload={'status':p.status,'next_follow_up_at':p.next_follow_up_at,'notes':p.notes})
    return {'customer_id':customer_id,'sales_status':p.status,'next_follow_up_at':p.next_follow_up_at}

@app.post('/crm/prospects/{customer_id}/intake')
async def create_intake_from_prospect(customer_id:str,p:ProspectIntakeIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    backend=get_backend(); ts=now()
    accounts=await backend.select('customer_accounts',params={'customer_id':f'eq.{customer_id}','limit':'1'}) or []
    if not accounts: raise HTTPException(404,'Prospect not found')
    intake_id=f'int_{secrets.token_urlsafe(10)}'
    row={'intake_id':intake_id,'customer_id':customer_id,'product_need':p.product_need,'specifications':p.specifications,'quantity':p.quantity,'target_budget':p.target_budget,'currency':p.currency.upper(),'destination_country':p.destination_country.upper(),'target_delivery_date':p.target_delivery_date,'preferred_incoterm':p.preferred_incoterm,'notes':p.notes,'status':'NEW','qualification_status':'PENDING','assigned_employee_id':actor['id'] if actor['role']=='employee' else accounts[0].get('assigned_employee_id'),'created_at':ts,'updated_at':ts}
    await backend.insert('customer_trade_intakes',row)
    await backend.patch('customer_accounts',{'sales_status':'QUALIFIED_LEAD','updated_at':ts},params={'customer_id':f'eq.{customer_id}'})
    await audit(actor,'intake_created_from_prospect','Trade requirement captured from prospect reply',customer_id,intake_id,{'source':'staff_capture'})
    return {'intake':row,'customer_id':customer_id}

@app.get('/crm/intakes')
async def list_intakes(x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    await ensure_campaign_bootstrap()
    backend=get_backend()
    params={'order':'updated_at.desc','limit':'250'}
    if actor['role']=='employee': params['assigned_employee_id']=f'eq.{actor["id"]}'
    intakes=await backend.select('customer_trade_intakes',params=params) or []
    accounts=await backend.select('customer_accounts',params=params) or []
    intake_customer_ids={row.get('customer_id') for row in intakes}
    prospects=[]
    for account in accounts:
        if account.get('customer_id') in intake_customer_ids: continue
        prospects.append({'intake_id':f"prospect:{account.get('customer_id')}",'customer_id':account.get('customer_id'),'legal_name':account.get('legal_name'),'trade_name':account.get('trade_name'),'contact_name':account.get('contact_name'),'email':account.get('email'),'phone':account.get('phone'),'country_code':account.get('country_code'),'website':account.get('website'),'product_need':'Outreach prospect — awaiting trade requirement','destination_country':account.get('country_code') or 'CU','status':account.get('sales_status') or account.get('status') or 'PROSPECT','qualification_status':'PENDING','source':account.get('source'),'next_follow_up_at':account.get('next_follow_up_at'),'created_at':account.get('created_at'),'updated_at':account.get('updated_at'),'prospect_only':True})
    external_rows=[]
    try:
        external=await backend.select('external_trade_prospects',params={'organization_id':'eq.org_sahjony_global_trade','order':'updated_at.desc','limit':'5000'}) or []
        for row in external:
            item=dict(row)
            item.update({
                'intake_id':f"external:{row.get('id')}",
                'legal_name':row.get('buyer_company') or row.get('buyer_name') or row.get('opportunity_title'),
                'trade_name':row.get('buyer_company'),
                'contact_name':row.get('buyer_name'),
                'country_code':row.get('buyer_country'),
                'website':row.get('source_url'),
                'product_need':row.get('product_description') or row.get('opportunity_title') or 'External trade research prospect',
                'destination_country':row.get('buyer_country') or row.get('destination') or 'CU',
                'status':row.get('qualification_stage') or 'RESEARCH',
                'qualification_status':row.get('verification_status') or 'UNVERIFIED',
                'source':row.get('source_platform') or row.get('source_type') or 'EXTERNAL_RESEARCH',
                'prospect_only':True,'external_research':True,'read_only':True,
            })
            external_rows.append(item)
    except Exception:
        external_rows=[]
    combined=intakes+prospects+external_rows
    combined.sort(key=lambda row: row.get('updated_at') or row.get('source_checked_at') or row.get('created_at') or '',reverse=True)
    return {'intakes':combined[:5000],'real_intake_count':len(intakes),'prospect_count':len(prospects),'external_research_count':len(external_rows),'record_count':len(combined)}

@app.patch('/crm/intakes/{intake_id}/qualify')
async def qualify(intake_id:str,p:QualifyIn,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if intake_id.startswith('prospect:') or intake_id.startswith('external:'): raise HTTPException(409,'Research/prospect record has not submitted a trade intake yet')
    rows=await get_backend().select('customer_trade_intakes',params={'intake_id':f'eq.{intake_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Intake not found')
    assigned=p.assigned_employee_id or (actor['id'] if actor['role']=='employee' else rows[0].get('assigned_employee_id'))
    values={'qualification_status':p.status,'status':'QUALIFIED' if p.status=='QUALIFIED' else ('NEEDS_INFO' if p.status=='NEEDS_INFO' else 'CLOSED'),'assigned_employee_id':assigned,'updated_at':now()}
    await get_backend().patch('customer_trade_intakes',values,params={'intake_id':f'eq.{intake_id}'})
    if assigned: await get_backend().patch('customer_accounts',{'assigned_employee_id':assigned,'status':'ACTIVE' if p.status=='QUALIFIED' else 'PROSPECT','updated_at':now()},params={'customer_id':f'eq.{rows[0]["customer_id"]}'})
    await audit(actor,'intake_qualified',f'Intake qualification -> {p.status}',rows[0]['customer_id'],intake_id,{'notes':p.notes,'assigned_employee_id':assigned})
    return {'intake_id':intake_id,'qualification_status':p.status,'assigned_employee_id':assigned}

@app.post('/crm/intakes/{intake_id}/promote')
async def promote(intake_id:str,x_role:str|None=Header(None,alias='X-Role'),authorization:str|None=Header(None,alias='Authorization'),x_employee_id:str|None=Header(None,alias='X-Employee-Id')):
    actor=identity(x_role,authorization,x_employee_id)
    if intake_id.startswith('prospect:') or intake_id.startswith('external:'): raise HTTPException(409,'Research/prospect record has not submitted a trade intake yet')
    backend=get_backend(); rows=await backend.select('customer_trade_intakes',params={'intake_id':f'eq.{intake_id}','limit':'1'}) or []
    if not rows: raise HTTPException(404,'Intake not found')
    row=rows[0]
    if row.get('qualification_status')!='QUALIFIED': raise HTTPException(409,'Only QUALIFIED customer intakes may enter managed trade')
    if row.get('managed_trade_request_id'): return {'intake_id':intake_id,'managed_trade_request_id':row.get('managed_trade_request_id'),'sourcing_request_id':row.get('sourcing_request_id'),'already_promoted':True}
    ts=now(); mtr=f'mtr_{secrets.token_urlsafe(10)}'; gsr=f'gsr_{secrets.token_urlsafe(10)}'
    common={'product_need':row['product_need'],'specifications':row.get('specifications'),'quantity':row.get('quantity'),'target_budget':row.get('target_budget'),'currency':row.get('currency') or 'USD','destination_country':row.get('destination_country'),'target_delivery_date':row.get('target_delivery_date')}
    await backend.insert('managed_trade_requests',{'request_id':mtr,'requester_type':'BUYER','requester_ref':row['customer_id'],'private_business_id':None,'employee_id':row.get('assigned_employee_id'),'assigned_owner_id':'owner','assigned_employee_id':row.get('assigned_employee_id'),**common,'status':'INTAKE','created_at':ts,'updated_at':ts})
    await backend.insert('global_sourcing_requests',{'sourcing_request_id':gsr,'requester_type':'BUYER','requester_ref':row['customer_id'],**common,'worldwide_search':True,'status':'SEARCHING','assigned_owner_id':'owner','assigned_employee_id':row.get('assigned_employee_id'),'created_at':ts,'updated_at':ts})
    await backend.patch('customer_trade_intakes',{'status':'PROMOTED','managed_trade_request_id':mtr,'sourcing_request_id':gsr,'updated_at':ts},params={'intake_id':f'eq.{intake_id}'})
    await audit(actor,'intake_promoted','Qualified customer intake promoted into Managed Trade and Worldwide Sourcing',row['customer_id'],intake_id,{'managed_trade_request_id':mtr,'sourcing_request_id':gsr})
    return {'intake_id':intake_id,'managed_trade_request_id':mtr,'sourcing_request_id':gsr,'already_promoted':False}
