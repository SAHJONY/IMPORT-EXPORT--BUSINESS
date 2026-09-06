from __future__ import annotations

import os
from datetime import date
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, model_validator

DUFFEL_API_BASE = "https://api.duffel.com"
DUFFEL_VERSION = "v2"
CabinClass = Literal["economy", "premium_economy", "business", "first"]


class DuffelFlightSearchIn(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    departure_date: date
    return_date: date | None = None
    adults: int = Field(default=1, ge=1, le=9)
    cabin_class: CabinClass = "economy"
    max_connections: int | None = Field(default=None, ge=0, le=2)
    limit: int = Field(default=10, ge=1, le=20)

    @model_validator(mode="after")
    def normalize(self):
        self.origin = self.origin.upper()
        self.destination = self.destination.upper()
        if self.origin == self.destination:
            raise ValueError("origin and destination must differ")
        if self.return_date and self.return_date < self.departure_date:
            raise ValueError("return_date cannot be before departure_date")
        return self


def token_mode(token: str | None = None) -> Literal["test", "live", "unset", "unknown"]:
    value = (token if token is not None else os.getenv("DUFFEL_ACCESS_TOKEN", "")).strip()
    if not value:
        return "unset"
    if value.startswith("duffel_test_"):
        return "test"
    if value.startswith("duffel_live_"):
        return "live"
    return "unknown"


def sandbox_ready(token: str | None = None) -> tuple[bool, str]:
    mode = token_mode(token)
    if mode == "test":
        return True, "Duffel Test Mode configurado. Búsqueda permitida; emisión real bloqueada."
    if mode == "live":
        return False, "Token live detectado pero rechazado por el adapter sandbox."
    if mode == "unknown":
        return False, "Credencial Duffel con formato no reconocido; se mantiene fail-closed."
    return False, "DUFFEL_ACCESS_TOKEN no configurado."


def _headers(token: str) -> dict[str, str]:
    if token_mode(token) != "test":
        raise RuntimeError("Duffel sandbox requires a duffel_test_ token; live tokens are not accepted")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Duffel-Version": DUFFEL_VERSION,
    }


def _passengers(adults: int) -> list[dict[str, str]]:
    return [{"type": "adult"} for _ in range(adults)]


def _slices(p: DuffelFlightSearchIn) -> list[dict[str, str]]:
    slices = [{
        "origin": p.origin,
        "destination": p.destination,
        "departure_date": p.departure_date.isoformat(),
    }]
    if p.return_date:
        slices.append({
            "origin": p.destination,
            "destination": p.origin,
            "departure_date": p.return_date.isoformat(),
        })
    return slices


def build_offer_request(p: DuffelFlightSearchIn) -> dict[str, Any]:
    data: dict[str, Any] = {
        "cabin_class": p.cabin_class,
        "passengers": _passengers(p.adults),
        "slices": _slices(p),
    }
    if p.max_connections is not None:
        data["max_connections"] = p.max_connections
    return {"data": data}


def _segment_summary(segment: dict[str, Any]) -> dict[str, Any]:
    operating_carrier = segment.get("operating_carrier") or {}
    marketing_carrier = segment.get("marketing_carrier") or {}
    return {
        "origin": (segment.get("origin") or {}).get("iata_code"),
        "destination": (segment.get("destination") or {}).get("iata_code"),
        "departing_at": segment.get("departing_at"),
        "arriving_at": segment.get("arriving_at"),
        "operating_carrier": operating_carrier.get("name"),
        "marketing_carrier": marketing_carrier.get("name"),
        "flight_number": segment.get("marketing_carrier_flight_number") or segment.get("operating_carrier_flight_number"),
    }


def summarize_offer(offer: dict[str, Any]) -> dict[str, Any]:
    slices = []
    for flight_slice in offer.get("slices") or []:
        segments = [_segment_summary(segment) for segment in (flight_slice.get("segments") or [])]
        slices.append({
            "origin": (flight_slice.get("origin") or {}).get("iata_code"),
            "destination": (flight_slice.get("destination") or {}).get("iata_code"),
            "duration": flight_slice.get("duration"),
            "segments": segments,
        })
    owner = offer.get("owner") or {}
    return {
        "offer_id": offer.get("id"),
        "total_amount": offer.get("total_amount"),
        "total_currency": offer.get("total_currency"),
        "expires_at": offer.get("expires_at"),
        "live_mode": bool(offer.get("live_mode")),
        "airline": owner.get("name"),
        "passenger_identity_documents_required": bool(offer.get("passenger_identity_documents_required")),
        "slices": slices,
    }


async def search_flights(p: DuffelFlightSearchIn, token: str | None = None) -> dict[str, Any]:
    access_token = (token if token is not None else os.getenv("DUFFEL_ACCESS_TOKEN", "")).strip()
    ready, reason = sandbox_ready(access_token)
    if not ready:
        raise RuntimeError(reason)

    params = {"return_offers": "true"}
    async with httpx.AsyncClient(base_url=DUFFEL_API_BASE, timeout=30.0) as client:
        response = await client.post(
            "/air/offer_requests",
            params=params,
            headers=_headers(access_token),
            json=build_offer_request(p),
        )
        response.raise_for_status()
        body = response.json()

    offer_request = body.get("data") or {}
    offers = offer_request.get("offers") or []
    safe_offers = [summarize_offer(offer) for offer in offers[: p.limit]]
    if any(offer.get("live_mode") for offer in safe_offers):
        raise RuntimeError("Duffel returned live-mode content to the sandbox adapter; response rejected")

    return {
        "status": "ok",
        "provider": "duffel",
        "mode": "test",
        "real_money_booking_allowed": False,
        "ticket_issuance_allowed": False,
        "offer_request_id": offer_request.get("id"),
        "count": len(safe_offers),
        "offers": safe_offers,
    }


async def get_offer(offer_id: str, token: str | None = None) -> dict[str, Any]:
    access_token = (token if token is not None else os.getenv("DUFFEL_ACCESS_TOKEN", "")).strip()
    ready, reason = sandbox_ready(access_token)
    if not ready:
        raise RuntimeError(reason)
    if not offer_id.startswith("off_"):
        raise ValueError("Invalid Duffel offer id")

    async with httpx.AsyncClient(base_url=DUFFEL_API_BASE, timeout=20.0) as client:
        response = await client.get(
            f"/air/offers/{offer_id}",
            params={"return_available_services": "true"},
            headers=_headers(access_token),
        )
        response.raise_for_status()
        body = response.json()

    offer = summarize_offer(body.get("data") or {})
    if offer.get("live_mode"):
        raise RuntimeError("Live-mode offer rejected by sandbox adapter")
    return {
        "status": "ok",
        "provider": "duffel",
        "mode": "test",
        "ticket_issuance_allowed": False,
        "offer": offer,
    }
