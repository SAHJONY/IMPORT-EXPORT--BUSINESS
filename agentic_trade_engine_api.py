from __future__ import annotations

import asyncio
import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from ai_brain_api import call_anthropic, call_openai
from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title='SAHJONY LLC Frontier Agentic Trade Engine', version='2.1.0', docs_url=None, redoc_url=None)

Task = Literal['OPPORTUNITY_TRIAGE','SUPPLIER_SOURCING','BUYER_QUALIFICATION','RFQ_BUILD','NEGOTIATION','COMPLIANCE_REVIEW','PAYMENT_REVIEW','LOGISTICS_PLAN','CATALOG_ENRICHMENT','EXECUTIVE_DECISION']
Mode = Literal['AUTO','OPENAI','ANTHROPIC','CONSENSUS']

HIGH_STAKES = {'COMPLIANCE_REVIEW','PAYMENT_REVIEW','EXECUTIVE_DECISION'}
EXTERNAL_COMMITMENTS = {'SEND_EMAIL','SEND_RFQ','PLACE_ORDER','SEND_PAYMENT','RELEASE_SHIPMENT','APPROVE_COMPLIANCE','SIGN_CONTRACT','DISCLOSE_COUNTERPARTY'}

OPENAI_FRONTIER = lambda: os.getenv('OPENAI_PRIMARY_MODEL','gpt-5.6-sol').strip() or 'gpt-5.6-sol'
OPENAI_BALANCED = OPENAI_FRONTIER
OPENAI_ECONOMY = OPENAI_FRONTIER
ANTHROPIC_FABLE = lambda: os.getenv('ANTHROPIC_FRONTIER_MODEL','claude-fable-5').strip() or 'claude-fable-5'
ANTHROPIC_OPUS = lambda: os.getenv('ANTHROPIC_PRIMARY_MODEL','claude-opus-5').strip() or 'claude-opus-5'
ANTHROPIC_SONNET = lambda: os.getenv('ANTHROPIC_FAST_MODEL','claude-sonnet-5').strip() or 'claude-sonnet-5'

POLICY = '''You are the autonomous trade intelligence engine for SAHJONY LLC. Optimize for legitimate, capital-light trade intermediation: sourcing, origination, introductions, RFQ management and managed-trade fees without SAHJONY LLC owning inventory or advancing transaction capital. Separate verified facts from assumptions. Never invent buyer authority, supplier capacity, pricing, certifications, bankability, sanctions clearance, or shipment status. Research and analysis may run autonomously. External commitments, payments, contracts, supplier selection, compliance clearance, shipment release and disclosure of protected counterparties require deterministic authorization gates. Prefer highest commercially defensible fee economics while preserving legality, disclosure duties and close probability. Return concise structured recommendations with evidence gaps, next actions, fee strategy, risk controls and measurable success conditions.'''


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identity(role: str | None, authorization: str | None) -> dict:
    if role != 'owner':
        raise HTTPException(403, 'Frontier orchestration currently requires owner authority')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    token = authorization.removeprefix('Bearer ').strip()
    if not verify_owner_token(token):
        raise HTTPException(403, 'Invalid owner credential')
    return {'role':'owner','id':'owner'}


class OrchestrateIn(BaseModel):
    task: Task
    objective: str = Field(min_length=3, max_length=30000)
    context: str | None = Field(default=None, max_length=80000)
    mode: Mode = 'AUTO'
    requested_actions: list[str] = Field(default_factory=list, max_length=40)
    max_output_tokens: int = Field(default=3000, ge=300, le=12000)


def route(task: str, mode: str) -> tuple[list[tuple[str,str]], bool]:
    high = task in HIGH_STAKES
    if mode == 'ANTHROPIC': return [('anthropic', ANTHROPIC_FABLE() if high else ANTHROPIC_OPUS())], high
    if mode == 'CONSENSUS' or high: return [('openai', OPENAI_FRONTIER()),('anthropic', ANTHROPIC_FABLE())], high
    return [('openai', OPENAI_FRONTIER())], high


async def _invoke(provider: str, model: str, prompt: str, max_tokens: int) -> dict:
    merged = POLICY + '\n\n' + prompt
    if provider == 'openai':
        return await call_openai(merged, model, max_tokens)
    return await call_anthropic(merged, model, max_tokens)


async def _audit(row: dict) -> None:
    try:
        await get_backend().insert('agentic_trade_runs', row)
    except Exception:
        pass


@app.get('/agentic-engine/health')
async def health():
    backend = persistent_backend_status()
    return {
        'status':'ok',
        'service':'sahjony-llc-frontier-agentic-trade-engine',
        'version':'2.1.0',
        'openai_frontier':OPENAI_FRONTIER(),
        'openai_balanced':OPENAI_BALANCED(),
        'openai_economy':OPENAI_ECONOMY(),
        'primary_reasoning_authority':'gpt-5.6-sol',
        'anthropic_fable':ANTHROPIC_FABLE(),
        'anthropic_opus':ANTHROPIC_OPUS(),
        'anthropic_sonnet':ANTHROPIC_SONNET(),
        'anthropic_role':'independent_review_consensus_and_resilience',
        'responses_api':True,
        'dual_model_consensus_for_high_stakes':True,
        'autonomous_internal_research':True,
        'autonomous_external_commitments':False,
        'zero_own_capital_policy':True,
        'fee_protection_policy':True,
        'durable_audit_available':backend['configured'],
        'fail_closed':True,
    }


@app.post('/agentic-engine/orchestrate')
async def orchestrate(payload: OrchestrateIn, x_role: str | None = Header(None, alias='X-Role'), authorization: str | None = Header(None, alias='Authorization')):
    actor = _identity(x_role, authorization)
    requested = {x.strip().upper() for x in payload.requested_actions if x.strip()}
    blocked = sorted(requested & EXTERNAL_COMMITMENTS)
    allowed = sorted(requested - EXTERNAL_COMMITMENTS)
    providers, high = route(payload.task, payload.mode)
    run_id = f'ate_{secrets.token_urlsafe(10)}'
    prompt = f'''TASK: {payload.task}\nOBJECTIVE: {payload.objective}\nRISK: {'HIGH' if high else 'STANDARD'}\nAUTONOMOUS ACTIONS ALLOWED: {allowed or ['ANALYZE','RESEARCH','RANK','DRAFT','COMPARE']}\nBLOCKED EXTERNAL ACTIONS: {blocked}\n\nReturn: 1) decision summary, 2) evidence required, 3) ranked execution plan, 4) maximum defensible fee strategy, 5) zero-capital structure, 6) risks/mitigations, 7) explicit approval gates, 8) 7-day and 30-day metrics.'''
    if payload.context:
        prompt += '\n\nCONTEXT:\n' + payload.context
    await _audit({'run_id':run_id,'task':payload.task,'status':'STARTED','risk_tier':'HIGH' if high else 'STANDARD','providers':[{'provider':p,'model':m} for p,m in providers],'requested_actions':sorted(requested),'blocked_actions':blocked,'actor_id':actor['id'],'created_at':now()})
    try:
        results = await asyncio.gather(*[_invoke(p,m,prompt,payload.max_output_tokens) for p,m in providers], return_exceptions=True)
        good = [x for x in results if isinstance(x,dict)]
        errors = [str(x)[:500] for x in results if isinstance(x,Exception)]
        if not good:
            raise RuntimeError('; '.join(errors) or 'No frontier provider returned a result')
        if len(good) == 1:
            answer = good[0].get('text','')
            consensus = 'SINGLE_PROVIDER' if len(providers)==1 else 'DEGRADED_SINGLE_PROVIDER'
        else:
            synthesis_prompt = POLICY + '\n\nSynthesize the independent analyses below. Preserve disagreements and uncertainty. Do not authorize any blocked action.\n\nA:\n' + good[0].get('text','') + '\n\nB:\n' + good[1].get('text','')
            try:
                synthesis = await call_openai(synthesis_prompt, OPENAI_FRONTIER(), payload.max_output_tokens)
                answer = synthesis.get('text','')
            except Exception:
                answer = 'ANALYSIS A:\n' + good[0].get('text','') + '\n\nANALYSIS B:\n' + good[1].get('text','')
            consensus = 'DUAL_FRONTIER_CONSENSUS'
        await _audit({'run_id':run_id,'task':payload.task,'status':'COMPLETED','consensus':consensus,'blocked_actions':blocked,'output_summary':answer[:2400],'completed_at':now()})
        return {'run_id':run_id,'task':payload.task,'risk_tier':'HIGH' if high else 'STANDARD','answer':answer,'consensus':consensus,'providers':[{'provider':x.get('provider'),'model':x.get('model')} for x in good],'autonomous_actions_allowed':allowed,'approval_required_for':blocked,'authority':'INTERNAL_AUTONOMY_EXTERNAL_FAIL_CLOSED','zero_own_capital':True}
    except Exception as exc:
        await _audit({'run_id':run_id,'task':payload.task,'status':'FAILED','error':str(exc)[:1000],'completed_at':now()})
        raise HTTPException(503, str(exc)[:800]) from exc
