from __future__ import annotations

import json
import os
from typing import Any

import httpx

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
NVIDIA_CHAT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Frontier hierarchy: strongest reasoning first, then cost/latency tiers.
SOL = "gpt-5.6-sol"
TERRA = "gpt-5.6-terra"
LUNA = "gpt-5.6-luna"
NVIDIA_FALLBACKS = [
    "nvidia/nemotron-3-nano-30b-a3b",
    "deepseek-ai/deepseek-v4-flash-0731",
]

SYSTEM = """You are the SAHJONY LLC WhatsApp Sales Brain and commercial execution engine for global B2B import-export.
Your job is to convert conversations into qualified, evidence-backed opportunities while preserving trust, compliance, and margin.
You may autonomously: detect intent, qualify demand, ask targeted questions, score opportunities, prepare RFQs, recommend supplier/freight/compliance work, draft follow-ups, summarize negotiations, and recommend next actions.
You must never invent supplier prices, freight, inventory, certifications, customs requirements, landed cost, or binding terms.
Formal quotes, price commitments, credit terms, contracts, and WON status require verified commercial evidence from the application data layer.
Return strict JSON with: opportunity_score (0-100), intent, language, recommended_stage, missing_fields, next_best_action, draft_reply, risk_flags, evidence_required, reasoning_level.
Allowed stages: NEW, ENGAGED, QUALIFYING, QUALIFIED, RFQ_READY, SOURCING, QUOTED, NEGOTIATING, WON, LOST, OPTED_OUT.
If evidence is not present, never recommend QUOTED, NEGOTIATING, or WON as an automatic stage; cap at RFQ_READY.
"""


def _openai_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip()


def _nvidia_key() -> str:
    return os.getenv("NVIDIA_API_KEY", "").strip()


def choose_frontier_model(*, complexity: str = "normal", latency_sensitive: bool = False, high_volume: bool = False) -> tuple[str, str]:
    """Return (model, reasoning_effort)."""
    c = (complexity or "normal").lower()
    if c in {"critical", "complex", "negotiation", "rfq", "sourcing", "compliance", "quote"}:
        return SOL, "high"
    if latency_sensitive or high_volume:
        return LUNA, "low"
    return TERRA, "medium"


def _extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for c in item.get("content") or []:
            if not isinstance(c, dict):
                continue
            txt = c.get("text")
            if isinstance(txt, str) and txt.strip():
                return txt.strip()
    return ""


async def _openai_analyze(*, transcript: str, current_stage: str, complexity: str) -> dict[str, Any] | None:
    key = _openai_key()
    if not key:
        return None
    model, effort = choose_frontier_model(complexity=complexity)
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
            r = await client.post(
                OPENAI_RESPONSES_URL,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
            )
        if r.status_code >= 400:
            return None
        raw = _extract_response_text(r.json())
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        stage = str(data.get("recommended_stage") or current_stage or "NEW").upper()
        if stage in {"QUOTED", "NEGOTIATING", "WON"}:
            stage = "RFQ_READY"
        data["recommended_stage"] = stage
        data["model"] = model
        data["reasoning_effort"] = effort
        data["engine"] = "openai_responses_frontier"
        data["binding_commitment_allowed"] = False
        data["quote_release_allowed"] = False
        return data
    except Exception:
        return None


async def _nvidia_analyze(*, transcript: str, current_stage: str) -> dict[str, Any] | None:
    key = _nvidia_key()
    if not key:
        return None
    prompt = SYSTEM + f"\nCurrent stage: {current_stage}\nConversation:\n{transcript[:24000]}"
    for model in NVIDIA_FALLBACKS:
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                r = await client.post(
                    NVIDIA_CHAT_URL,
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.15, "max_tokens": 1200},
                )
            if r.status_code >= 400:
                continue
            raw = (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            raw = raw.strip("` \n")
            if raw.startswith("json"):
                raw = raw[4:].strip()
            data = json.loads(raw)
            if not isinstance(data, dict):
                continue
            stage = str(data.get("recommended_stage") or current_stage or "NEW").upper()
            if stage in {"QUOTED", "NEGOTIATING", "WON"}:
                stage = "RFQ_READY"
            return {**data, "recommended_stage": stage, "model": model, "engine": "nvidia_resilience", "binding_commitment_allowed": False, "quote_release_allowed": False}
        except Exception:
            continue
    return None


def _deterministic(transcript: str, current_stage: str) -> dict[str, Any]:
    t = transcript.lower()
    intent = any(x in t for x in ("quote", "cotiz", "buy", "compr", "import", "precio", "price", "container", "contenedor"))
    score = 25 + (35 if intent else 0) + (10 if any(ch.isdigit() for ch in t) else 0)
    score = min(score, 90)
    stage = "QUALIFYING" if intent else (current_stage or "ENGAGED")
    return {
        "opportunity_score": score,
        "intent": "commercial_trade" if intent else "unknown",
        "language": "auto",
        "recommended_stage": stage,
        "missing_fields": ["product/specification", "quantity", "origin", "destination", "delivery timeline", "target budget"],
        "next_best_action": "Collect only the missing trade requirements and preserve momentum.",
        "draft_reply": "Para preparar la próxima etapa, confirme producto/especificación, cantidad, origen, destino, fecha objetivo y presupuesto.",
        "risk_flags": [],
        "evidence_required": ["verified supplier offer", "freight evidence", "compliance review", "landed-cost calculation"],
        "reasoning_level": "fallback",
        "model": "deterministic",
        "engine": "local_fallback",
        "binding_commitment_allowed": False,
        "quote_release_allowed": False,
    }


async def analyze_sales_conversation(*, transcript: str, current_stage: str = "NEW", complexity: str = "normal") -> dict[str, Any]:
    """Frontier-first router: OpenAI GPT-5.6 family -> NVIDIA resilience -> deterministic fallback."""
    result = await _openai_analyze(transcript=transcript, current_stage=current_stage, complexity=complexity)
    if result:
        return result
    result = await _nvidia_analyze(transcript=transcript, current_stage=current_stage)
    if result:
        return result
    return _deterministic(transcript, current_stage)


def frontier_status() -> dict[str, Any]:
    return {
        "primary_brain": SOL,
        "balanced_executor": TERRA,
        "high_volume_executor": LUNA,
        "openai_responses_api": True,
        "reasoning_router": {"critical": "high", "normal": "medium", "high_volume": "low"},
        "nvidia_resilience": NVIDIA_FALLBACKS,
        "openai_key_configured": bool(_openai_key()),
        "nvidia_key_configured": bool(_nvidia_key()),
        "binding_quotes_fail_closed": True,
    }
