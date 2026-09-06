from __future__ import annotations

import hashlib, os, secrets
from datetime import datetime, timezone
from typing import Any
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY Agency Owner Command Center", version="1.0.0", docs_url=None, redoc_url=None)
ORG="org_sahjony_global_trade"

def now(): return datetime.now(timezone.utc).isoformat()
def digest(v:str): return hashlib.sha256(v.encode()).hexdigest()
def owner(auth):
    if not auth or not auth.startswith("Bearer ") or not verify_owner_token(auth.removeprefix("Bearer ").strip()): raise HTTPException(403,"Owner authorization required")

async def agency_actor(agency_id:str|None, auth:str|None):
    if not agency_id: raise HTTPException(400,"X-Agency-Id required")
    if not auth or not auth.startswith("Bearer "): raise HTTPException(401,"Missing Authorization")
    token=auth.removeprefix("Bearer ").strip(); rows=await get_backend().select("logistics_agency_owner_credentials",params={"agency_id":f"eq.{agency_id}","token_hash":f"eq.{digest(token)}","status":"eq.active","limit":"1"}) or []
    if not rows: raise HTTPException(403,"Invalid agency owner credential")
    return {"role":"agency_owner","agency_id":agency_id,"owner_id":rows[0].get("owner_id")}

class AgencyIn(BaseModel):
    legal_name:str=Field(min_length=2,max_length=240); display_name:str|None=Field(default=None,max_length=240); owner_name:str=Field(min_length=2,max_length=240); owner_phone:str|None=Field(default=None,max_length=80); owner_email:str|None=Field(default=None,max_length=240); country:str=Field(default="US",max_length=3)
class EmployeeIn(BaseModel):
    full_name:str=Field(min_length=2,max_length=240); phone:str|None=Field(default=None,max_length=80); photo_url:str|None=Field(default=None,max_length=2000); emergency_phone:str|None=Field(default=None,max_length=80); branch_id:str|None=Field(default=None,max_length=160); role:str=Field(default="operator",max_length=80); permissions:list[str]=Field(default_factory=list,max_length=50)
class EmployeeAccessPatch(BaseModel):
    role:str|None=Field(default=None,max_length=80); branch_id:str|None=Field(default=None,max_length=160); permissions:list[str]|None=Field(default=None,max_length=50); status:str|None=Field(default=None,max_length=40)
class ShipmentIn(BaseModel):
    tracking_reference:str=Field(min_length=4,max_length=120); customer_name:str|None=Field(default=None,max_length=240); origin:str|None=Field(default=None,max_length=240); destination:str|None=Field(default=None,max_length=240); carrier_choice:str=Field(default="AGENCY_CHOICE",max_length=120); weight_lb:float|None=Field(default=None,ge=0); customer_price:float|None=Field(default=None,ge=0); agency_cost:float|None=Field(default=None,ge=0)
class CarrierPreferenceIn(BaseModel):
    mode:str=Field(default="OPEN_CHOICE",max_length=80); preferred_provider:str|None=Field(default=None,max_length=240); use_sahjony_when_better:bool=True

@app.get("/agency-os/health")
async def health():
    p=persistent_backend_status(); return {"status":"ok" if p.get("configured") else "configuration_required","service":"agency-owner-command-center","multi_tenant":True,"agency_data_isolation":True,"sahjony_internal_economics_hidden":True,"carrier_choice_open":True,"offline_pwa_ready":True}

@app.post("/agency-os/agencies")
async def create_agency(p:AgencyIn, authorization:str|None=Header(None,alias="Authorization")):
    owner(authorization); aid="agy_"+secrets.token_urlsafe(12); oid="ago_"+secrets.token_urlsafe(10); raw=secrets.token_urlsafe(32); ts=now()
    agency={"agency_id":aid,"organization_id":ORG,**p.model_dump(),"status":"active","carrier_mode":"OPEN_CHOICE","created_at":ts,"updated_at":ts}
    cred={"credential_id":"agc_"+secrets.token_urlsafe(10),"agency_id":aid,"owner_id":oid,"owner_name":p.owner_name,"token_hash":digest(raw),"status":"active","created_at":ts,"updated_at":ts}
    await get_backend().insert("logistics_agencies",agency); await get_backend().insert("logistics_agency_owner_credentials",cred)
    return {"agency":agency,"owner_id":oid,"owner_access_token":raw,"token_shown_once":True}

@app.get("/agency-os/me")
async def me(x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); rows=await get_backend().select("logistics_agencies",params={"agency_id":f"eq.{a['agency_id']}","limit":"1"}) or []
    if not rows: raise HTTPException(404,"Agency not found")
    r=dict(rows[0]); [r.pop(k,None) for k in ("sahjony_cost","sahjony_margin","internal_rate_card")]; return {"agency":r,"actor":a}

@app.get("/agency-os/summary")
async def summary(x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); aid=a["agency_id"]
    ships=await get_backend().select("logistics_agency_shipments",params={"agency_id":f"eq.{aid}","order":"updated_at.desc","limit":"1000"}) or []
    emps=await get_backend().select("logistics_agency_employees",params={"agency_id":f"eq.{aid}","status":"eq.active","limit":"1000"}) or []
    revenue=sum(float(x.get("customer_price") or 0) for x in ships); cost=sum(float(x.get("agency_cost") or 0) for x in ships); exceptions=sum(1 for x in ships if str(x.get("status") or "").upper()=="EXCEPTION")
    delivered=sum(1 for x in ships if str(x.get("status") or "").upper().startswith("DELIVERED")); active=max(0,len(ships)-delivered)
    return {"agency_id":aid,"metrics":{"shipments":len(ships),"active":active,"delivered":delivered,"exceptions":exceptions,"employees":len(emps),"revenue":round(revenue,2),"agency_cost":round(cost,2),"gross_profit":round(revenue-cost,2)},"privacy":{"other_agencies_visible":False,"sahjony_internal_cost_visible":False}}

@app.post("/agency-os/employees")
async def add_employee(p:EmployeeIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); eid="age_"+secrets.token_urlsafe(10); ts=now(); qr="EMP-"+secrets.token_urlsafe(16)
    row={"employee_id":eid,"agency_id":a["agency_id"],**p.model_dump(),"employee_qr_token":qr,"status":"pending_verification","access_granted_by_owner_id":a["owner_id"],"access_granted_at":ts,"created_at":ts,"updated_at":ts}; await get_backend().insert("logistics_agency_employees",row); return {"employee":row,"authority":"AGENCY_OWNER"}

@app.get("/agency-os/employees")
async def employees(x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); rows=await get_backend().select("logistics_agency_employees",params={"agency_id":f"eq.{a['agency_id']}","order":"created_at.desc","limit":"500"}) or []; return {"employees":rows}


@app.patch("/agency-os/employees/{employee_id}/access")
async def update_employee_access(employee_id:str,p:EmployeeAccessPatch,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization)
    rows=await get_backend().select("logistics_agency_employees",params={"employee_id":f"eq.{employee_id}","agency_id":f"eq.{a['agency_id']}","limit":"1"}) or []
    if not rows: raise HTTPException(404,"Employee not found in this agency")
    patch={k:v for k,v in p.model_dump().items() if v is not None}
    if patch.get("status") not in {None,"pending_verification","active","suspended","terminated"}: raise HTTPException(422,"Invalid employee status")
    patch.update({"access_granted_by_owner_id":a["owner_id"],"access_granted_at":now(),"updated_at":now()})
    await get_backend().patch("logistics_agency_employees",patch,params={"employee_id":f"eq.{employee_id}","agency_id":f"eq.{a['agency_id']}"})
    return {"employee_id":employee_id,"agency_id":a["agency_id"],"access":patch,"authority":"AGENCY_OWNER"}

@app.post("/agency-os/shipments")
async def add_shipment(p:ShipmentIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); sid="ags_"+secrets.token_urlsafe(12); ts=now(); row={"agency_shipment_id":sid,"agency_id":a["agency_id"],**p.model_dump(),"status":"CREATED","created_at":ts,"updated_at":ts}; await get_backend().insert("logistics_agency_shipments",row); return {"shipment":row}

@app.get("/agency-os/shipments")
async def shipments(x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); rows=await get_backend().select("logistics_agency_shipments",params={"agency_id":f"eq.{a['agency_id']}","order":"updated_at.desc","limit":"500"}) or []; return {"shipments":rows}

@app.post("/agency-os/carrier-preference")
async def carrier_preference(p:CarrierPreferenceIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); row={"carrier_mode":p.mode,"preferred_provider":p.preferred_provider,"use_sahjony_when_better":p.use_sahjony_when_better,"updated_at":now()}; await get_backend().patch("logistics_agencies",row,params={"agency_id":f"eq.{a['agency_id']}"}); return {"agency_id":a["agency_id"],**row}
