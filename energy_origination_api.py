from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY Energy Global Origination', version='1.0.0', docs_url=None, redoc_url=None)

TargetRole = Literal['BUYER','REFINERY','SELLER','PRODUCER','TRADER','MANDATE','TERMINAL','BROKER']

MARKETS = {
    'US': {'name':'United States','side':['BUYER','REFINERY','TRADER','TERMINAL'],'grades':['WTI','WTI MIDLAND','MARS','LLS','WCS'],'hubs':['Houston','Corpus Christi','Cushing','Louisiana Gulf Coast']},
    'CA': {'name':'Canada','side':['SELLER','PRODUCER','TRADER','BUYER'],'grades':['WCS','SYNCRUDE','LIGHT SWEET'],'hubs':['Alberta','Hardisty','Vancouver']},
    'MX': {'name':'Mexico','side':['SELLER','PRODUCER','BUYER','REFINERY'],'grades':['MAYA','ISTHMUS','OLMECA'],'hubs':['Dos Bocas','Salina Cruz','Tuxpan']},
    'BR': {'name':'Brazil','side':['SELLER','PRODUCER','BUYER','TRADER'],'grades':['TUPI','BUZIOS','MERO','OTHER'],'hubs':['Santos Basin','Rio de Janeiro','Acu']},
    'GY': {'name':'Guyana','side':['SELLER','PRODUCER','TRADER'],'grades':['LIZA','UNITY GOLD','PAYARA GOLD'],'hubs':['Stabroek Block','Georgetown']},
    'NG': {'name':'Nigeria','side':['SELLER','PRODUCER','TRADER','MANDATE'],'grades':['BONNY LIGHT','QUA IBOE','FORCADOS','ESCRAVOS'],'hubs':['Bonny','Forcados','Qua Iboe','Lagos']},
    'AO': {'name':'Angola','side':['SELLER','PRODUCER','TRADER'],'grades':['CABINDA','DALIA','GIRASSOL'],'hubs':['Luanda','Cabinda']},
    'DZ': {'name':'Algeria','side':['SELLER','PRODUCER','TRADER'],'grades':['SAHARAN BLEND'],'hubs':['Arzew','Skikda']},
    'SA': {'name':'Saudi Arabia','side':['SELLER','PRODUCER','TRADER'],'grades':['ARAB LIGHT','ARAB MEDIUM','ARAB HEAVY'],'hubs':['Ras Tanura','Yanbu']},
    'AE': {'name':'United Arab Emirates','side':['SELLER','PRODUCER','TRADER','BUYER'],'grades':['MURBAN','DAS','UPPER ZAKUM'],'hubs':['Fujairah','Jebel Dhanna','Abu Dhabi']},
    'OM': {'name':'Oman','side':['SELLER','PRODUCER','TRADER'],'grades':['OMAN'],'hubs':['Mina Al Fahal','Duqm']},
    'IQ': {'name':'Iraq','side':['SELLER','PRODUCER','TRADER'],'grades':['BASRAH LIGHT','BASRAH MEDIUM','KIRKUK'],'hubs':['Basra','Ceyhan']},
    'KZ': {'name':'Kazakhstan','side':['SELLER','PRODUCER','TRADER'],'grades':['CPC BLEND','KEBCO'],'hubs':['Tengiz','Novorossiysk corridor']},
    'AZ': {'name':'Azerbaijan','side':['SELLER','PRODUCER','TRADER'],'grades':['AZERI LIGHT'],'hubs':['Baku','Ceyhan']},
    'GB': {'name':'United Kingdom','side':['BUYER','REFINERY','TRADER'],'grades':['BRENT-LINKED','FORTIES'],'hubs':['London','North Sea','Hound Point']},
    'NL': {'name':'Netherlands','side':['BUYER','REFINERY','TRADER','TERMINAL'],'grades':['BRENT-LINKED','WTI','OTHER'],'hubs':['Rotterdam']},
    'SG': {'name':'Singapore','side':['BUYER','REFINERY','TRADER','TERMINAL'],'grades':['DUBAI','OMAN','MURBAN','ESPO','OTHER'],'hubs':['Singapore']},
    'IN': {'name':'India','side':['BUYER','REFINERY','TRADER'],'grades':['DUBAI','OMAN','MURBAN','BASRAH MEDIUM','OTHER'],'hubs':['Jamnagar','Mundra','Vadinar','Mumbai']},
    'CN': {'name':'China','side':['BUYER','REFINERY','TRADER'],'grades':['ESPO','MURBAN','OMAN','BASRAH MEDIUM','OTHER'],'hubs':['Shandong','Ningbo','Zhoushan','Dalian']},
    'KR': {'name':'South Korea','side':['BUYER','REFINERY','TRADER'],'grades':['MURBAN','ARAB LIGHT','DUBAI','OTHER'],'hubs':['Ulsan','Yeosu','Daesan']},
    'JP': {'name':'Japan','side':['BUYER','REFINERY','TRADER'],'grades':['MURBAN','ARAB LIGHT','DUBAI','OTHER'],'hubs':['Chiba','Yokohama','Mizushima']},
}

SOURCE_CLASSES = [
    'national oil company and producer websites',
    'refinery and downstream company websites',
    'recognized commodity trading company websites',
    'port, terminal and storage operator directories',
    'energy ministry and petroleum regulator records',
    'stock exchange and securities filings',
    'company registries and beneficial ownership evidence where lawful',
    'recognized industry associations and conference exhibitor lists',
    'public procurement, tender and refinery crude slate disclosures',
]


def now() -> str: return datetime.now(timezone.utc).isoformat()

def owner(auth: str | None):
    if not auth or not auth.startswith('Bearer '): raise HTTPException(401,'Missing Authorization')
    if not verify_owner_token(auth.removeprefix('Bearer ').strip()): raise HTTPException(403,'Invalid or expired owner session')


def market(code: str) -> dict:
    c = code.strip().upper()
    if c not in MARKETS: raise HTTPException(404,'Energy market profile not configured')
    m = MARKETS[c]
    return {'country_code':c, **m, 'source_classes':SOURCE_CLASSES, 'authority':'RESEARCH_AND_QUALIFICATION_ONLY'}


class JobIn(BaseModel):
    country_code: str = Field(min_length=2,max_length=2)
    roles: list[TargetRole] = Field(default_factory=list,max_length=8)
    grades: list[str] = Field(default_factory=list,max_length=30)
    target_count: int = Field(default=25,ge=1,le=500)
    minimum_evidence_score: int = Field(default=70,ge=0,le=100)
    notes: str | None = Field(default=None,max_length=4000)


class CandidateIn(BaseModel):
    job_id: str | None = Field(default=None,max_length=180)
    legal_name: str = Field(min_length=2,max_length=240)
    country_code: str = Field(min_length=2,max_length=2)
    role: TargetRole
    website: str | None = Field(default=None,max_length=1200)
    contact_name: str | None = Field(default=None,max_length=160)
    email: str | None = Field(default=None,max_length=320)
    phone: str | None = Field(default=None,max_length=100)
    crude_grades: list[str] = Field(default_factory=list,max_length=30)
    refinery_capacity_bpd: float | None = Field(default=None,ge=0)
    production_capacity_bpd: float | None = Field(default=None,ge=0)
    source_url: str = Field(min_length=8,max_length=1200)
    evidence_urls: list[str] = Field(default_factory=list,max_length=20)
    registration_reference: str | None = Field(default=None,max_length=300)
    evidence_score: int = Field(default=60,ge=0,le=100)
    notes: str | None = Field(default=None,max_length=4000)


def fp(p: CandidateIn) -> str:
    basis='|'.join([p.legal_name.strip().lower(),p.country_code.upper(),p.role,(p.website or '').strip().lower(),(p.email or '').strip().lower()])
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


def quality(p: CandidateIn) -> tuple[int,list[str]]:
    score=int(p.evidence_score); gaps=[]
    if p.website: score+=5
    else: gaps.append('website')
    if p.registration_reference: score+=8
    else: gaps.append('registration_reference')
    if p.email: score+=4
    else: gaps.append('business_email')
    if p.evidence_urls: score+=min(12,len(p.evidence_urls)*3)
    else: gaps.append('supporting_evidence')
    if p.crude_grades: score+=4
    return min(100,score),gaps


@app.get('/energy-origination/health')
async def health():
    p=persistent_backend_status()
    return {'status':'ok' if p['configured'] else 'configuration_required','service':'energy-global-origination','markets':len(MARKETS),'source_classes':len(SOURCE_CLASSES),'durable_jobs':p['configured'],'automatic_outbound_commitment':False,'automatic_counterparty_approval':False,'fail_closed':True}

@app.get('/energy-origination/markets')
async def markets(authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); return {'markets':[market(c) for c in MARKETS]}

@app.get('/energy-origination/markets/{code}')
async def market_detail(code: str, authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); return market(code)

@app.post('/energy-origination/jobs')
async def create_job(p: JobIn, authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); m=market(p.country_code); jid=f'eoj_{secrets.token_urlsafe(12)}'; ts=now()
    roles=p.roles or m['side']; grades=p.grades or m['grades']
    row={'job_id':jid,'country_code':m['country_code'],'country_name':m['name'],'roles':roles,'grades':grades,'hubs':m['hubs'],'source_classes':SOURCE_CLASSES,'target_count':p.target_count,'minimum_evidence_score':p.minimum_evidence_score,'notes':p.notes,'status':'RESEARCH_QUEUED','candidate_count':0,'accepted_count':0,'authority':'RESEARCH_AND_QUALIFICATION_ONLY','created_at':ts,'updated_at':ts}
    await get_backend().insert('energy_origination_jobs',row); return {'job':row,'market_brief':m}

@app.get('/energy-origination/jobs')
async def jobs(authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); return {'jobs':await get_backend().select('energy_origination_jobs',params={'order':'updated_at.desc','limit':'500'}) or []}

@app.post('/energy-origination/candidates')
async def candidate(p: CandidateIn, authorization: str|None=Header(None,alias='Authorization')):
    owner(authorization); backend=get_backend(); m=market(p.country_code); fingerprint=fp(p); score,gaps=quality(p)
    existing=await backend.select('energy_counterparties',params={'fingerprint':f'eq.{fingerprint}','limit':'1'}) or []
    duplicate=existing[0].get('counterparty_id') if existing else None
    cid=f'enc_{secrets.token_urlsafe(12)}'; ts=now()
    row={'counterparty_id':cid,'fingerprint':fingerprint,'legal_name':p.legal_name,'country':m['name'],'country_code':m['country_code'],'role':p.role,'website':p.website,'contact_name':p.contact_name,'email':(p.email or '').strip().lower() or None,'phone':p.phone,'registration_reference':p.registration_reference,'beneficial_owner_summary':None,'evidence_urls':[p.source_url,*p.evidence_urls],'crude_grades':p.crude_grades,'refinery_capacity_bpd':p.refinery_capacity_bpd,'production_capacity_bpd':p.production_capacity_bpd,'source_url':p.source_url,'evidence_score':score,'evidence_gaps':gaps,'status':'DUPLICATE_REVIEW' if duplicate else 'UNVERIFIED','duplicate_of_counterparty_id':duplicate,'kyb_status':'PENDING','screening_status':'PENDING','bankability_status':'PENDING','origination_job_id':p.job_id,'notes':p.notes,'created_by':'SAHJONY Energy Origination Agent','created_at':ts,'updated_at':ts}
    await backend.insert('energy_counterparties',row)
    await backend.insert('energy_audit_events',{'event_id':f'ena_{secrets.token_urlsafe(12)}','deal_id':None,'counterparty_id':cid,'actor_role':'owner','actor_id':'owner','event_type':'origination_candidate_ingested','summary':f'{p.role} candidate routed into SAHJONY Energy CRM','payload':{'country_code':m['country_code'],'score':score,'duplicate':bool(duplicate),'job_id':p.job_id},'created_at':ts})
    if p.job_id:
        rows=await backend.select('energy_origination_jobs',params={'job_id':f'eq.{p.job_id}','limit':'1'}) or []
        if rows:
            j=rows[0]; await backend.patch('energy_origination_jobs',{'candidate_count':int(j.get('candidate_count') or 0)+1,'accepted_count':int(j.get('accepted_count') or 0)+(0 if duplicate else 1),'status':'CANDIDATES_FOUND','updated_at':ts},params={'job_id':f'eq.{p.job_id}'})
    return {'counterparty_id':cid,'country_code':m['country_code'],'evidence_score':score,'evidence_gaps':gaps,'duplicate_candidate':bool(duplicate),'duplicate_of_counterparty_id':duplicate,'status':row['status']}
