from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

try:
    from sofia_human_conversation_engine import build_sofia_prompt
except Exception:
    def build_sofia_prompt(memory=None):
        return "Write naturally, concisely, truthfully, and never repeat known questions."

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
NVIDIA_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

SOL = "gpt-5.6-sol"
TERRA = "gpt-5.6-terra"
LUNA = "gpt-5.6-luna"

FABLE = "claude-fable-5"
MYTHOS = "claude-mythos-5"
OPUS = "claude-opus-5"
SONNET = "claude-sonnet-5"
ANTHROPIC_FRONTIER = [FABLE, OPUS, SONNET, MYTHOS]

NVIDIA_FALLBACKS = ["nvidia/nemotron-3-nano-30b-a3b", "deepseek-ai/deepseek-v4-flash-0731"]

BASE_SYSTEM = """You are the SAHJONY LLC WhatsApp Sales Brain and commercial execution engine for global B2B import-export.
Convert conversations into qualified, evidence-backed opportunities while preserving trust, compliance, and margin.
You may autonomously detect intent, qualify demand, ask targeted questions, score opportunities, prepare RFQs, recommend supplier/freight/compliance work, draft follow-ups, summarize negotiations, and recommend next actions.
Never invent supplier prices, freight, inventory, certifications, customs requirements, landed cost, or binding terms.
Formal quotes, price commitments, credit terms, contracts, and WON status require verified evidence from the application data layer.
Return strict JSON with: opportunity_score, intent, language, recommended_stage, missing_fields, next_best_action, draft_reply, risk_flags, evidence_required, reasoning_level.
Allowed stages: NEW, ENGAGED, QUALIFYING, QUALIFIED, RFQ_READY, SOURCING, QUOTED, NEGOTIATING, WON, LOST, OPTED_OUT.
Without verified evidence, cap automatic progression at RFQ_READY.
"""


def _system(memory: dict[str, Any] | None = None) -> str:
    return BASE_SYSTEM + "\n\nCUSTOMER-FACING SOFIA POLICY\n" + build_sofia_prompt(memory)


def _openai_key() -> str: return os.getenv("OPENAI_API_KEY", "").strip()
def _anthropic_key() -> str: return os.getenv("ANTHROPIC_API_KEY", "").strip()
def _nvidia_key() -> str: return os.getenv("NVIDIA_API_KEY", "").strip()


def choose_openai_model(complexity: str = "normal") -> tuple[str, str]:
    c = (complexity or "normal").lower()
    if c in {"critical", "complex", "negotiation", "rfq", "sourcing", "compliance", "quote"}: return SOL, "high"
    if c in {"fast", "high_volume", "triage"}: return SOL, "low"
    return SOL, "medium"


def choose_anthropic_models(complexity: str = "normal") -> list[str]:
    c = (complexity or "normal").lower()
    if c in {"critical", "complex", "negotiation", "rfq", "sourcing", "compliance", "quote"}: return [FABLE, OPUS, SONNET, MYTHOS]
    if c in {"fast", "high_volume", "triage"}: return [SONNET, OPUS, FABLE, MYTHOS]
    return [OPUS, FABLE, SONNET, MYTHOS]


def _safe_stage(data: dict[str, Any], current_stage: str) -> dict[str, Any]:
    stage = str(data.get("recommended_stage") or current_stage or "NEW").upper()
    if stage in {"QUOTED", "NEGOTIATING", "WON"}: stage = "RFQ_READY"
    return {**data, "recommended_stage": stage, "binding_commitment_allowed": False, "quote_release_allowed": False}


def _openai_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str) and data["output_text"].strip(): return data["output_text"].strip()
    for item in data.get("output") or []:
        for part in (item.get("content") or []) if isinstance(item, dict) else []:
            text = part.get("text") if isinstance(part, dict) else None
            if isinstance(text, str) and text.strip(): return text.strip()
    return ""


async def _openai_analyze(transcript: str, current_stage: str, complexity: str, memory=None):
    if not _openai_key(): return None
    model, effort = choose_openai_model(complexity)
    body = {"model": model, "reasoning": {"effort": effort}, "input": [{"role":"system","content":[{"type":"input_text","text":_system(memory)}]}, {"role":"user","content":[{"type":"input_text","text":f"Current stage: {current_stage}\nConversation:\n{transcript[:30000]}"}]}], "text":{"format":{"type":"json_object"}}, "max_output_tokens":1800}
    try:
        async with httpx.AsyncClient(timeout=45) as client: r = await client.post(OPENAI_RESPONSES_URL, headers={"Authorization":f"Bearer {_openai_key()}","Content-Type":"application/json"}, json=body)
        if r.status_code >= 400: return None
        data=json.loads(_openai_text(r.json()))
        return _safe_stage({**data,"model":model,"provider":"openai","engine":"openai_responses_frontier","reasoning_effort":effort},current_stage) if isinstance(data,dict) else None
    except Exception: return None


async def _anthropic_one(model, transcript, current_stage, complexity, memory=None):
    if not _anthropic_key(): return None
    effort="high" if complexity in {"critical","complex","negotiation","rfq","sourcing","compliance","quote"} else "medium"
    body={"model":model,"max_tokens":1800,"system":_system(memory),"messages":[{"role":"user","content":f"Current stage: {current_stage}\nConversation:\n{transcript[:30000]}\nReturn JSON only."}],"output_config":{"effort":effort}}
    try:
        async with httpx.AsyncClient(timeout=50) as client: r=await client.post(ANTHROPIC_MESSAGES_URL,headers={"x-api-key":_anthropic_key(),"anthropic-version":"2023-06-01","content-type":"application/json"},json=body)
        if r.status_code>=400:return None
        text="\n".join(str(x.get("text") or "") for x in r.json().get("content") or [] if isinstance(x,dict) and x.get("type")=="text").strip().strip("` \n")
        if text.startswith("json"):text=text[4:].strip()
        data=json.loads(text)
        return _safe_stage({**data,"model":model,"provider":"anthropic","engine":"anthropic_frontier","reasoning_effort":effort},current_stage) if isinstance(data,dict) else None
    except Exception:return None


async def _anthropic_analyze(transcript,current_stage,complexity,memory=None):
    for model in choose_anthropic_models(complexity):
        result=await _anthropic_one(model,transcript,current_stage,complexity,memory)
        if result:return result
    return None


def _consensus(oa,an):
    order=["NEW","ENGAGED","QUALIFYING","QUALIFIED","RFQ_READY","SOURCING","QUOTED","NEGOTIATING","WON"]
    try:stage=order[min(order.index(str(oa.get("recommended_stage") or "NEW")),order.index(str(an.get("recommended_stage") or "NEW")))]
    except ValueError:stage="QUALIFYING"
    return _safe_stage({**oa,"recommended_stage":stage,"opportunity_score":max(int(oa.get("opportunity_score") or 0),int(an.get("opportunity_score") or 0)),"missing_fields":list(dict.fromkeys((oa.get("missing_fields") or [])+(an.get("missing_fields") or []))),"risk_flags":list(dict.fromkeys((oa.get("risk_flags") or [])+(an.get("risk_flags") or []))),"evidence_required":list(dict.fromkeys((oa.get("evidence_required") or [])+(an.get("evidence_required") or []))),"next_best_action":an.get("next_best_action") or oa.get("next_best_action"),"draft_reply":oa.get("draft_reply") or an.get("draft_reply"),"engine":"openai_anthropic_frontier_consensus","co_brains":[{"provider":"openai","model":oa.get("model")},{"provider":"anthropic","model":an.get("model")}]},stage)


async def _nvidia_analyze(transcript,current_stage,memory=None):
    if not _nvidia_key():return None
    prompt=_system(memory)+f"\nCurrent stage: {current_stage}\nConversation:\n{transcript[:24000]}"
    for model in NVIDIA_FALLBACKS:
        try:
            async with httpx.AsyncClient(timeout=35) as client:r=await client.post(NVIDIA_CHAT_URL,headers={"Authorization":f"Bearer {_nvidia_key()}","Content-Type":"application/json"},json={"model":model,"messages":[{"role":"user","content":prompt}],"temperature":0.15,"max_tokens":1200})
            if r.status_code>=400:continue
            raw=(((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip().strip("` \n")
            if raw.startswith("json"):raw=raw[4:].strip()
            data=json.loads(raw)
            if isinstance(data,dict):return _safe_stage({**data,"model":model,"provider":"nvidia","engine":"nvidia_resilience"},current_stage)
        except Exception:continue
    return None


def _deterministic(transcript,current_stage):
    t=transcript.lower();intent=any(x in t for x in ("quote","cotiz","buy","compr","import","precio","price","container","contenedor"))
    return _safe_stage({"opportunity_score":min(25+(35 if intent else 0)+(10 if any(ch.isdigit() for ch in t) else 0),90),"intent":"commercial_trade" if intent else "unknown","language":"auto","recommended_stage":"QUALIFYING" if intent else (current_stage or "ENGAGED"),"missing_fields":["product/specification","quantity","origin","destination","delivery timeline","target budget"],"next_best_action":"Collect only the genuinely missing trade requirements and preserve momentum.","draft_reply":"Gracias. Ya tengo el contexto anterior; avancemos únicamente con el próximo dato necesario para mover la solicitud.","risk_flags":[],"evidence_required":["verified supplier offer","freight evidence","compliance review","landed-cost calculation"],"reasoning_level":"fallback","model":"deterministic","provider":"local","engine":"local_fallback"},current_stage)


async def analyze_sales_conversation(*,transcript:str,current_stage:str="NEW",complexity:str="normal",relationship_memory:dict[str,Any]|None=None)->dict[str,Any]:
    oa_task=_openai_analyze(transcript,current_stage,complexity,relationship_memory);an_task=_anthropic_analyze(transcript,current_stage,complexity,relationship_memory)
    oa,an=await asyncio.gather(oa_task,an_task)
    if oa and an:return _consensus(oa,an)
    if oa:return oa
    if an:return an
    return _deterministic(transcript,current_stage)


def frontier_status():
    return {"openai":{"primary_brain":SOL,"balanced_executor":SOL,"high_volume_executor":SOL,"responses_api":True},"primary_reasoning_authority":SOL,"anthropic":{"frontier_general":FABLE,"restricted_frontier":MYTHOS,"daily_frontier":OPUS,"fast_frontier":SONNET,"messages_api":True},"anthropic_role":"independent_review_consensus_and_resilience","co_brain_consensus":True,"deterministic_continuity_fallback":True,"openai_key_configured":bool(_openai_key()),"anthropic_key_configured":bool(_anthropic_key()),"binding_quotes_fail_closed":True,"sofia_human_conversation_policy":True,"relationship_memory_injection":True}
