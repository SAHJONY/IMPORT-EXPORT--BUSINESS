from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

app = FastAPI(title="SAHJONY Spanish UI Gateway", version="1.1.0", docs_url=None, redoc_url=None)

WINDOW: dict[str, list[float]] = {}


class BatchTranslateRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=60)
    target_locale: str = Field(default="es", min_length=2, max_length=12)


def _country(request: Request) -> str:
    return (request.headers.get("x-vercel-ip-country") or "").strip().upper()


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _enforce_limit(request: Request) -> None:
    key = _client_key(request)
    now = time.time()
    window = WINDOW.setdefault(key, [])
    window[:] = [item for item in window if now - item < 60]
    limit = int(os.getenv("SPANISH_UI_TRANSLATION_RPM", os.getenv("CUBA_UI_TRANSLATION_RPM", "30")))
    if len(window) >= limit:
        raise HTTPException(429, "Spanish UI translation rate limit exceeded")
    window.append(now)


def _openai_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


@app.get("/cuba-language/health")
async def health(request: Request) -> dict[str, Any]:
    country = _country(request)
    return {
        "status": "ok",
        "service": "spanish-ui-gateway",
        "country": country or None,
        "cuba_spanish_default": country == "CU",
        "manual_spanish_available_worldwide": True,
        "openai_configured": _openai_configured(),
        "manual_language_override_preserved": True,
        "legal_regulatory_translation": "not_handled_here",
    }


@app.get("/cuba-language/geo")
async def geo(request: Request) -> dict[str, Any]:
    country = _country(request)
    return {
        "country": country or None,
        "locale": "es" if country == "CU" else None,
        "auto_translate": country == "CU",
    }


async def _translate_with_openai(texts: list[str]) -> list[str]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "Spanish UI translation provider is not configured")
    model = os.getenv("OPENAI_FAST_MODEL", "gpt-5.6-terra").strip() or "gpt-5.6-terra"
    prompt = (
        "Translate every item in the JSON array into clear, professional, natural Spanish suitable for Cuban business users. "
        "Translate UI navigation, buttons, labels, form prompts, placeholders, help text, statuses and descriptions. "
        "Preserve company names, product codes, URLs, email addresses, currencies, numbers, Incoterms, legal entity names and acronyms. "
        "Keep the wording concise for application interfaces. Do not add explanations. "
        "Return ONLY a valid JSON array of strings in the same order with exactly the same number of items.\n\n"
        + json.dumps(texts, ensure_ascii=False)
    )
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": "You are a precise Spanish UI localization engine. Output only the requested JSON array."}]},
            {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
        ],
        "max_output_tokens": 6000,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(503, f"Spanish UI translation unavailable: OpenAI HTTP {response.status_code}")
    data = response.json()
    text = data.get("output_text") or ""
    if not text:
        parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    parts.append(content["text"])
        text = "\n".join(parts)
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    try:
        translated = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise HTTPException(503, "Spanish UI translation returned an invalid payload") from exc
    if not isinstance(translated, list) or len(translated) != len(texts) or not all(isinstance(item, str) for item in translated):
        raise HTTPException(503, "Spanish UI translation returned an inconsistent payload")
    return translated


@app.post("/cuba-language/translate-batch")
async def translate_batch(payload: BatchTranslateRequest, request: Request) -> dict[str, Any]:
    if payload.target_locale.lower().split("-", 1)[0] != "es":
        raise HTTPException(400, "This gateway only serves Spanish UI localization")
    if sum(len(text) for text in payload.texts) > 12000:
        raise HTTPException(413, "Translation batch too large")
    _enforce_limit(request)
    translated = await _translate_with_openai(payload.texts)
    return {
        "translations": [{"text": text, "to": "es"} for text in translated],
        "target_locale": "es",
        "direction": "ltr",
        "country": _country(request) or None,
        "provider": "openai",
        "automatic": _country(request) == "CU",
    }
