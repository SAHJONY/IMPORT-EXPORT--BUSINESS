from __future__ import annotations

from typing import Literal
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="SAHJONY US National Shipping Network", version="1.3.0", docs_url=None, redoc_url=None)

Mode = Literal["AIR", "SEA", "MULTIMODAL"]
CargoUnit = Literal["SINGLE_ITEM", "BOX", "MULTIPLE_BOXES", "PALLET", "LTL", "CONSOLIDATED_LCL", "FCL", "VEHICLE", "MOTORCYCLE", "OVERSIZED", "SPECIAL_REGULATED"]
DeliveryType = Literal["DOOR_TO_DOOR", "DOOR_TO_BUSINESS", "TERMINAL_OPTIONAL"]

US_ZONES = {
    "SOUTH_FLORIDA": ["FL"],
    "TEXAS_GULF": ["TX", "LA"],
    "SOUTHEAST": ["GA", "AL", "MS", "SC", "NC", "TN", "AR"],
    "NORTHEAST": ["NY", "NJ", "PA", "MA", "CT", "RI", "NH", "VT", "ME", "DE", "MD", "DC"],
    "MIDWEST": ["OH", "MI", "IN", "IL", "WI", "MN", "IA", "MO", "KS", "NE", "SD", "ND"],
    "WEST": ["CA", "OR", "WA", "NV", "AZ", "UT", "CO", "NM", "ID", "MT", "WY", "AK", "HI"],
}

PRIMARY_HUBS = {
    "HOUSTON": {
        "state": "TX", "owner": "SAHJONY", "facility_type": "VIRTUAL_HUB",
        "phase": "ACTIVE_NOW",
        "role": ["TEXAS_GULF", "CENTRAL_US", "SEA", "AIR", "LINEHAUL", "CONSOLIDATION_COORDINATION", "VEHICLE_STAGING_COORDINATION"],
        "execution": "AUTHORIZED_THIRD_PARTY_WAREHOUSES_AGENCIES_AND_CARRIERS",
        "future_facility_type": "SAHJONY_OWNED_WAREHOUSE",
    },
    "MIAMI": {
        "state": "FL", "owner": "SAHJONY", "facility_type": "VIRTUAL_HUB",
        "phase": "ACTIVE_NOW",
        "role": ["SOUTH_FLORIDA", "CARIBBEAN_GATEWAY", "SEA", "AIR", "CONSOLIDATION_COORDINATION", "VEHICLE_STAGING_COORDINATION"],
        "execution": "AUTHORIZED_THIRD_PARTY_WAREHOUSES_AGENCIES_AND_CARRIERS",
        "future_facility_type": "SAHJONY_OWNED_WAREHOUSE",
    },
}

class NationalIntake(BaseModel):
    origin_state: str = Field(min_length=2, max_length=2)
    origin_postal_code: str | None = Field(default=None, max_length=20)
    origin_pickup_address: str | None = Field(default=None, max_length=400)
    destination_country: str = Field(min_length=2, max_length=3)
    destination_city_or_region: str | None = Field(default=None, max_length=160)
    destination_address: str | None = Field(default=None, max_length=400)
    recipient_type: Literal["HOME", "BUSINESS"] = "HOME"
    cargo_unit: CargoUnit
    description: str = Field(min_length=2, max_length=2000)
    pieces: int = Field(default=1, ge=1, le=10000)
    weight_lb: float | None = Field(default=None, ge=0)
    volume_cuft: float | None = Field(default=None, ge=0)
    urgent: bool = False
    temperature_controlled: bool = False
    dangerous_or_regulated: bool = False
    delivery_type: DeliveryType = "DOOR_TO_DOOR"
    customer_requests_terminal_delivery: bool = False


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


def final_delivery_policy(p: NationalIntake) -> dict:
    if p.customer_requests_terminal_delivery:
        return {"delivery_type": "TERMINAL_OPTIONAL", "door_to_door_default_overridden": True, "override_reason": "CUSTOMER_REQUEST"}
    return {
        "delivery_type": "DOOR_TO_BUSINESS" if p.recipient_type == "BUSINESS" else "DOOR_TO_DOOR",
        "door_to_door_default_overridden": False,
        "override_reason": None,
    }


@app.get("/us-network/health")
async def health():
    return {
        "status": "ok",
        "national_coverage": True,
        "operating_model": "VIRTUAL_HUBS_PLUS_PARTNER_FEEDER_NETWORK",
        "active_virtual_hubs": ["HOUSTON", "MIAMI"],
        "owned_warehouses_active": False,
        "future_owned_warehouses": ["HOUSTON", "MIAMI"],
        "primary_hubs": PRIMARY_HUBS,
        "asset_light_launch": True,
        "air_sea_separated": True,
        "universal_cargo_units": True,
        "customer_technical_knowledge_required": False,
        "door_to_door_default": True,
        "last_mile_included_in_route_design": True,
        "pod_required_for_completion": True,
    }


@app.post("/us-network/route")
async def route(p: NationalIntake):
    mode = recommend_mode(p)
    hub = recommend_hub(p)
    final_delivery = final_delivery_policy(p)
    return {
        "origin_zone": zone_for(p.origin_state),
        "recommended_hub": hub,
        "hub_owner": "SAHJONY",
        "hub_facility_type": "VIRTUAL_HUB",
        "recommended_mode": mode,
        "origin_leg": "HOME_OR_BUSINESS_PICKUP_TO_AUTHORIZED_PARTNER_AGENCY_OR_THIRD_PARTY_WAREHOUSE",
        "virtual_hub_leg": "SAHJONY_COORDINATES_RECEIVING_WEIGHING_PHOTOS_QR_STAGING_AND_CONSOLIDATION_THROUGH_AUTHORIZED_PROVIDERS",
        "domestic_leg": "LOCAL_PICKUP_OR_PARCEL_LTL_LINEHAUL_TO_SELECTED_VIRTUAL_HUB_PROVIDER",
        "international_leg": mode,
        "destination_leg": "CUSTOMS_TO_LAST_MILE_TO_FINAL_ADDRESS",
        "final_delivery": final_delivery,
        "pricing_rule": "Quote must include origin pickup/collection, domestic transfer, third-party warehouse or agency handling, international freight, customs/destination handling where applicable, last-mile delivery and POD unless explicitly disclosed otherwise.",
        "completion_rule": "Shipment is not complete until delivered to the final home/business address and POD is recorded, unless a customer-selected or legally required terminal exception applies.",
        "booking_status": "COMPLIANCE_REVIEW" if p.dangerous_or_regulated else "RATE_CAPACITY_AND_PROVIDER_REVIEW",
        "provider_rule": "No provider is represented as SAHJONY-owned unless a physical facility has actually been acquired or leased and activated.",
        "customer_message_rule": "Ask what, from where, to where, quantity/size and urgency. Do not require port, terminal, incoterm, HAWB or HBL from the customer at first contact.",
    }
