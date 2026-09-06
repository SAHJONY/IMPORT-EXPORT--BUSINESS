from __future__ import annotations

from typing import Literal
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="SAHJONY US National Shipping Network", version="1.0.0", docs_url=None, redoc_url=None)

Mode = Literal["AIR", "SEA", "MULTIMODAL"]
CargoUnit = Literal["SINGLE_ITEM", "BOX", "MULTIPLE_BOXES", "PALLET", "LTL", "CONSOLIDATED_LCL", "FCL", "VEHICLE", "MOTORCYCLE", "OVERSIZED", "SPECIAL_REGULATED"]

US_ZONES = {
    "SOUTH_FLORIDA": ["FL"],
    "TEXAS_GULF": ["TX", "LA"],
    "SOUTHEAST": ["GA", "AL", "MS", "SC", "NC", "TN", "AR"],
    "NORTHEAST": ["NY", "NJ", "PA", "MA", "CT", "RI", "NH", "VT", "ME", "DE", "MD", "DC"],
    "MIDWEST": ["OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "KS", "NE", "SD", "ND"],
    "WEST": ["CA", "OR", "WA", "NV", "AZ", "UT", "CO", "NM", "ID", "MT", "WY", "AK", "HI"],
}

PRIMARY_HUBS = {
    "HOUSTON": {"state": "TX", "role": ["TEXAS_GULF", "CENTRAL_US", "SEA", "AIR", "LINEHAUL"]},
    "MIAMI": {"state": "FL", "role": ["SOUTH_FLORIDA", "CARIBBEAN_GATEWAY", "SEA", "AIR", "CONSOLIDATION"]},
}

class NationalIntake(BaseModel):
    origin_state: str = Field(min_length=2, max_length=2)
    origin_postal_code: str | None = Field(default=None, max_length=20)
    destination_country: str = Field(min_length=2, max_length=3)
    destination_city_or_region: str | None = Field(default=None, max_length=160)
    cargo_unit: CargoUnit
    description: str = Field(min_length=2, max_length=2000)
    pieces: int = Field(default=1, ge=1, le=10000)
    weight_lb: float | None = Field(default=None, ge=0)
    volume_cuft: float | None = Field(default=None, ge=0)
    urgent: bool = False
    temperature_controlled: bool = False
    dangerous_or_regulated: bool = False


def zone_for(state: str) -> str:
    s = state.upper()
    for zone, states in US_ZONES.items():
        if s in states:
            return zone
    return "OTHER_US"


def recommend_mode(p: NationalIntake) -> Mode:
    if p.cargo_unit in {"VEHICLE", "MOTORCYCLE", "FCL", "OVERSIZED"}:
        return "SEA"
    if p.urgent and not p.dangerous_or_regulated and (p.weight_lb or 0) <= 300:
        return "AIR"
    if p.cargo_unit in {"SINGLE_ITEM", "BOX", "MULTIPLE_BOXES"} and (p.weight_lb or 0) <= 150 and p.urgent:
        return "AIR"
    return "SEA"


def recommend_hub(p: NationalIntake) -> str:
    zone = zone_for(p.origin_state)
    if zone in {"TEXAS_GULF", "MIDWEST", "SOUTHEAST"}:
        return "HOUSTON"
    return "MIAMI"


@app.get("/us-network/health")
async def health():
    return {
        "status": "ok",
        "national_coverage": True,
        "asset_light": True,
        "primary_hubs": list(PRIMARY_HUBS),
        "air_sea_separated": True,
        "universal_cargo_units": True,
        "customer_technical_knowledge_required": False,
    }


@app.post("/us-network/route")
async def route(p: NationalIntake):
    mode = recommend_mode(p)
    hub = recommend_hub(p)
    return {
        "origin_zone": zone_for(p.origin_state),
        "recommended_hub": hub,
        "recommended_mode": mode,
        "domestic_leg": "LOCAL_PICKUP_OR_PARCEL_LTL_LINEHAUL",
        "international_leg": mode,
        "booking_status": "COMPLIANCE_REVIEW" if p.dangerous_or_regulated else "RATE_AND_CAPACITY_REVIEW",
        "customer_message_rule": "Ask what, from where, to where, quantity/size and urgency. Do not require port, terminal, incoterm, HAWB or HBL from the customer at first contact.",
    }
