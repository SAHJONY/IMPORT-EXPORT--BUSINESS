from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token


app = FastAPI(
    title="SAHJONY Worldwide Business Discovery",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

_PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
_FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.googleMapsUri",
        "places.primaryType",
        "places.businessStatus",
        "places.rating",
        "places.userRatingCount",
    )
)


def _places_key() -> str:
    return os.getenv("GOOGLE_PLACES_API_KEY", "").strip()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Owner authorization is required")
    token = authorization.removeprefix("Bearer ").strip()
    if not verify_owner_token(token):
        raise HTTPException(403, "Invalid or expired owner session")


class PlacesSearchIn(BaseModel):
    query: str = Field(min_length=3, max_length=240)
    limit: int = Field(default=10, ge=1, le=20)
    language_code: str = Field(default="en", min_length=2, max_length=12)
    region_code: str = Field(default="US", min_length=2, max_length=2)


def _safe_place(place: dict[str, Any]) -> dict[str, Any]:
    display = place.get("displayName") or {}
    return {
        "place_id": place.get("id"),
        "name": display.get("text") if isinstance(display, dict) else None,
        "address": place.get("formattedAddress"),
        "website": place.get("websiteUri"),
        "phone": place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber"),
        "google_maps_url": place.get("googleMapsUri"),
        "primary_type": place.get("primaryType"),
        "business_status": place.get("businessStatus"),
        "rating": place.get("rating"),
        "user_rating_count": place.get("userRatingCount"),
    }


@app.get("/api/connect/worldwide/health")
async def worldwide_health() -> dict[str, Any]:
    ready = bool(_places_key())
    return {
        "status": "ok" if ready else "configuration_required",
        "service": "worldwide-business-discovery",
        "google_places_ready": ready,
        "google_places_api": "places-api-new",
        "search_endpoint": "/api/connect/worldwide/search",
        "owner_authorization_required": True,
        "api_key_exposed": False,
    }


@app.post("/api/connect/worldwide/search")
async def worldwide_search(
    payload: PlacesSearchIn,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _owner(authorization)
    api_key = _places_key()
    if not api_key:
        raise HTTPException(503, "Google Places is not configured")

    request_body = {
        "textQuery": payload.query.strip(),
        "pageSize": payload.limit,
        "languageCode": payload.language_code,
        "regionCode": payload.region_code.upper(),
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as client:
            response = await client.post(
                _PLACES_URL,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": api_key,
                    "X-Goog-FieldMask": _FIELD_MASK,
                },
                json=request_body,
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Google Places timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Google Places transport failed") from exc

    if response.status_code >= 400:
        # Provider bodies can contain diagnostics that should remain in server-side
        # observability. Never relay credentials or the raw provider response.
        raise HTTPException(502, f"Google Places request failed with HTTP {response.status_code}")

    try:
        provider_payload = response.json()
    except ValueError as exc:
        raise HTTPException(502, "Google Places returned a non-JSON response") from exc

    results = [
        safe
        for raw in provider_payload.get("places") or []
        if isinstance(raw, dict) and (safe := _safe_place(raw)).get("place_id") and safe.get("name")
    ][: payload.limit]
    return {
        "status": "ok",
        "provider": "google_places",
        "query": payload.query.strip(),
        "result_count": len(results),
        "usable_results": bool(results),
        "results": results,
        "api_key_exposed": False,
    }
