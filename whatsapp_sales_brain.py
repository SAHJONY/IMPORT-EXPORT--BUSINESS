from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx

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

NVIDIA_FALLBACKS = [
    "nvidia/nemotron-3-nano-30b-a3b",
    "deepseek-ai/deepseek-v4-flash-0731",
]

SYSTEM = """You are the SAHJONY LLC WhatsApp Sales Brain and commercial execution engine for global B2B import-export.
Convert conversations into qualified, evidence-backed opportunities while preserving trust, compliance, and margin.
You may autonomously detect intent, qualify demand, ask targeted questions, score opportunities, prepare RFQs, recommend supplier/freight/compliance work, draft follow-ups, summarize negotiations, and recommend next actions.
Never invent supplier prices, freight, inventory, certifications, customs requirements, landed cost, or binding terms.
Formal quotes, price commitments, credit terms, contracts, and WON status require verified evidence from the application data layer.
Return strict JSON with: opportunity_score, intent, language, recommended_stage, missing_fields, next_best_action, draft_reply, risk_flags, evidence_required, reasoning_level.
Allowed stages: NEW, ENGAGED, QUALIFYING, QUALIFIED, RFQ_READY, SOURCING, QUOTED, NEGOTIATING, WON, LOST, OPTED_OUT.
Without verified evidence, cap automatic progression at RFQ_READY.
"""


def _openai_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def _anthropic_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip()


def _nvidia_key() -> str:
    return os.getenv("NVIDIA_API_KEY", "").strip()


def choose_openai_model(complexity: str = "normal") -> tuple[str, str]:
    c = (complexity or "normal").lower()
    if c in {"critical", "complex", "negotiation", "rfq", "sourcing", "compliance", "quote"}:
        return SOL, "high"
    if c in {"fast", "high_volume", "triage"}:
        return LUNA, "low"
    return TERRA, "medium"


def choose_anthropic_models(complexity: str = "normal") -> list[str]:
    c = (complexity or "normal").lower()
    if c in {"critical", "complex", "negotiation", "rfq", "sourcing", "compliance", "quote"}:
        return [FABLE, OPUS, SONNET, MYTHOS]
    if c in {"fast", "high_volume", "triage"}:
        return [SONNET, OPUS, FABLE, MYTHOS]
    return [OPUS, FABLE, SONNET, MYTHOS]


def _safe_stage(data: dict[str, Any], current_stage: str) -> dict[str, Any]:
    stage = str(data.get("recommended_stage") or current_stage or "NEW").upper()
    if stage in {"QUOTED", "NEGOTIATING", "WON"}:
        stage = "RFQ_READY"
    return {**data, "recommended_stage": stage, "binding_commitment_allowed": False, "quote_release_allowed": False}


def _openai_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()
    for item in data.get("output") or []:
        for part in (item.get("content") or []) if isinstance(item, dict) else []:
            text = part.get("text") if isinstance(part, dict) else None
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


async def _openai_analyze(transcript: str, current_stage: str, complexity: str) -> dict[str, Any] | None:
    if not _openai_key():
        return None
    model, effort = choose_openai_model(complexity)
    body = {
        "model": model,
        "reasoning": {"effort": effort},
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": SYSTEM}]},
            {"role": "user", "content": [{"type": "input_text", "text": f"Current stage: {current_stage}\nConversation:\n{transcript[:30000]}"}]},
        ],
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": 1800,
    }
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(OPENAI_RESPONSES_URL, headers={"Authorization": f"Bearer {_openai_key()}", "Content-Type": "application/json"}, json=body)
        if r.status_code >= 400:
            return None
        data = json.loads(_openai_text(r.json()))
        if not isinstance(data, dict):
            return None
        return _safe_stage({**data, "model": model, "provider": "openai", "engine": "openai_responses_frontier", "reasoning_effort": effort}, current_stage)
    except Exception:
        return None


async def _anthropic_one(model: str, transcript: str, current_stage: str, complexity: str) -> dict[str, Any] | None:
    if not _anthropic_key():
        return None
    effort = "high" if complexity in {"critical", "complex", "negotiation", "rfq", "sourcing", "compliance", "quote"} else "medium"
    body = {
        "model": model,
        "max_tokens": 1800,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": f"Current stage: {current_stage}\nConversation:\n{transcript[:30000]}\nReturn JSON only."}],
        "output_config": {"effort": effort},
    }
    try:
        async with httpx.AsyncClient(timeout=50) as client:
            r = await client.post(ANTHROPIC_MESSAGES_URL, headers={"x-api-key": _anthropic_key(), "anthropic-version": "2023-06-01", "content-type": "application/json"}, json=body)
        if r.status_code >= 400:
            return None
        text = "\n".join(str(x.get("text") or "") for x in r.json().get("content") or [] if isinstance(x, dict) and x.get("type") == "text").strip().strip("` \n")
        if text.startswith("json"):
            text = text[4:].strip()
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return _safe_stage({**data, "model": model, "provider": "anthropic", "engine": "anthropic_frontier", "reasoning_effort": effort}, current_stage)
    except Exception:
        return None


async def _anthropic_analyze(transcript: str, current_stage: str, complexity: str) -> dict[str, Any] | None:
    # Try all currently supported frontier models in a workload-aware order.
    for model in choose_anthropic_models(complexity):
        result = await _anthropic_one(model, transcript, current_stage, complexity)
        if result:
            return result
    return None


def _consensus(openai_result: dict[str, Any], anthropic_result: dict[str, Any]) -> dict[str, Any]:
    order = ["NEW", "ENGAGED", "QUALIFYING", "QUALIFIED", "RFQ_READY", "SOURCING", "QUOTED", "NEGOTIATING", "WON"]
    oa = str(openai_result.get("recommended_stage") or "NEW")
    an = str(anthropic_result.get("recommended_stage") or "NEW")
    try:
        stage = order[min(order.index(oa), order.index(an))]
    except ValueError:
        stage = "QUALIFYING"
    missing = list(dict.fromkeys((openai_result.get("missing_fields") or []) + (anthropic_result.get("missing_fields") or [])))
    risks = list(dict.fromkeys((openai_result.get("risk_flags") or []) + (anthropic_result.get("risk_flags") or [])))
    evidence = list(dict.fromkeys((openai_result.get("evidence_required") or []) + (anthropic_result.get("evidence_required") or [])))
    return _safe_stage({
        **openai_result,
        "recommended_stage": stage,
        "opportunity_score": max(int(openai_result.get("opportunity_score") or 0), int(anthropic_result.get("opportunity_score") or 0)),
        "missing_fields": missing,
        "risk_flags": risks,
        "evidence_required": evidence,
        "next_best_action": anthropic_result.get("next_best_action") or openai_result.get("next_best_action"),
        "draft_reply": openai_result.get("draft_reply") or anthropic_result.get("draft_reply"),
        "engine": "openai_anthropic_frontier_consensus",
        "co_brains": [
            {"provider": "openai", "model": openai_result.get("model")},
            {"provider": "anthropic", "model": anthropic_result.get("model")},
        ],
    }, stage)


async def _nvidia_analyze(transcript: str, current_stage: str) -> dict[str, Any] | None:
    if not _nvidia_key():
        return None
    prompt = SYSTEM + f"\nCurrent stage: {current_stage}\nConversation:\n{transcript[:24000]}"
    for model in NVIDIA_FALLBACKS:
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                r = await client.post(NVIDIA_CHAT_URL, headers={"Authorization": f"Bearer {_nvidia_key()}", "Content-Type": "application/json"}, json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.15, "max_tokens": 1200})
            if r.status_code >= 400:
                continue
            raw = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip().strip("` \n")
            if raw.startswith("json"):
                raw = raw[4:].strip()
            data = json.loads(raw)
            if isinstance(data, dict):
                return _safe_stage({**data, "model": model, "provider": "nvidia", "engine": "nvidia_resilience"}, current_stage)
        except Exception:
            continue
    return None


def _deterministic(transcript: str, current_stage: str) -> dict[str, Any]:
    t = transcript.lower()
    intent = any(x in t for x in ("quote", "cotiz", "buy", "compr", "import", "precio", "price", "container", "contenedor"))
    return _safe_stage({
        "opportunity_score": min(25 + (35 if intent else 0) + (10 if any(ch.isdigit() for ch in t) else 0), 90),
        "intent": "commercial_trade" if intent else "unknown",
        "language": "auto",
        "recommended_stage": "QUALIFYING" if intent else (current_stage or "ENGAGED"),
        "missing_fields": ["product/specification", "quantity", "origin", "destination", "delivery timeline", "target budget"],
        "next_best_action": "Collect only the missing trade requirements and preserve momentum.",
        "draft_reply": "Para preparar la próxima etapa, confirme producto/especificación, cantidad, origen, destino, fecha objetivo y presupuesto.",
        "risk_flags": [],
        "evidence_required": ["verified supplier offer", "freight evidence", "compliance review", "landed-cost calculation"],
        "reasoning_level": "fallback",
        "model": "deterministic",
        "provider": "local",
        "engine": "local_fallback",
    }, current_stage)


async def analyze_sales_conversation(*, transcript: str, current_stage: str = "NEW", complexity: str = "normal") -> dict[str, Any]:
    # OpenAI and Anthropic run as true co-brains in parallel. Either provider can carry the turn alone.
    oa_task = _openai_analyze(transcript, current_stage, complexity)
    an_task = _anthropic_analyze(transcript, current_stage, complexity)
    openai_result, anthropic_result = await asyncio.gather(oa_task, an_task)
    if openai_result and anthropic_result:
        return _consensus(openai_result, anthropic_result)
    if openai_result:
        return openai_result
    if anthropic_result:
        return anthropic_result
    result = await _nvidia_analyze(transcript, current_stage)
    return result or _deterministic(transcript, current_stage)


def frontier_status() -> dict[str, Any]:
    return {
        "openai": {"primary_brain": SOL, "balanced_executor": TERRA, "high_volume_executor": LUNA, "responses_api": True},
        "anthropic": {"frontier_general": FABLE, "restricted_frontier": MYTHOS, "daily_frontier": OPUS, "fast_frontier": SONNET, "messages_api": True},
        "co_brain_consensus": True,
        "parallel_reasoning": True,
        "nvidia_resilience": NVIDIA_FALLBACKS,
        "openai_key_configured": bool(_openai_key()),
        "anthropic_key_configured": bool(_anthropic_key()),
        "nvidia_key_configured": bool(_nvidia_key()),
        "binding_quotes_fail_closed": True,
    }
