from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

app = FastAPI(title="SAHJONY Viajes Globales Operations API", version="1.0.0", docs_url=None, redoc_url=None)

ProviderType = Literal["gds", "ndc", "airline", "consolidator", "charter", "visa_rules"]
ComplianceState = Literal["unknown", "pending", "review", "cleared", "blocked"]


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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
    provider_name: str
    configured: bool
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
    if p.case_compliance_state != "cleared":
        blockers.append("CASE_COMPLIANCE_NOT_CLEARED")
    if p.itinerary_compliance_state != "cleared":
        blockers.append("ITINERARY_COMPLIANCE_NOT_CLEARED")
    if p.case_human_review_required:
        blockers.append("CASE_HUMAN_REVIEW_REQUIRED")
    if p.itinerary_human_review_required:
        blockers.append("ITINERARY_HUMAN_REVIEW_REQUIRED")
    if not p.provider_configured:
        blockers.append("TICKETING_PROVIDER_NOT_CONFIGURED")
    if not p.provider_health_ok:
        blockers.append("TICKETING_PROVIDER_NOT_HEALTHY")
    if not p.payment_authorized:
        blockers.append("PAYMENT_NOT_AUTHORIZED")
    if not p.fare_still_valid:
        blockers.append("FARE_NOT_REVALIDATED")
    return {
        "release_allowed": not blockers,
        "booking_status": "READY_TO_ISSUE" if not blockers else "HOLD",
        "blockers": blockers,
        "fail_closed": True,
    }


def provider_readiness() -> list[ProviderReadiness]:
    providers = [
        ("gds", "GDS", "TRAVEL_GDS_API_KEY"),
        ("ndc", "NDC", "TRAVEL_NDC_API_KEY"),
        ("consolidator", "Consolidador", "TRAVEL_CONSOLIDATOR_API_KEY"),
        ("charter", "Charter", "TRAVEL_CHARTER_API_KEY"),
        ("visa_rules", "Reglas migratorias", "TRAVEL_VISA_RULES_API_KEY"),
    ]
    out: list[ProviderReadiness] = []
    for provider_type, provider_name, env_name in providers:
        configured = bool(os.getenv(env_name, "").strip())
        out.append(ProviderReadiness(
            provider_type=provider_type, provider_name=provider_name,
            configured=configured,
            live_ticketing_allowed=False,
            reason_es=("Credencial detectada; todavía requiere health-check y habilitación contractual." if configured else "Proveedor no configurado; no se permiten tarifas ni emisión simuladas como reales."),
        ))
    return out


@app.get("/travel-api/health")
async def health():
    providers = provider_readiness()
    return {
        "status": "configuration_required" if not any(p.configured for p in providers) else "provider_validation_required",
        "service": "sahjony-viajes-globales",
        "primary_language": "es",
        "spanish_first": True,
        "live_fare_search": False,
        "live_ticket_issuance": False,
        "visa_rule_source_live": False,
        "booking_gate_fail_closed": True,
        "providers": [p.model_dump() for p in providers],
    }


@app.post("/travel-api/economics")
async def economics(payload: FareEconomicsIn):
    return calculate_economics(payload)


@app.post("/travel-api/booking-gate")
async def release_gate(payload: BookingGateIn):
    result = booking_gate(payload)
    if not result["release_allowed"]:
        return result
    # This endpoint certifies readiness only. It intentionally does not issue a ticket.
    return {**result, "issuance_executed": False, "next_step": "CALL_CONTRACTED_PROVIDER_ADAPTER"}


@app.post("/travel-api/issue")
async def issue_disabled():
    raise HTTPException(status_code=503, detail="Live ticket issuance is fail-closed until a contracted provider adapter is configured, healthy, and explicitly enabled.")
