from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

from auth import verify_owner_token

app = FastAPI(title="SAHJONY Viajes Globales Operations API", version="1.1.0", docs_url=None, redoc_url=None)

ProviderType = Literal["gds", "ndc", "airline", "consolidator", "charter", "visa_rules", "other"]
ComplianceState = Literal["unknown", "pending", "review", "cleared", "blocked"]
CabinClass = Literal["economy", "premium_economy", "business", "first"]

DUFFEL_API_BASE = "https://api.duffel.com"


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _env_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _owner(auth: str | None) -> None:
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(auth.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


class FareEconomicsIn(BaseModel):
    currency: str = Field(default="USD", min_length=3, max_length=3)
    net_fare: Decimal = Field(ge=0)
    taxes_fees: Decimal = Field(default=Decimal("0"), ge=0)
    agency_fee: Decimal = Field(default=Decimal("0"), ge=0)
    markup_amount: Decimal = Field(default=Decimal("0"), ge=0)
    payment_cost: Decimal = Field(default=Decimal("0"), ge=0)
    support_cost: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def canonical_currency(self):
        self.currency = self.currency.upper()
        if self.currency != "USD":
            raise ValueError("Travel economics are currently canonicalized in USD")
        return self


class BookingGateIn(BaseModel):
    case_compliance_state: ComplianceState = "unknown"
    itinerary_compliance_state: ComplianceState = "unknown"
    case_human_review_required: bool = True
    itinerary_human_review_required: bool = True
    provider_configured: bool = False
    provider_health_ok: bool = False
    payment_authorized: bool = False
    fare_still_valid: bool = False


class ProviderReadiness(BaseModel):
    provider_type: ProviderType
    provider_code: str
    provider_name: str
    configured: bool
    environment: str
    fare_search_allowed: bool
    live_ticketing_allowed: bool
    reason_es: str


class DuffelSearchIn(BaseModel):
    origin: str = Field(min_length=3, max_length=3)
    destination: str = Field(min_length=3, max_length=3)
    departure_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    return_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    adults: int = Field(default=1, ge=1, le=9)
    cabin_class: CabinClass = "economy"
    max_connections: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def normalize_airports(self):
        self.origin = self.origin.upper()
        self.destination = self.destination.upper()
        if self.origin == self.destination:
            raise ValueError("Origin and destination must differ")
        return self


def calculate_economics(p: FareEconomicsIn) -> dict[str, str]:
    supplier_cost = _money(p.net_fare + p.taxes_fees)
    customer_price = _money(supplier_cost + p.agency_fee + p.markup_amount)
    gross_profit = _money(p.agency_fee + p.markup_amount - p.payment_cost - p.support_cost)
    gross_margin_pct = Decimal("0") if customer_price == 0 else _money((gross_profit / customer_price) * Decimal("100"))
    return {
        "currency": p.currency,
        "supplier_cost": str(supplier_cost),
        "customer_price": str(customer_price),
        "estimated_gross_profit": str(gross_profit),
        "estimated_gross_margin_pct": str(gross_margin_pct),
    }


def booking_gate(p: BookingGateIn) -> dict:
    blockers: list[str] = []
    if p.case_compliance_state != "cleared": blockers.append("CASE_COMPLIANCE_NOT_CLEARED")
    if p.itinerary_compliance_state != "cleared": blockers.append("ITINERARY_COMPLIANCE_NOT_CLEARED")
    if p.case_human_review_required: blockers.append("CASE_HUMAN_REVIEW_REQUIRED")
    if p.itinerary_human_review_required: blockers.append("ITINERARY_HUMAN_REVIEW_REQUIRED")
    if not p.provider_configured: blockers.append("TICKETING_PROVIDER_NOT_CONFIGURED")
    if not p.provider_health_ok: blockers.append("TICKETING_PROVIDER_NOT_HEALTHY")
    if not p.payment_authorized: blockers.append("PAYMENT_NOT_AUTHORIZED")
    if not p.fare_still_valid: blockers.append("FARE_NOT_REVALIDATED")
    return {
        "release_allowed": not blockers,
        "booking_status": "READY_TO_ISSUE" if not blockers else "HOLD",
        "blockers": blockers,
        "fail_closed": True,
    }


def duffel_readiness() -> ProviderReadiness:
    token = bool(os.getenv("DUFFEL_ACCESS_TOKEN", "").strip())
    mode = os.getenv("DUFFEL_MODE", "test").strip().lower()
    live_mode = mode == "live"
    contract = _env_true("TRAVEL_DUFFEL_CONTRACT_APPROVED")
    ticketing_switch = _env_true("TRAVEL_DUFFEL_LIVE_TICKETING_ENABLED")
    ticketing = token and live_mode and contract and ticketing_switch
    if not token:
        reason = "Duffel no configurado; falta DUFFEL_ACCESS_TOKEN."
    elif not live_mode:
        reason = "Duffel configurado en test; búsqueda de prueba permitida, emisión real bloqueada."
    elif not contract:
        reason = "Duffel live detectado; falta aprobación contractual interna."
    elif not ticketing_switch:
        reason = "Contrato aprobado; el switch de emisión real continúa desactivado."
    else:
        reason = "Proveedor configurado para live; la emisión todavía requiere booking gate, pago y compliance por transacción."
    return ProviderReadiness(
        provider_type="other", provider_code="duffel", provider_name="Duffel Flights",
        configured=token, environment="live" if live_mode else "test",
        fare_search_allowed=token, live_ticketing_allowed=ticketing, reason_es=reason,
    )


def provider_readiness() -> list[ProviderReadiness]:
    duffel = duffel_readiness()
    timatic_configured = bool(os.getenv("TIMATIC_API_KEY", "").strip())
    return [
        duffel,
        ProviderReadiness(
            provider_type="visa_rules", provider_code="iata_timatic", provider_name="IATA Timatic",
            configured=timatic_configured, environment="live" if timatic_configured else "unconfigured",
            fare_search_allowed=False, live_ticketing_allowed=False,
            reason_es=("Fuente migratoria configurada; requiere health-check antes de usarla como evidencia operativa." if timatic_configured else "Timatic registrado como fuente prioritaria; credencial API todavía no configurada."),
        ),
    ]


def build_duffel_offer_request(p: DuffelSearchIn) -> dict:
    slices = [{"origin": p.origin, "destination": p.destination, "departure_date": p.departure_date}]
    if p.return_date:
        slices.append({"origin": p.destination, "destination": p.origin, "departure_date": p.return_date})
    return {
        "data": {
            "cabin_class": p.cabin_class,
            "max_connections": p.max_connections,
            "slices": slices,
            "passengers": [{"type": "adult"} for _ in range(p.adults)],
        }
    }


def _compact_duffel_offers(payload: dict) -> list[dict]:
    data = payload.get("data") or {}
    offers = data.get("offers") or []
    compact = []
    for offer in offers[:50]:
        compact.append({
            "offer_id": offer.get("id"),
            "expires_at": offer.get("expires_at"),
            "total_amount": offer.get("total_amount"),
            "total_currency": offer.get("total_currency"),
            "owner": (offer.get("owner") or {}).get("name"),
            "slices": offer.get("slices") or [],
            "payment_requirements": offer.get("payment_requirements") or {},
        })
    return compact


@app.get("/travel-api/health")
async def health():
    providers = provider_readiness()
    duffel = providers[0]
    timatic = providers[1]
    return {
        "status": "configuration_required" if not any(p.configured for p in providers) else "provider_validation_required",
        "service": "sahjony-viajes-globales",
        "primary_language": "es",
        "spanish_first": True,
        "live_fare_search": duffel.configured and duffel.environment == "live",
        "test_fare_search": duffel.configured and duffel.environment == "test",
        "live_ticket_issuance": duffel.live_ticketing_allowed,
        "visa_rule_source_live": timatic.configured,
        "booking_gate_fail_closed": True,
        "providers": [p.model_dump() for p in providers],
    }


@app.get("/travel-api/provider-registry")
async def provider_registry():
    return {
        "status": "ok",
        "primary_language": "es",
        "providers": [p.model_dump() for p in provider_readiness()],
        "authoritative_sources": [
            {"code": "iata_timatic", "purpose": "passport_visa_health_requirements", "official_url": "https://www.iata.org/en/services/compliance/timatic/"},
            {"code": "duffel", "purpose": "flight_search_booking_order_management", "official_url": "https://duffel.com/docs/api"},
        ],
    }


@app.post("/travel-api/economics")
async def economics(payload: FareEconomicsIn):
    return calculate_economics(payload)


@app.post("/travel-api/booking-gate")
async def release_gate(payload: BookingGateIn):
    result = booking_gate(payload)
    if not result["release_allowed"]:
        return result
    return {**result, "issuance_executed": False, "next_step": "CALL_CONTRACTED_PROVIDER_ADAPTER"}


@app.post("/travel-api/providers/duffel/search")
async def duffel_search(payload: DuffelSearchIn, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    readiness = duffel_readiness()
    if not readiness.configured:
        raise HTTPException(503, "Duffel is not configured")
    token = os.getenv("DUFFEL_ACCESS_TOKEN", "").strip()
    headers = {
        "Authorization": f"Bearer {token}",
        "Duffel-Version": "v2",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
    }
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                f"{DUFFEL_API_BASE}/air/offer_requests",
                params={"return_offers": "true", "supplier_timeout": "10000"},
                headers=headers,
                json=build_duffel_offer_request(payload),
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Duffel transport error: {type(exc).__name__}") from exc
    if response.status_code >= 400:
        raise HTTPException(502, f"Duffel provider error: HTTP {response.status_code}")
    body = response.json()
    offers = _compact_duffel_offers(body)
    return {
        "status": "ok",
        "provider": "duffel",
        "environment": readiness.environment,
        "offer_request_id": (body.get("data") or {}).get("id"),
        "offers": offers,
        "count": len(offers),
        "live_ticketing_allowed": readiness.live_ticketing_allowed,
        "issuance_executed": False,
    }


@app.post("/travel-api/issue")
async def issue_disabled():
    raise HTTPException(status_code=503, detail="Live ticket issuance is fail-closed until a contracted provider adapter is configured, healthy, and explicitly enabled.")
