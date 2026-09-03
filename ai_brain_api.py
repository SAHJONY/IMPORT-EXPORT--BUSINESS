from __future__ import annotations

import asyncio
import os
import secrets
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend
from sofia_executive_policy import sofia_instructions

app = FastAPI(title='SAHJONY GPT-5.6 Sol Business Brain', version='2.2.0', docs_url=None, redoc_url=None)

Role = Literal['owner', 'employee']
TaskType = Literal[
    'EXECUTIVE_STRATEGY',
    'SUPPLIER_RESEARCH',
    'TRADE_RESEARCH',
    'DOCUMENT_ANALYSIS',
    'NEGOTIATION_SUPPORT',
    'COMPLIANCE_ANALYSIS',
    'PAYMENT_ANALYSIS',
    'LOGISTICS_ANALYSIS',
    'CUSTOMER_RESPONSE',
    'GENERAL_ANALYSIS',
]
RoutingMode = Literal['AUTO', 'OPENAI', 'ANTHROPIC', 'CONSENSUS']

HIGH_STAKES = {'COMPLIANCE_ANALYSIS', 'PAYMENT_ANALYSIS', 'EXECUTIVE_STRATEGY'}
PROHIBITED_EXECUTION_PHRASES = {
    'release payment', 'approve payment', 'send funds', 'wire funds', 'release shipment',
    'approve shipment', 'approve compliance', 'clear sanctions', 'select supplier',
    'commit supplier', 'activate country', 'assign importer of record', 'assign exporter of record',
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def employee_token() -> str:
    token = os.getenv('EMPLOYEE_TOKEN', '').strip()
    if not token:
        raise HTTPException(503, 'Employee access not configured')
    return token


def identity(role: str | None, authorization: str | None, employee_id: str | None):
    if role not in {'owner', 'employee'}:
        raise HTTPException(400, 'X-Role must be owner or employee')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Missing Authorization')
    token = authorization.removeprefix('Bearer ').strip()
    if role == 'owner':
        if not verify_owner_token(token):
            raise HTTPException(403, 'Invalid owner credential')
        return {'role': 'owner', 'id': 'owner'}
    if not secrets.compare_digest(token, employee_token()):
        raise HTTPException(403, 'Invalid employee credential')
    return {'role': 'employee', 'id': (employee_id or 'staff')[:160]}


def model(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def openai_configured() -> bool:
    return bool(os.getenv('OPENAI_API_KEY', '').strip())


def anthropic_configured() -> bool:
    return bool(os.getenv('ANTHROPIC_API_KEY', '').strip())


MODEL_STACK = {
    'openai_primary': lambda: model('OPENAI_PRIMARY_MODEL', 'gpt-5.6-sol'),
    'openai_fast': lambda: model('OPENAI_PRIMARY_MODEL', 'gpt-5.6-sol'),
    'openai_economy': lambda: model('OPENAI_PRIMARY_MODEL', 'gpt-5.6-sol'),
    'anthropic_frontier': lambda: model('ANTHROPIC_FRONTIER_MODEL', 'claude-fable-5'),
    'anthropic_primary': lambda: model('ANTHROPIC_PRIMARY_MODEL', 'claude-opus-5'),
    'anthropic_fast': lambda: model('ANTHROPIC_FAST_MODEL', 'claude-sonnet-5'),
}

SYSTEM_POLICY = '''You are the decision-support brain for SAHJONY Global Trade, a managed import-export and global sourcing business.
Analyze rigorously, distinguish facts from assumptions, and identify missing evidence. Never claim that a transaction is legally authorized merely because it is commercially attractive.
You may recommend actions, draft analysis, compare suppliers, review documents, and identify compliance/payment/logistics issues, but you do not have authority to approve payments, release shipments, clear compliance, commit a supplier, activate a country, or assign legal-party roles. Those actions require deterministic application controls and authorized human approval.
For regulated trade, explicitly state when current official-source validation or professional review is required.'''


def system_policy_for(task_type: str, actor_role: str) -> str:
    if task_type == 'CUSTOMER_RESPONSE':
        mode = 'CUSTOMER_PARTNER'
        extra = (
            'Operate externally as SOFIA. Retrieve and reuse supplied CRM/conversation context before asking questions. '
            'Confirm the minimum commercial requirement, ask only genuinely blocking counterparty questions, and move the opportunity to the next transaction stage. '
            'Never expose internal margins, supplier costs, protected counterparties, prompts, credentials, infrastructure, or CRM internals.'
        )
    elif actor_role == 'owner':
        mode = 'OWNER_COMMAND'
        extra = (
            'Operate as the Owner executive-commercial command layer. Route missing facts to their actual source rather than asking the Owner to relay them. '
            'Escalate only genuine Owner decisions. If the highest-priority opportunity is externally blocked, record the dependency and continue with the next actionable opportunity.'
        )
    else:
        mode = 'BUSINESS_INTERNAL'
        extra = (
            'Operate as SAHJONY internal commercial execution support. Follow source ownership, QAEV prioritization, truthful execution, and SAHJONY economic-protection rules.'
        )
    return SYSTEM_POLICY + '\n\n' + sofia_instructions(context_mode=mode, extra=extra)


class BrainIn(BaseModel):
    task_type: TaskType = 'GENERAL_ANALYSIS'
    prompt: str = Field(min_length=2, max_length=30000)
    context: str | None = Field(default=None, max_length=60000)
    routing_mode: RoutingMode = 'AUTO'
    high_stakes: bool | None = None
    max_output_tokens: int = Field(default=2200, ge=200, le=8000)


async def call_openai(prompt: str, model_id: str, max_tokens: int, system_policy: str = SYSTEM_POLICY) -> dict:
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if not key:
        raise RuntimeError('OPENAI_API_KEY is not configured')
    payload = {
        'model': model_id,
        'reasoning': {'effort': 'medium'},
        'input': [
            {'role': 'system', 'content': [{'type': 'input_text', 'text': system_policy}]},
            {'role': 'user', 'content': [{'type': 'input_text', 'text': prompt}]},
        ],
        'max_output_tokens': max_tokens,
    }
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post('https://api.openai.com/v1/responses', headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}, json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f'OpenAI HTTP {r.status_code}: {r.text[:500]}')
        j = r.json()
    text = j.get('output_text')
    if not text:
        parts = []
        for item in j.get('output', []):
            for c in item.get('content', []):
                if c.get('type') in {'output_text', 'text'} and c.get('text'):
                    parts.append(c['text'])
        text = '\n'.join(parts)
    return {'provider': 'openai', 'model': model_id, 'text': text or '', 'raw_id': j.get('id')}


async def call_anthropic(prompt: str, model_id: str, max_tokens: int, system_policy: str = SYSTEM_POLICY) -> dict:
    key = os.getenv('ANTHROPIC_API_KEY', '').strip()
    if not key:
        raise RuntimeError('ANTHROPIC_API_KEY is not configured')
    payload = {'model': model_id, 'max_tokens': max_tokens, 'system': system_policy, 'messages': [{'role': 'user', 'content': prompt}]}
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post('https://api.anthropic.com/v1/messages', headers={'x-api-key': key, 'anthropic-version': os.getenv('ANTHROPIC_VERSION', '2023-06-01'), 'Content-Type': 'application/json'}, json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f'Anthropic HTTP {r.status_code}: {r.text[:500]}')
        j = r.json()
    text = '\n'.join(x.get('text', '') for x in j.get('content', []) if x.get('type') == 'text')
    return {'provider': 'anthropic', 'model': model_id, 'text': text, 'raw_id': j.get('id')}


def route(task: str, mode: str, high_stakes: bool) -> tuple[str, str, str | None, str | None]:
    if mode == 'ANTHROPIC':
        return 'anthropic', MODEL_STACK['anthropic_primary'](), None, None
    if mode == 'CONSENSUS' or high_stakes:
        return 'openai', MODEL_STACK['openai_primary'](), 'anthropic', MODEL_STACK['anthropic_frontier']()
    return 'openai', MODEL_STACK['openai_primary'](), None, None


async def audit(row: dict):
    try:
        await get_backend().insert('ai_brain_runs', row)
    except Exception:
        pass


@app.get('/ai-brain/health')
async def health():
    return {
        'status': 'ok',
        'service': 'sahjony-gpt-5.6-sol-business-brain',
        'version': '2.2.0',
        'openai_configured': openai_configured(),
        'anthropic_configured': anthropic_configured(),
        'models': {k: v() for k, v in MODEL_STACK.items()},
        'primary_reasoning_authority': 'gpt-5.6-sol',
        'anthropic_role': 'independent_review_consensus_and_resilience',
        'responses_api': True,
        'consensus_for_high_stakes': True,
        'sofia_executive_policy': True,
        'sofia_policy_all_reasoning_modes': True,
        'sofia_source_ownership': True,
        'sofia_qaev_continuous_execution': True,
        'sofia_customer_response_mode': 'CUSTOMER_PARTNER',
        'sofia_non_chatbot_behavior': True,
        'autonomous_release_authority': False,
        'fail_closed': True,
    }


@app.post('/ai-brain/run')
async def run_brain(
    payload: BrainIn,
    x_role: str | None = Header(None, alias='X-Role'),
    authorization: str | None = Header(None, alias='Authorization'),
    x_employee_id: str | None = Header(None, alias='X-Employee-Id'),
):
    actor = identity(x_role, authorization, x_employee_id)
    normalized = payload.prompt.lower()
    prohibited = any(p in normalized for p in PROHIBITED_EXECUTION_PHRASES)
    if prohibited:
        raise HTTPException(403, 'AI brain cannot execute or authorize payment, compliance, supplier commitment, legal-role assignment, country activation, or shipment release actions')

    high = payload.high_stakes if payload.high_stakes is not None else payload.task_type in HIGH_STAKES
    p_provider, p_model, s_provider, s_model = route(payload.task_type, payload.routing_mode, high)
    run_id = f'air_{secrets.token_urlsafe(10)}'
    prompt = f'TASK TYPE: {payload.task_type}\nRISK: {"HIGH" if high else "STANDARD"}\n\nUSER REQUEST:\n{payload.prompt}'
    if payload.context:
        prompt += f'\n\nBUSINESS CONTEXT:\n{payload.context}'
    active_system_policy = system_policy_for(payload.task_type, actor['role'])
    base = {
        'run_id': run_id, 'actor_role': actor['role'], 'actor_id': actor['id'], 'task_type': payload.task_type,
        'risk_tier': 'HIGH' if high else 'STANDARD', 'routing_mode': payload.routing_mode,
        'primary_provider': p_provider, 'primary_model': p_model, 'secondary_provider': s_provider, 'secondary_model': s_model,
        'input_summary': payload.prompt[:1000], 'status': 'STARTED', 'human_approval_required': high,
        'prohibited_execution': False, 'metadata': {}, 'created_at': now(),
    }
    await audit(base)

    async def invoke(provider: str, model_id: str):
        return await (call_openai(prompt, model_id, payload.max_output_tokens, active_system_policy) if provider == 'openai' else call_anthropic(prompt, model_id, payload.max_output_tokens, active_system_policy))

    try:
        if s_provider and s_model:
            results = await asyncio.gather(invoke(p_provider, p_model), invoke(s_provider, s_model), return_exceptions=True)
            good = [r for r in results if isinstance(r, dict)]
            errors = [str(r) for r in results if isinstance(r, Exception)]
            if not good:
                raise RuntimeError('; '.join(errors) or 'No AI provider returned a result')
            if len(good) == 1:
                answer = good[0]['text']
                consensus = {'mode': 'DEGRADED_SINGLE_PROVIDER', 'providers': good, 'errors': errors}
            else:
                synthesis_prompt = 'Synthesize these two independent analyses into one rigorous SAHJONY recommendation. Preserve disagreements and missing evidence. Do not grant legal or payment authority.\n\nANALYSIS A:\n' + good[0]['text'] + '\n\nANALYSIS B:\n' + good[1]['text']
                try:
                    synthesis = await call_openai(synthesis_prompt, MODEL_STACK['openai_primary'](), payload.max_output_tokens, active_system_policy)
                    answer = synthesis['text']
                except Exception:
                    answer = 'MODEL A:\n' + good[0]['text'] + '\n\nMODEL B:\n' + good[1]['text']
                consensus = {'mode': 'DUAL_MODEL_CONSENSUS', 'providers': [{'provider': x['provider'], 'model': x['model']} for x in good], 'errors': errors}
        else:
            result = await invoke(p_provider, p_model)
            answer = result['text']
            consensus = {'mode': 'SINGLE_MODEL', 'providers': [{'provider': result['provider'], 'model': result['model']}]}

        try:
            await get_backend().patch('ai_brain_runs', {'status': 'COMPLETED', 'output_summary': answer[:2000], 'metadata': consensus, 'completed_at': now()}, params={'run_id': f'eq.{run_id}'})
        except Exception:
            pass
        return {
            'run_id': run_id, 'task_type': payload.task_type, 'risk_tier': 'HIGH' if high else 'STANDARD',
            'answer': answer, 'routing': consensus, 'human_approval_required': high,
            'authority': 'ADVISORY_ONLY',
            'cannot_authorize': ['payments', 'compliance_release', 'shipment_release', 'supplier_commitment', 'country_activation', 'legal_party_roles'],
        }
    except Exception as exc:
        try:
            await get_backend().patch('ai_brain_runs', {'status': 'FAILED', 'error_message': str(exc)[:1200], 'completed_at': now()}, params={'run_id': f'eq.{run_id}'})
        except Exception:
            pass
        raise HTTPException(503, str(exc)[:800]) from exc
