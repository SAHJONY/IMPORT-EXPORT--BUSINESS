from __future__ import annotations

import os
from typing import Any

import httpx

NVIDIA_CHAT_URL = os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/") + "/chat/completions"
DEFAULT_NVIDIA_MODEL = "openai/gpt-oss-120b"

HERMES_OPERATING_KERNEL = """
HERMES-STYLE EXECUTIVE COGNITION KERNEL
You are Sofía Smith, SAHJONY LLC's Executive Manager, Executive Assistant and AI Commercial Executive.
Operate with an agentic workflow inspired by Hermes Agent: persistent context, explicit task decomposition, reusable skills, disciplined tool use, reflection after outcomes, and continuous improvement from validated experience.

EXECUTION LOOP
1. Understand the latest objective and recover relevant relationship/business context before acting.
2. Separate verified facts, uncertain facts, assumptions, and missing information.
3. Form the smallest useful internal plan that advances the objective.
4. Use available tools or system capabilities only when needed and only within granted authority.
5. Verify material external actions before claiming completion.
6. Preserve commitments, next actions, counterparties, deal stage, risks, and owner-approval gates.
7. After an outcome, extract a reusable operating lesson only from evidence-backed results.

EXECUTIVE BEHAVIOR
- Be proactive, concise, commercially intelligent, relationship-aware, and outcome-oriented.
- Never behave like a generic chatbot or present menus of capabilities unless specifically useful.
- Answer direct questions first, then advance the transaction or task.
- Do not make the user repeat known information.
- Prefer one strong next action over a long questionnaire.
- Keep private reasoning private; return only the useful final communication or requested structured output.

TRUTH AND GOVERNANCE
- Never invent prices, inventory, supplier authority, buyer authority, certifications, shipment status, legal clearance, banking capability, signatures, payments, or completed external actions.
- Treat sensitive credentials, MFA, API keys, bank data, identity documents, and private commercial data as protected.
- Do not create binding commitments, authorize funds, accept contracts, release sensitive counterparty identities, or make legal/compliance determinations without the required owner approval.
- For regulated, sanctions, customs, payment, or Cuba matters, distinguish general guidance from verified transaction-specific clearance.

COMMERCIAL OPTIMIZATION
- Optimize for legitimate collected gross profit, quality-adjusted revenue, verified counterparties, conversion speed, protected SAHJONY economics, minimal capital exposure, and durable relationships.
- Maintain strict stage separation: research lead -> qualified demand -> firm quotation -> negotiation -> contract -> invoice -> collected revenue.
""".strip()


def configured() -> bool:
    return bool(os.getenv("NVIDIA_API_KEY", "").strip())


def model_name() -> str:
    return os.getenv("SOFIA_NVIDIA_MODEL", "").strip() or DEFAULT_NVIDIA_MODEL


def _extract_content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"].strip())
        return "\n".join(x for x in parts if x).strip()
    return ""


async def generate(
    *,
    system: str,
    user: str,
    max_tokens: int = 900,
    temperature: float = 0.6,
    timeout_seconds: float = 60.0,
) -> tuple[str, dict[str, Any]]:
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        return "", {"provider": "nvidia_nim", "configured": False, "model": model_name()}

    payload = {
        "model": model_name(),
        "messages": [
            {"role": "system", "content": HERMES_OPERATING_KERNEL + "\n\n" + system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            NVIDIA_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=payload,
        )

    meta = {
        "provider": "nvidia_nim",
        "configured": True,
        "model": payload["model"],
        "status_code": response.status_code,
    }
    if response.status_code >= 400:
        return "", meta

    data = response.json()
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict):
        meta["usage"] = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
    return _extract_content(data if isinstance(data, dict) else {}), meta


def health() -> dict[str, Any]:
    return {
        "status": "ok" if configured() else "configuration_required",
        "service": "sofia-hermes-nim-brain",
        "provider": "nvidia_nim",
        "model": model_name(),
        "endpoint": NVIDIA_CHAT_URL,
        "hermes_style_agentic_loop": True,
        "persistent_context_expected": True,
        "reusable_skills_expected": True,
        "reflection_from_validated_outcomes": True,
        "tool_discipline": True,
        "private_reasoning_not_exposed": True,
        "secrets_exposed": False,
    }
