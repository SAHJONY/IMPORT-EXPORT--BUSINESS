from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, model_validator

from auth import verify_owner_token
from travel_duffel_sandbox import DuffelFlightSearchIn, get_offer as duffel_get_offer, sandbox_ready, search_flights as duffel_search_flights, token_mode

app = FastAPI(title="SAHJONY Viajes Globales Operations API", version="1.2.0", docs_url=None, redoc_url=None)

ProviderType = Literal["gds", "ndc", "airline", "consolidator", "charter", "visa_rules", "other"]
ComplianceState = Literal["unknown", "pending", "review", "cleared", "blocked"]


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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
    mode = token_mode()
    ready, reason = sandbox_ready()
    return ProviderReadiness(
        provider_type="other",
        provider_code="duffel",
        provider_name="Duffel Flights",
        configured=mode != "unset",
        environment=mode,
        fare_search_allowed=ready,
        live_ticketing_allowed=False,
        reason_es=reason,
    )


def provider_readiness() -> list[ProviderReadiness]:
    duffel = duffel_readiness()
    timatic_configured = bool(os.getenv("TIMATIC_API_KEY", "").strip())
    return [
        duffel,
        ProviderReadiness(
            provider_type="visa_rules",
            provider_code="iata_timatic",
            provider_name="IATA Timatic",
            configured=timatic_configured,
            environment="live" if timatic_configured else "unconfigured",
            fare_search_allowed=False,
            live_ticketing_allowed=False,
            reason_es=(
                "Fuente migratoria configurada; requiere health-check antes de usarla como evidencia operativa."
                if timatic_configured
                else "Timatic registrado como fuente prioritaria; credencial API todavía no configurada."
            ),
        ),
    ]


@app.get("/travel-api/health")
async def health():
    providers = provider_readiness()
    duffel = providers[0]
    timatic = providers[1]
    return {
        "status": "sandbox_ready" if duffel.fare_search_allowed else "configuration_required",
        "service": "sahjony-viajes-globales",
        "primary_language": "es",
        "spanish_first": True,
        "temporary_flight_provider": "duffel_test_mode",
        "test_fare_search": duffel.fare_search_allowed,
        "live_fare_search": False,
        "live_ticket_issuance": False,
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
        "temporary_policy": {
            "provider": "Duffel Test Mode",
            "search_only": True,
            "real_money_booking_allowed": False,
            "live_tokens_rejected": True,
        },
        "authoritative_sources": [
            {"code": "iata_timatic", "purpose": "passport_visa_health_requirements", "official_url": "https://www.iata.org/en/services/compliance/timatic/"},
            {"code": "duffel", "purpose": "temporary_test_flight_search", "official_url": "https://duffel.com/docs/api"},
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
    return {**result, "issuance_executed": False, "next_step": "CONNECT_CONTRACTED_LIVE_PROVIDER"}


@app.post("/travel-api/providers/duffel-test/search")
async def duffel_test_search(payload: DuffelFlightSearchIn, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    try:
        return await duffel_search_flights(payload)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Duffel sandbox search failed: {type(exc).__name__}") from exc


@app.get("/travel-api/providers/duffel-test/offers/{offer_id}")
async def duffel_test_offer(offer_id: str, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    try:
        return await duffel_get_offer(offer_id)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Duffel sandbox offer refresh failed: {type(exc).__name__}") from exc


@app.post("/travel-api/issue")
async def issue_disabled():
    raise HTTPException(
        status_code=503,
        detail="Live ticket issuance is disabled. Temporary Duffel integration accepts test tokens for search/inspection only.",
    )
