from __future__ import annotations

from typing import Literal
from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="SAHJONY US National Shipping Network", version="1.4.0", docs_url=None, redoc_url=None)

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

GATEWAY_HUBS = {
    "HOUSTON": {"state": "TX", "gateway_roles": ["AIR", "SEA", "LINEHAUL", "CONSOLIDATION", "VEHICLE_STAGING"]},
    "MIAMI": {"state": "FL", "gateway_roles": ["AIR", "SEA", "CARIBBEAN", "CONSOLIDATION", "VEHICLE_STAGING"]},
}

VIRTUAL_HUB_POLICY = {
    "activation_rule": "A city becomes an active virtual hub only when at least one agency/partner/provider is verified and capacity is confirmed.",
    "facility_rule": "Virtual hubs are coordination nodes, not SAHJONY-owned facilities unless separately acquired/leased and activated.",
    "partner_types": ["AGENCY", "HOME_COLLECTION_PARTNER", "THIRD_PARTY_WAREHOUSE", "FORWARDER", "CARRIER_AGENT"],
    "required_capabilities": ["RECEIVE_OR_PICKUP", "WEIGH", "PACKAGE_ID_OR_QR", "CHAIN_OF_CUSTODY", "SAFE_STAGING", "HANDOFF"],
}

class NationalIntake(BaseModel):
    origin_state: str = Field(min_length=2, max_length=2)
    origin_city: str | None = Field(default=None, max_length=160)
    origin_postal_code: str | None = Field(default=None, max_length=20)
    origin_pickup_address: str | None = Field(default=None, max_length=400)
    local_verified_agency_available: bool = False
    local_provider_reference: str | None = Field(default=None, max_length=180)
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


def recommend_gateway(p: NationalIntake) -> str:
    zone = zone_for(p.origin_state)
    if zone in {"TEXAS_GULF", "MIDWEST", "SOUTHEAST"}:
        return "HOUSTON"
    return "MIAMI"


def recommend_collection_hub(p: NationalIntake) -> dict:
    if p.local_verified_agency_available and p.origin_city:
        return {
            "hub_type": "LOCAL_CITY_VIRTUAL_HUB",
            "hub_city": p.origin_city.upper(),
            "hub_state": p.origin_state.upper(),
            "provider_reference": p.local_provider_reference,
        }
    gateway = recommend_gateway(p)
    return {
        "hub_type": "GATEWAY_VIRTUAL_HUB",
        "hub_city": gateway,
        "hub_state": GATEWAY_HUBS[gateway]["state"],
        "provider_reference": None,
    }


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
        "operating_model": "DISTRIBUTED_CITY_VIRTUAL_HUB_NETWORK",
        "city_virtual_hubs_dynamic": True,
        "virtual_hub_activation_requires_verified_provider": True,
        "gateway_hubs": GATEWAY_HUBS,
        "virtual_hub_policy": VIRTUAL_HUB_POLICY,
        "owned_warehouses_active": False,
        "asset_light_launch": True,
        "air_sea_separated": True,
        "universal_cargo_units": True,
        "door_to_door_default": True,
        "last_mile_included_in_route_design": True,
        "pod_required_for_completion": True,
    }


@app.post("/us-network/route")
async def route(p: NationalIntake):
    mode = recommend_mode(p)
    collection_hub = recommend_collection_hub(p)
    gateway = recommend_gateway(p)
    final_delivery = final_delivery_policy(p)
    return {
        "origin_zone": zone_for(p.origin_state),
        "collection_hub": collection_hub,
        "gateway_hub": gateway,
        "recommended_mode": mode,
        "origin_leg": "HOME_OR_BUSINESS_PICKUP_TO_NEAREST_VERIFIED_CITY_AGENCY_OR_PARTNER",
        "city_hub_leg": "LOCAL_CITY_VIRTUAL_HUB_RECEIVE_WEIGH_PHOTO_QR_STAGE_AND_HANDOFF",
        "domestic_leg": "CONSOLIDATED_LINEHAUL_FROM_CITY_VIRTUAL_HUB_TO_SELECTED_GATEWAY_WHEN_NEEDED",
        "international_leg": mode,
        "destination_leg": "CUSTOMS_TO_LAST_MILE_TO_FINAL_ADDRESS",
        "final_delivery": final_delivery,
        "pricing_rule": "Quote must compare the local city-hub path versus direct gateway path and include pickup, city handling, domestic linehaul where needed, international freight, destination handling, last-mile delivery and POD.",
        "completion_rule": "Shipment is not complete until delivered to the final home/business address and POD is recorded, unless a customer-selected or legally required terminal exception applies.",
        "booking_status": "COMPLIANCE_REVIEW" if p.dangerous_or_regulated else "RATE_CAPACITY_AND_PROVIDER_REVIEW",
        "provider_rule": "A virtual hub may be advertised as active only after the local agency/partner/provider is verified and capacity is confirmed.",
        "customer_message_rule": "Ask what, from where, to where, quantity/size and urgency. The system chooses the nearest verified city hub and best gateway; do not require the customer to choose a port, terminal or carrier.",
    }
