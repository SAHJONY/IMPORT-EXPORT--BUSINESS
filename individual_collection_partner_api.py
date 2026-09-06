from __future__ import annotations

import secrets
from typing import Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from agency_owner_api import now
from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY Individual Collection Partner Network", version="1.0.0", docs_url=None, redoc_url=None)
PartnerStatus = Literal["APPLIED","UNDER_REVIEW","APPROVED","SUSPENDED","REJECTED"]
CollectionStatus = Literal["CREATED","RECEIVED","WEIGHED","LABELED","READY_FOR_LINEHAUL","HANDED_OFF","EXCEPTION"]


def _owner(auth: str | None, role: str | None) -> None:
    if role != "owner": raise HTTPException(403, "Owner role required")
    if not auth or not auth.startswith("Bearer "): raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(auth.removeprefix("Bearer ").strip()): raise HTTPException(403, "Invalid owner credential")


class PartnerApplicationIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=180)
    phone: str = Field(min_length=7, max_length=80)
    email: str | None = Field(default=None, max_length=254)
    street_address: str = Field(min_length=5, max_length=300)
    city: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=40)
    postal_code: str = Field(min_length=3, max_length=20)
    service_radius_miles: int = Field(default=10, ge=0, le=150)
    max_daily_weight_lb: float = Field(default=250, gt=0, le=10000)
    home_dropoff_enabled: bool = True
    customer_pickup_enabled: bool = False
    has_verified_scale: bool = False
    has_secure_storage: bool = False
    accepts_terms: bool


class CollectionIn(BaseModel):
    partner_id: str = Field(min_length=4, max_length=120)
    customer_name: str = Field(min_length=2, max_length=180)
    customer_phone: str | None = Field(default=None, max_length=80)
    description: str = Field(min_length=2, max_length=1200)
    pieces: int = Field(default=1, ge=1, le=500)
    measured_weight_lb: float = Field(gt=0, le=5000)
    declared_value_usd: float | None = Field(default=None, ge=0)
    destination_country: str = Field(min_length=2, max_length=3)
    destination_city: str | None = Field(default=None, max_length=120)
    cargo_category: str = Field(default="GENERAL", max_length=80)
    customer_reference: str | None = Field(default=None, max_length=180)


class HandoffIn(BaseModel):
    collection_id: str = Field(min_length=4, max_length=120)
    from_partner_id: str = Field(min_length=4, max_length=120)
    to_party: str = Field(min_length=2, max_length=180)
    offline_event_id: str = Field(min_length=8, max_length=180)
    location: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=1200)


@app.get("/individual-collection/health")
async def health():
    p = persistent_backend_status()
    return {"status":"ok" if p.get("configured") else "configuration_required","nationwide_us":True,"home_collection_partners":True,"pickup_optional":True,"qr_chain_of_custody":True,"no_scan_no_handoff":True,"owner_approval_required":True,"regulated_cargo_fail_closed":True}


@app.post("/individual-collection/apply")
async def apply(p: PartnerApplicationIn):
    if not p.accepts_terms: raise HTTPException(422, "Program terms must be accepted")
    pid = "hcp_" + secrets.token_urlsafe(10); ts = now()
    row = {"partner_id":pid, **p.model_dump(exclude={"accepts_terms"}), "status":"APPLIED", "kyb_kyc_status":"REVIEW_REQUIRED", "cargo_authority":"NONE_UNTIL_APPROVED", "created_at":ts, "updated_at":ts}
    await get_backend().insert("logistics_individual_collection_partners", row)
    return {"partner_id":pid,"status":"APPLIED","message":"Application received and pending SAHJONY review."}


@app.patch("/individual-collection/owner/partners/{partner_id}")
async def review_partner(partner_id: str, status: PartnerStatus, authorization: str | None = Header(None, alias="Authorization"), x_role: str | None = Header(None, alias="X-Role")):
    _owner(authorization, x_role)
    patch = {"status":status,"cargo_authority":"GENERAL_APPROVED" if status=="APPROVED" else "NONE","updated_at":now()}
    updated = await get_backend().patch("logistics_individual_collection_partners", patch, params={"partner_id":f"eq.{partner_id}"})
    if not updated: raise HTTPException(404, "Partner not found")
    return {"partner_id":partner_id,"status":status}


@app.post("/individual-collection/collections")
async def create_collection(p: CollectionIn):
    rows = await get_backend().select("logistics_individual_collection_partners", params={"partner_id":f"eq.{p.partner_id}","limit":"1"}) or []
    if not rows or rows[0].get("status") != "APPROVED": raise HTTPException(409, "Partner is not approved for collections")
    partner = rows[0]
    if not partner.get("has_verified_scale"): raise HTTPException(409, "Verified scale required before weighing customer cargo")
    if p.measured_weight_lb > float(partner.get("max_daily_weight_lb") or 0): raise HTTPException(422, "Collection exceeds partner approved daily capacity")
    special = p.cargo_category.upper() in {"DANGEROUS_GOODS","REGULATED","FIREARM","EXPLOSIVE","HAZMAT"}
    if special: raise HTTPException(409, "Special or regulated cargo requires centralized compliance review before acceptance")
    cid = "col_" + secrets.token_urlsafe(10); tracking = "SHJ-COL-" + secrets.token_hex(4).upper(); ts = now()
    row = {"collection_id":cid,"tracking_reference":tracking,**p.model_dump(),"status":"WEIGHED","compliance_status":"REVIEW_REQUIRED","created_at":ts,"updated_at":ts}
    await get_backend().insert("logistics_individual_collections", row)
    return {"collection":row,"qr_payload":f"/collection-track/{cid}","next_step":"LABEL_AND_ROUTE_TO_HUB"}


@app.post("/individual-collection/handoffs")
async def handoff(p: HandoffIn):
    existing = await get_backend().select("logistics_collection_handoffs", params={"offline_event_id":f"eq.{p.offline_event_id}","limit":"1"}) or []
    if existing: return {"handoff":existing[0],"created":False,"idempotent_replay":True}
    rows = await get_backend().select("logistics_individual_collections", params={"collection_id":f"eq.{p.collection_id}","partner_id":f"eq.{p.from_partner_id}","limit":"1"}) or []
    if not rows: raise HTTPException(404, "Collection not found for this partner")
    ts = now(); row = {"handoff_id":"hnd_"+secrets.token_urlsafe(10),**p.model_dump(),"server_recorded_at":ts,"immutable":True}
    await get_backend().insert("logistics_collection_handoffs", row)
    await get_backend().patch("logistics_individual_collections", {"status":"HANDED_OFF","updated_at":ts}, params={"collection_id":f"eq.{p.collection_id}"})
    return {"handoff":row,"created":True,"no_scan_no_handoff":True}
