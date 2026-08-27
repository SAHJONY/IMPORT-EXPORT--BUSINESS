from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY Wi-Fi Connectivity", version="1.0.0", docs_url=None, redoc_url=None)

FundingMode = Literal["local_only", "sponsor_funded", "community_funded", "business_funded", "customer_backhaul"]
BackhaulType = Literal["none", "fiber", "cable", "cellular", "starlink", "other"]
SiteStatus = Literal["REQUESTED", "DESIGN", "WAITING_BACKHAUL", "READY_FOR_INSTALL", "ACTIVE", "PAUSED", "CLOSED"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


class HotspotRequest(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    country: str = Field(min_length=2, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=500)
    contact_name: str | None = Field(default=None, max_length=160)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=80)
    funding_mode: FundingMode = "local_only"
    backhaul_type: BackhaulType = "none"
    free_to_end_user: bool = True
    estimated_users: int = Field(default=25, ge=1, le=100000)
    enable_local_text: bool = True
    enable_local_voice: bool = True
    enable_local_video: bool = True
    enable_captive_portal: bool = True
    enable_internet_when_available: bool = True
    notes: str | None = Field(default=None, max_length=3000)


class HotspotUpdate(BaseModel):
    status: SiteStatus
    backhaul_verified: bool | None = None
    provider_terms_verified: bool | None = None
    owner_note: str | None = Field(default=None, max_length=3000)


@app.get("/connectivity/wifi/health")
async def health() -> dict[str, Any]:
    persistence = persistent_backend_status()
    return {
        "status": "ok" if persistence.get("configured") else "configuration_required",
        "service": "sahjony-free-wifi-connectivity",
        "version": "1.0.0",
        "free_to_end_user_supported": True,
        "internet_is_not_claimed_free": True,
        "modes": {
            "local_only": {
                "internet_required": False,
                "end_user_fee_required": False,
                "supports": ["local_text", "local_voice", "local_video", "local_file_transfer", "local_presence"],
            },
            "sponsor_funded": {
                "internet_required": True,
                "end_user_fee_required": False,
                "backhaul_paid_by": "sponsor_or_host",
            },
            "customer_backhaul": {
                "internet_required": True,
                "end_user_fee_required": False,
                "backhaul_paid_by": "customer_or_site_owner",
            },
        },
        "network_components": [
            "wifi_access_points", "captive_portal", "local_lan_services", "webrtc_lan",
            "direct_text_lan", "optional_turn_relay", "backhaul_router", "offline_queue",
            "quality_of_service", "device_isolation", "rate_limits", "abuse_controls",
        ],
        "supported_backhaul": ["fiber", "cable", "cellular", "starlink", "other"],
        "provider_terms_must_allow_sharing": True,
        "no_unauthorized_resale_or_activation_bypass": True,
        "fail_closed": True,
        "persistence": persistence,
    }


@app.post("/connectivity/wifi/sites")
async def create_site(payload: HotspotRequest, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    if not persistent_backend_status().get("configured"):
        raise HTTPException(503, "Durable persistence is required")
    if payload.funding_mode == "local_only" and payload.backhaul_type != "none":
        raise HTTPException(422, "local_only sites must use backhaul_type=none until Internet backhaul is separately verified")
    site_id = f"wifi_{secrets.token_urlsafe(12)}"
    ts = _now()
    row = {
        "site_id": site_id,
        "status": "REQUESTED",
        "name": payload.name,
        "country": payload.country,
        "city": payload.city,
        "address": payload.address,
        "contact_name": payload.contact_name,
        "contact_email": payload.contact_email,
        "contact_phone": payload.contact_phone,
        "funding_mode": payload.funding_mode,
        "backhaul_type": payload.backhaul_type,
        "free_to_end_user": payload.free_to_end_user,
        "estimated_users": payload.estimated_users,
        "enable_local_text": payload.enable_local_text,
        "enable_local_voice": payload.enable_local_voice,
        "enable_local_video": payload.enable_local_video,
        "enable_captive_portal": payload.enable_captive_portal,
        "enable_internet_when_available": payload.enable_internet_when_available,
        "backhaul_verified": payload.backhaul_type == "none",
        "provider_terms_verified": payload.backhaul_type == "none",
        "internet_enabled": False,
        "notes": payload.notes,
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("wifi_connectivity_sites", row)
    return {
        "status": "REQUESTED",
        "site_id": site_id,
        "local_network_can_operate_without_internet": True,
        "internet_enabled": False,
        "internet_gate": None if payload.backhaul_type == "none" else "BACKHAUL_AND_PROVIDER_TERMS_VERIFICATION_REQUIRED",
        "free_to_end_user": payload.free_to_end_user,
    }


@app.get("/connectivity/wifi/sites")
async def list_sites(authorization: str | None = Header(None, alias="Authorization"), limit: int = 200):
    _owner(authorization)
    rows = await get_backend().select("wifi_connectivity_sites", params={"order": "updated_at.desc", "limit": str(max(1, min(limit, 500)))})
    return {"status": "ok", "count": len(rows or []), "sites": rows or []}


@app.post("/connectivity/wifi/sites/{site_id}/status")
async def update_site(site_id: str, payload: HotspotUpdate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    rows = await get_backend().select("wifi_connectivity_sites", params={"site_id": f"eq.{site_id}", "limit": "1"})
    if not rows:
        raise HTTPException(404, "Wi-Fi site not found")
    current = rows[0]
    backhaul_verified = current.get("backhaul_verified") if payload.backhaul_verified is None else payload.backhaul_verified
    terms_verified = current.get("provider_terms_verified") if payload.provider_terms_verified is None else payload.provider_terms_verified
    internet_enabled = bool(current.get("backhaul_type") != "none" and backhaul_verified and terms_verified and payload.status == "ACTIVE")
    values: dict[str, Any] = {
        "status": payload.status,
        "backhaul_verified": bool(backhaul_verified),
        "provider_terms_verified": bool(terms_verified),
        "internet_enabled": internet_enabled,
        "updated_at": _now(),
    }
    if payload.owner_note is not None:
        values["owner_note"] = payload.owner_note
    updated = await get_backend().patch("wifi_connectivity_sites", values, params={"site_id": f"eq.{site_id}"})
    return {
        "status": "updated",
        "site_id": site_id,
        "internet_enabled": internet_enabled,
        "local_services_enabled": payload.status in {"READY_FOR_INSTALL", "ACTIVE"},
        "fail_closed": True,
        "record": updated[0] if updated else None,
    }
