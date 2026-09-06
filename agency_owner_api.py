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


class PaymentProviderIn(BaseModel):
    provider_name:str=Field(min_length=2,max_length=120)
    provider_type:str=Field(default="EXTERNAL_POS",max_length=40)
    terminal_id:str|None=Field(default=None,max_length=160)
    location_id:str|None=Field(default=None,max_length=160)
    currency:str=Field(default="USD",min_length=3,max_length=3)
    integration_mode:str=Field(default="REFERENCE_ONLY",max_length=40)

class AgencyPaymentIn(BaseModel):
    amount:float=Field(gt=0)
    currency:str=Field(default="USD",min_length=3,max_length=3)
    method:str=Field(max_length=40)
    provider_id:str|None=Field(default=None,max_length=160)
    external_reference:str=Field(min_length=2,max_length=240)
    agency_shipment_id:str|None=Field(default=None,max_length=180)
    customer_reference:str|None=Field(default=None,max_length=180)
    terminal_id:str|None=Field(default=None,max_length=160)
    fee_amount:float=Field(default=0,ge=0)
    card_brand:str|None=Field(default=None,max_length=40)
    card_last4:str|None=Field(default=None,pattern=r"^\d{4}$")
    status:str=Field(default="CAPTURED",max_length=40)
    note:str|None=Field(default=None,max_length=1200)

class SettlementIn(BaseModel):
    payment_ids:list[str]=Field(min_length=1,max_length=500)
    settlement_reference:str=Field(min_length=2,max_length=240)
    settled_amount:float=Field(gt=0)
    fee_amount:float=Field(default=0,ge=0)
    currency:str=Field(default="USD",min_length=3,max_length=3)

class PaperlessRecordIn(BaseModel):
    record_type:str=Field(min_length=2,max_length=80)
    title:str=Field(min_length=2,max_length=240)
    related_type:str|None=Field(default=None,max_length=80)
    related_id:str|None=Field(default=None,max_length=180)
    content:dict[str,Any]=Field(default_factory=dict)
    signer_name:str|None=Field(default=None,max_length=240)
    signer_phone:str|None=Field(default=None,max_length=80)
    signature_method:str|None=Field(default=None,max_length=40)
    signature_value:str|None=Field(default=None,max_length=4000)
    customer_visible:bool=False

class PaperlessStatusPatch(BaseModel):
    status:str=Field(max_length=40)
    note:str|None=Field(default=None,max_length=2000)

@app.get("/agency-os/health")
async def health():
    p=persistent_backend_status(); return {"status":"ok" if p.get("configured") else "configuration_required","service":"agency-owner-command-center","multi_tenant":True,"agency_data_isolation":True,"sahjony_internal_economics_hidden":True,"carrier_choice_open":True,"offline_pwa_ready":True,"paperless_by_default":True,"electronic_signatures":True,"paper_required_only_by_exception":True,"payment_agnostic":True,"any_pos_reference_supported":True,"sensitive_card_data_stored":False}

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


@app.post("/agency-os/paperless/records")
async def create_paperless_record(p:PaperlessRecordIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); ts=now(); rid="apr_"+secrets.token_urlsafe(12)
    sig_hash=None
    if p.signature_value:
        sig_hash=hashlib.sha256(p.signature_value.encode()).hexdigest()
    row={"record_id":rid,"agency_id":a["agency_id"],"record_type":p.record_type.upper(),"title":p.title,"related_type":p.related_type,"related_id":p.related_id,"content":p.content,"signer_name":p.signer_name,"signer_phone":p.signer_phone,"signature_method":p.signature_method,"signature_hash":sig_hash,"status":"SIGNED" if sig_hash else "DRAFT","customer_visible":p.customer_visible,"created_by_owner_id":a["owner_id"],"created_at":ts,"updated_at":ts}
    await get_backend().insert("logistics_agency_paperless_records",row)
    return {"record":row,"paperless":True,"signature_value_persisted":False}

@app.get("/agency-os/paperless/records")
async def list_paperless_records(x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); rows=await get_backend().select("logistics_agency_paperless_records",params={"agency_id":f"eq.{a['agency_id']}","order":"created_at.desc","limit":"1000"}) or []
    return {"records":rows,"paperless_by_default":True}

@app.patch("/agency-os/paperless/records/{record_id}/status")
async def update_paperless_status(record_id:str,p:PaperlessStatusPatch,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization)
    if p.status not in {"DRAFT","SIGNED","APPROVED","RELEASED","VOID","SUPERSEDED"}: raise HTTPException(422,"Invalid paperless record status")
    rows=await get_backend().select("logistics_agency_paperless_records",params={"record_id":f"eq.{record_id}","agency_id":f"eq.{a['agency_id']}","limit":"1"}) or []
    if not rows: raise HTTPException(404,"Paperless record not found in this agency")
    patch={"status":p.status,"status_note":p.note,"updated_at":now(),"updated_by_owner_id":a["owner_id"]}
    await get_backend().patch("logistics_agency_paperless_records",patch,params={"record_id":f"eq.{record_id}","agency_id":f"eq.{a['agency_id']}"})
    return {"record_id":record_id,"status":p.status,"authority":"AGENCY_OWNER"}


@app.get("/agency-os/paperless/{record_id}/print")
async def printable_record(record_id:str,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization)
    rows=await get_backend().select("logistics_agency_paperless_records",params={"record_id":f"eq.{record_id}","agency_id":f"eq.{a['agency_id']}","limit":"1"}) or []
    if not rows: raise HTTPException(404,"Paperless record not found in this agency")
    r=dict(rows[0])
    for k in ("signature_value","signature_secret","raw_signature"):
        r.pop(k,None)
    return {"record":r,"print_authorized":True,"paperless_default":True,"printing_optional":True,"agency_id":a["agency_id"]}


@app.post("/agency-os/payments/providers")
async def add_payment_provider(p:PaymentProviderIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); ts=now(); pid="app_"+secrets.token_urlsafe(10)
    row={"provider_id":pid,"agency_id":a["agency_id"],**p.model_dump(),"currency":p.currency.upper(),"status":"active","created_by_owner_id":a["owner_id"],"created_at":ts,"updated_at":ts}
    await get_backend().insert("logistics_agency_payment_providers",row)
    return {"provider":row,"provider_agnostic":True}

@app.get("/agency-os/payments/providers")
async def payment_providers(x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); rows=await get_backend().select("logistics_agency_payment_providers",params={"agency_id":f"eq.{a['agency_id']}","order":"created_at.desc","limit":"200"}) or []
    return {"providers":rows,"supported_modes":["REFERENCE_ONLY","API","WEBHOOK","QR","CASH","BANK_TRANSFER","EXTERNAL_POS"]}

@app.post("/agency-os/payments")
async def record_payment(p:AgencyPaymentIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization)
    if p.status not in {"PENDING","AUTHORIZED","CAPTURED","SETTLED","REFUNDED","VOIDED","DISPUTED","FAILED"}: raise HTTPException(422,"Invalid payment status")
    if p.card_last4 and p.method.upper() not in {"CARD","CREDIT_CARD","DEBIT_CARD","EXTERNAL_POS"}: raise HTTPException(422,"card_last4 only applies to card/POS methods")
    if p.provider_id:
        prov=await get_backend().select("logistics_agency_payment_providers",params={"provider_id":f"eq.{p.provider_id}","agency_id":f"eq.{a['agency_id']}","status":"eq.active","limit":"1"}) or []
        if not prov: raise HTTPException(404,"Payment provider not found in this agency")
    ts=now(); payid="apy_"+secrets.token_urlsafe(12)
    row={"payment_id":payid,"agency_id":a["agency_id"],**p.model_dump(),"currency":p.currency.upper(),"net_amount":round(p.amount-p.fee_amount,2),"recorded_by_owner_id":a["owner_id"],"created_at":ts,"updated_at":ts}
    await get_backend().insert("logistics_agency_payments",row)
    safe=dict(row); safe.pop("provider_payload",None)
    return {"payment":safe,"pci_scope":"REFERENCE_ONLY","pan_stored":False,"cvv_stored":False}

@app.get("/agency-os/payments")
async def list_payments(x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); rows=await get_backend().select("logistics_agency_payments",params={"agency_id":f"eq.{a['agency_id']}","order":"created_at.desc","limit":"1000"}) or []
    return {"payments":rows}

@app.post("/agency-os/payments/settlements")
async def record_settlement(p:SettlementIn,x_agency_id:str|None=Header(None,alias="X-Agency-Id"),authorization:str|None=Header(None,alias="Authorization")):
    a=await agency_actor(x_agency_id,authorization); rows=[]
    for pid in p.payment_ids:
        found=await get_backend().select("logistics_agency_payments",params={"payment_id":f"eq.{pid}","agency_id":f"eq.{a['agency_id']}","limit":"1"}) or []
        if not found: raise HTTPException(404,f"Payment {pid} not found in this agency")
        rows.append(found[0])
    sid="ast_"+secrets.token_urlsafe(10); ts=now(); row={"settlement_id":sid,"agency_id":a["agency_id"],**p.model_dump(),"currency":p.currency.upper(),"net_settlement":round(p.settled_amount-p.fee_amount,2),"created_by_owner_id":a["owner_id"],"created_at":ts}
    await get_backend().insert("logistics_agency_payment_settlements",row)
    for pay in rows: await get_backend().patch("logistics_agency_payments",{"status":"SETTLED","settlement_id":sid,"updated_at":ts},params={"payment_id":f"eq.{pay['payment_id']}","agency_id":f"eq.{a['agency_id']}"})
    return {"settlement":row,"payments_reconciled":len(rows)}
