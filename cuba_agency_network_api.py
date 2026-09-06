from __future__ import annotations

import hashlib, hmac, os, secrets
from typing import Any, Literal
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from agency_owner_api import agency_actor, now
from insforge_backend import get_backend, persistent_backend_status

app=FastAPI(title="SAHJONY Cuba Agency Network OS",version="2.0.0",docs_url=None,redoc_url=None)
Stage=Literal["CREATED","AGENCY_RECEIVED","WAREHOUSE_IN","CONSOLIDATED","CARRIER_HANDOFF","DEPARTED_US","ARRIVED_CUBA","CUSTOMS_HOLD","CUSTOMS_RELEASED","LAST_MILE","DELIVERED_OK","DELIVERED_WITH_EXCEPTION","CANCELLED"]
Action=Literal["SCAN_IN","SCAN_OUT","HANDOFF","VERIFY","CONSOLIDATE","DECONSOLIDATE","DELIVER"]

def _secret(): return (os.getenv("AGENCY_TRACKING_SIGNING_SECRET") or os.getenv("OWNER_SESSION_SECRET") or "dev-agency-secret").encode()
def make_token(a,p):
    base=f"{a}.{p}"; sig=hmac.new(_secret(),base.encode(),hashlib.sha256).hexdigest()[:32]; return f"{base}.{sig}"
def read_token(t):
    try:a,p,s=t.split(".",2)
    except ValueError: raise HTTPException(404,"Tracking token invalid")
    e=hmac.new(_secret(),f"{a}.{p}".encode(),hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(s,e): raise HTTPException(404,"Tracking token invalid")
    return a,p

class PackageIn(BaseModel):
    recipient_name:str=Field(min_length=2,max_length=240); recipient_phone:str|None=Field(default=None,max_length=80); destination_province:str=Field(min_length=2,max_length=120); description:str=Field(min_length=2,max_length=1000); pieces:int=Field(default=1,ge=1,le=10000); weight_lb:float|None=Field(default=None,ge=0); declared_value:float|None=Field(default=None,ge=0); service_mode:str=Field(default="AIR",max_length=40); customer_reference:str|None=Field(default=None,max_length=180)
class CustodyIn(BaseModel):
    package_id:str=Field(min_length=4,max_length=180); action:Action; stage:Stage; employee_id:str|None=Field(default=None,max_length=180); from_party:str|None=Field(default=None,max_length=240); to_party:str|None=Field(default=None,max_length=240); location:str|None=Field(default=None,max_length=300); weight_lb:float|None=Field(default=None,ge=0); photo_refs:list[str]=Field(default_factory=list,max_length=20); offline_event_id:str=Field(min_length=8,max_length=180); client_captured_at:str|None=None; notes:str|None=Field(default=None,max_length=2000)
class ExceptionIn(BaseModel):
    package_id:str=Field(min_length=4,max_length=180); exception_type:str=Field(min_length=2,max_length=120); severity:Literal["LOW","MEDIUM","HIGH","CRITICAL"]="MEDIUM"; description:str=Field(min_length=2,max_length=3000); evidence_refs:list[str]=Field(default_factory=list,max_length=20)
class DeliveryIn(BaseModel):
    package_id:str=Field(min_length=4,max_length=180); recipient_name:str=Field(min_length=2,max_length=240); parcel_count:int=Field(default=1,ge=0,le=10000); condition:Literal["GOOD","DAMAGED","SHORTAGE","REFUSED","OTHER"]="GOOD"; recipient_confirmation:Literal["CONFIRMED_OK","CONFIRMED_PROBLEM","REFUSED","PENDING"]="PENDING"; signature_method:str|None=Field(default=None,max_length=40); signature_value:str|None=Field(default=None,max_length=4000); photo_refs:list[str]=Field(default_factory=list,max_length=20); offline_event_id:str=Field(min_length=8,max_length=180); comments:str|None=Field(default=None,max_length=2000)

async def pkg(a,pid):
    r=await get_backend().select("logistics_agency_packages",params={"agency_id":f"eq.{a['agency_id']}","package_id":f"eq.{pid}","limit":"1"}) or []
    if not r: raise HTTPException(404,"Package not found in this agency")
    return r[0]
async def once(table,row,a,eid):
    r=await get_backend().select(table,params={"agency_id":f"eq.{a}","offline_event_id":f"eq.{eid}","limit":"1"}) or []
    if r:return r[0],False
    await get_backend().insert(table,row); return row,True

@app.get("/agency-network/health")
async def health():
    p=persistent_backend_status(); return {"status":"ok" if p.get("configured") else "configuration_required","browser_pwa":True,"installation_required":False,"offline_idempotent":True,"immutable_custody":True,"dual_delivery_confirmation":True,"carrier_neutral":True,"payment_neutral":True,"paperless_printable":True,"exception_claims_engine":True}

@app.post("/agency-network/packages")
async def create_package(p:PackageIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); ts=now(); pid="pkg_"+secrets.token_urlsafe(12); tracking="SHJ-"+secrets.token_hex(5).upper(); token=make_token(a["agency_id"],pid)
    row={"package_id":pid,"agency_id":a["agency_id"],"tracking_reference":tracking,**p.model_dump(),"stage":"CREATED","status":"ACTIVE","public_tracking_token":token,"created_at":ts,"updated_at":ts}
    await get_backend().insert("logistics_agency_packages",row); return {"package":row,"qr_payload":f"/track-agency/{token}"}

@app.post("/agency-network/custody")
async def custody(p:CustodyIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); old=await pkg(a,p.package_id); ts=now(); row={"custody_event_id":"cst_"+secrets.token_urlsafe(12),"agency_id":a["agency_id"],**p.model_dump(),"server_recorded_at":ts,"immutable":True}
    saved,created=await once("logistics_agency_custody_events",row,a["agency_id"],p.offline_event_id)
    if created:
        patch={"stage":p.stage,"last_location":p.location,"updated_at":ts}
        if p.weight_lb is not None and old.get("weight_lb") is not None:
            d=round(float(p.weight_lb)-float(old["weight_lb"]),2); patch["weight_variance_lb"]=d
            if abs(d)>=1: patch["status"]="EXCEPTION"
        await get_backend().patch("logistics_agency_packages",patch,params={"agency_id":f"eq.{a['agency_id']}","package_id":f"eq.{p.package_id}"})
    return {"event":saved,"created":created,"idempotent_replay":not created,"no_scan_no_handoff":True}

@app.post("/agency-network/exceptions")
async def create_exception(p:ExceptionIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); await pkg(a,p.package_id); ts=now(); eid="exc_"+secrets.token_urlsafe(10); row={"exception_id":eid,"agency_id":a["agency_id"],**p.model_dump(),"status":"OPEN","created_at":ts,"updated_at":ts}
    await get_backend().insert("logistics_agency_exceptions",row); await get_backend().patch("logistics_agency_packages",{"status":"EXCEPTION","updated_at":ts},params={"agency_id":f"eq.{a['agency_id']}","package_id":f"eq.{p.package_id}"}); return {"exception":row}

@app.post("/agency-network/deliveries")
async def delivery(p:DeliveryIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); await pkg(a,p.package_id); ts=now(); sig=hashlib.sha256(p.signature_value.encode()).hexdigest() if p.signature_value else None; ok=p.condition=="GOOD" and p.recipient_confirmation=="CONFIRMED_OK"; stage="DELIVERED_OK" if ok else "DELIVERED_WITH_EXCEPTION"
    row={"delivery_id":"pod_"+secrets.token_urlsafe(10),"agency_id":a["agency_id"],**p.model_dump(exclude={"signature_value"}),"signature_hash":sig,"stage":stage,"server_recorded_at":ts}
    saved,created=await once("logistics_agency_deliveries",row,a["agency_id"],p.offline_event_id)
    if created:
        await get_backend().patch("logistics_agency_packages",{"stage":stage,"status":"DELIVERED" if ok else "EXCEPTION","updated_at":ts},params={"agency_id":f"eq.{a['agency_id']}","package_id":f"eq.{p.package_id}"})
        if not ok:
            await get_backend().insert("logistics_agency_exceptions",{"exception_id":"exc_"+secrets.token_urlsafe(10),"agency_id":a["agency_id"],"package_id":p.package_id,"exception_type":"DELIVERY_EXCEPTION","severity":"HIGH","description":p.comments or p.condition,"status":"OPEN","created_at":ts,"updated_at":ts})
    return {"delivery":saved,"created":created,"final_stage":stage,"claim_opened":created and not ok,"signature_value_persisted":False}

@app.get("/agency-network/public/{token}")
async def public_tracking(token:str):
    aid,pid=read_token(token); rows=await get_backend().select("logistics_agency_packages",params={"agency_id":f"eq.{aid}","package_id":f"eq.{pid}","limit":"1"}) or []
    if not rows: raise HTTPException(404,"Tracking not found")
    r=rows[0]; return {"tracking_reference":r.get("tracking_reference"),"stage":r.get("stage"),"status":r.get("status"),"destination_province":r.get("destination_province"),"last_location":r.get("last_location"),"updated_at":r.get("updated_at")}


class CanadaCorridorIn(BaseModel):
    origin_city:str=Field(min_length=2,max_length=120)
    origin_province:str=Field(min_length=2,max_length=80)
    destination_province_cuba:str=Field(min_length=2,max_length=120)
    transport_mode:str=Field(default="AIR",max_length=20)
    cargo_type:str=Field(default="NON_COMMERCIAL",max_length=40)
    currency:str=Field(default="CAD",max_length=3)
    declared_value:float|None=Field(default=None,ge=0)
    country_of_origin:str|None=Field(default=None,max_length=3)
    hs_code:str|None=Field(default=None,max_length=32)
    export_reporting_status:str=Field(default="REVIEW_REQUIRED",max_length=40)
    permit_status:str=Field(default="REVIEW_REQUIRED",max_length=40)
    carrier_choice:str=Field(default="AGENCY_CHOICE",max_length=120)

@app.post("/agency-network/canada-cuba/corridors")
async def create_canada_corridor(p:CanadaCorridorIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); ts=now(); cid="ca_"+secrets.token_urlsafe(10)
    mode=p.transport_mode.upper(); cargo=p.cargo_type.upper(); curr=p.currency.upper()
    if mode not in {"AIR","SEA","MULTIMODAL"}: raise HTTPException(422,"Unsupported Canada-Cuba transport mode")
    if cargo not in {"NON_COMMERCIAL","COMMERCIAL"}: raise HTTPException(422,"Unsupported cargo type")
    if curr not in {"CAD","USD"}: raise HTTPException(422,"Canada-Cuba corridor supports CAD or USD")
    ready=(p.export_reporting_status.upper()=="CLEARED" and p.permit_status.upper() in {"CLEARED","NOT_REQUIRED"} and bool(p.country_of_origin) and bool(p.hs_code))
    row={"corridor_id":cid,"agency_id":a["agency_id"],**p.model_dump(),"transport_mode":mode,"cargo_type":cargo,"currency":curr,"booking_ready":ready,"status":"READY_TO_BOOK" if ready else "COMPLIANCE_REVIEW","created_at":ts,"updated_at":ts}
    await get_backend().insert("logistics_canada_cuba_corridors",row)
    return {"corridor":row,"booking_gate":{"country_of_origin_required":True,"hs_code_required":True,"export_reporting_required":True,"permit_review_required":True}}

@app.get("/agency-network/canada-cuba/corridors")
async def list_canada_corridors(x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); rows=await get_backend().select("logistics_canada_cuba_corridors",params={"agency_id":f"eq.{a['agency_id']}","order":"created_at.desc","limit":"500"}) or []
    return {"corridors":rows,"supported_origins":["Toronto","Montreal","Other Canada"],"currencies":["CAD","USD"],"carrier_neutral":True}
