from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

app = FastAPI(title="SAHJONY UI Language Gateway", version="2.0.0", docs_url=None, redoc_url=None)

LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
RTL_LANGS = {"ar", "fa", "he", "ur", "ps", "sd", "ug", "yi"}
WINDOW: dict[str, list[float]] = {}


class BatchTranslateRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=60)
    target_locale: str = Field(min_length=2, max_length=35)
    source_locale: str | None = Field(default=None, max_length=35)


def _normalize_locale(value: str | None, *, default: str | None = None) -> str | None:
    raw = (value or "").strip().replace("_", "-")
    if not raw:
        return default
    if not LOCALE_RE.fullmatch(raw):
        raise HTTPException(400, "Invalid locale")
    parts = raw.split("-")
    base = parts[0].lower()
    if len(parts) == 1:
        return base
    normalized = [base]
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            normalized.append(part.upper())
        elif len(part) == 4 and part.isalpha():
            normalized.append(part.title())
        else:
            normalized.append(part)
    return "-".join(normalized)


def _direction(locale: str) -> str:
    return "rtl" if locale.split("-", 1)[0].lower() in RTL_LANGS else "ltr"


def _country(request: Request) -> str | None:
    value = (request.headers.get("x-vercel-ip-country") or "").strip().upper()
    return value or None


def _client_key(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _enforce_limit(request: Request) -> None:
    key = _client_key(request)
    now = time.time()
    window = WINDOW.setdefault(key, [])
    window[:] = [item for item in window if now - item < 60]
    limit = max(1, int(os.getenv("PUBLIC_UI_TRANSLATION_RPM", "30")))
    if len(window) >= limit:
        raise HTTPException(429, "UI translation rate limit exceeded")
    window.append(now)


def _openai_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def _model() -> str:
    return os.getenv("OPENAI_PRIMARY_MODEL", "gpt-5.6-sol").strip() or "gpt-5.6-sol"


async def _translate_with_openai(texts: list[str], target_locale: str, source_locale: str | None) -> list[str]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "UI translation provider is not configured")

    source_instruction = f" from {source_locale}" if source_locale else ""
    prompt = (
        f"Translate every item in the JSON array{source_instruction} into locale {target_locale}. "
        "Use professional, natural business language suitable for an international import/export application. "
        "Translate navigation, buttons, labels, form prompts, placeholders, help text, statuses and descriptions. "
        "Preserve SAHJONY, company names, legal entity names, URLs, email addresses, phone numbers, product codes, SKUs, "
        "currencies, numbers, Incoterms, HS/HTS/ECCN codes and standard trade acronyms. "
        "Do not invent facts, change commercial meaning, or add explanations. Keep UI wording concise. "
        "Return ONLY a valid JSON array of strings in the same order and with exactly the same number of items.\n\n"
        + json.dumps(texts, ensure_ascii=False)
    )
    payload = {
        "model": _model(),
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "You are SAHJONY's deterministic UI localization engine. Output only the requested JSON array.",
                    }
                ],
            },
            {"role": "user", "content": [{"type": "input_text", "text": prompt}]},
        ],
        "max_output_tokens": 7000,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(503, f"UI translation unavailable: provider HTTP {response.status_code}")

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
        raise HTTPException(503, "UI translation provider returned an invalid payload") from exc
    if not isinstance(translated, list) or len(translated) != len(texts) or not all(isinstance(item, str) for item in translated):
        raise HTTPException(503, "UI translation provider returned an inconsistent payload")
    return translated


@app.get("/ui-language/health")
async def health(request: Request) -> dict[str, Any]:
    country = _country(request)
    return {
        "status": "ok",
        "service": "sahjony-ui-language",
        "version": "2.0.0",
        "provider": "openai",
        "provider_configured": _openai_configured(),
        "manual_language_override_preserved": True,
        "query_parameter": "lang",
        "storage_key": "sahjony.locale",
        "cuba_default_locale": "es",
        "cuba_auto_default": country == "CU",
        "country": country,
        "rtl_supported": True,
        "ui_only": True,
        "legal_regulatory_translation": "separate_governed_pipeline",
    }


@app.get("/ui-language/geo")
async def geo(request: Request) -> dict[str, Any]:
    country = _country(request)
    return {
        "country": country,
        "default_locale": "es" if country == "CU" else None,
        "automatic": country == "CU",
    }


@app.post("/ui-language/translate-batch")
async def translate_batch(payload: BatchTranslateRequest, request: Request) -> dict[str, Any]:
    target = _normalize_locale(payload.target_locale)
    source = _normalize_locale(payload.source_locale) if payload.source_locale else None
    assert target is not None
    if source and source.split("-", 1)[0].lower() == target.split("-", 1)[0].lower():
        return {
            "translations": [{"text": text, "to": target} for text in payload.texts],
            "target_locale": target,
            "source_locale": source,
            "direction": _direction(target),
            "provider": "identity",
            "cached": False,
        }
    if sum(len(text) for text in payload.texts) > 12000:
        raise HTTPException(413, "UI translation batch too large")
    _enforce_limit(request)
    translated = await _translate_with_openai(payload.texts, target, source)
    return {
        "translations": [{"text": text, "to": target} for text in translated],
        "target_locale": target,
        "source_locale": source,
        "direction": _direction(target),
        "provider": "openai",
        "country": _country(request),
        "ui_only": True,
    }
