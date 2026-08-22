from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_customer_token, verify_owner_token
from insforge_backend import InsForgeConfigurationError, get_backend

app = FastAPI(title="SAHJONY Global Trade Documents", version="1.1.0", docs_url=None, redoc_url=None)

Role = Literal["owner","employee","customer"]
Status = Literal["requested","customer_submitted","employee_review","correction_requested","owner_review","approved","released","rejected","archived"]
DocType = Literal["proforma_invoice","commercial_invoice","packing_list","purchase_order","sales_contract","bill_of_lading","air_waybill","certificate_of_origin","customs_entry","export_declaration","insurance_certificate","inspection_certificate","phytosanitary_certificate","fumigation_certificate","import_permit","export_license","compliance_evidence","hts_classification","payment_evidence","other"]

class DocumentCreate(BaseModel):
    trade_case_id: str = Field(min_length=1,max_length=160)
    customer_id: str | None = Field(default=None,max_length=160)
    document_type: DocType
    title: str = Field(min_length=2,max_length=240)
    storage_object_key: str | None = Field(default=None,max_length=500)
    version: int = Field(default=1,ge=1)
    customer_visible: bool = False

class MoveRequest(BaseModel):
    to_status: Status
    note: str | None = Field(default=None,max_length=2000)
    customer_visible: bool | None = None

TRANSITIONS = {
    "requested":{"customer_submitted","archived"},
    "customer_submitted":{"employee_review","correction_requested","archived"},
    "employee_review":{"correction_requested","owner_review","rejected"},
    "correction_requested":{"customer_submitted","employee_review","archived"},
    "owner_review":{"approved","rejected","correction_requested"},
    "approved":{"released","archived"},
    "released":{"archived"},
    "rejected":{"correction_requested","archived"},
    "archived":set(),
}
ROLE_MOVES = {
    "customer":{"customer_submitted"},
    "employee":{"employee_review","correction_requested","owner_review","rejected","archived"},
    "owner":{"requested","correction_requested","owner_review","approved","released","rejected","archived"},
}
ACTION_STATUSES={"requested","correction_requested","owner_review"}

def now(): return datetime.now(timezone.utc).isoformat()

def employee_token():
    token=os.getenv("EMPLOYEE_TOKEN")
    if not token: raise HTTPException(503,"Employee document workflow is not configured")
    return token

def identity(role, authorization, employee_id):
    if role not in {"owner","employee","customer"}: raise HTTPException(400,"Invalid X-Role")
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Missing Authorization")
    token=authorization.removeprefix("Bearer ").strip()
    if role=="owner":
        if not verify_owner_token(token): raise HTTPException(403,"Invalid owner credential")
        return {"role":"owner","id":"owner"}
    if role=="employee":
        if not secrets.compare_digest(token, employee_token()): raise HTTPException(403,"Invalid employee credential")
        return {"role":"employee","id":(employee_id or "staff")[:160]}
    c=verify_customer_token(token)
    if not c: raise HTTPException(403,"Invalid customer credential")
    return {"role":"customer","id":str(c["participant_id"])}

async def audit(document_id, actor, from_status, to_status, note):
    event={"event_id":f"dme_{secrets.token_urlsafe(16)}","document_id":document_id,"actor_role":actor["role"],"actor_id":actor["id"],"from_status":from_status,"to_status":to_status,"note":note,"created_at":now()}
    await get_backend().insert("document_movements",event)
    return event

async def publish_timeline(doc, actor, from_status, to_status, note):
    customer_visible=bool(doc.get("customer_visible")) or actor["role"]=="customer" or to_status in {"requested","correction_requested","released"}
    visibility="customer" if customer_visible and doc.get("customer_id") else "internal"
    if to_status=="owner_review": visibility="internal"
    if to_status=="approved" and not doc.get("customer_visible"): visibility="internal"
    action=to_status in ACTION_STATUSES
    labels={"requested":"Document requested","correction_requested":"Correction required","owner_review":"Owner review required"}
    row={
        "event_id":f"evt_{secrets.token_urlsafe(16)}","event_type":"document","source_type":"trade_document",
        "source_id":doc["document_id"],"trade_case_id":doc.get("trade_case_id"),"customer_id":doc.get("customer_id"),
        "actor_role":actor["role"],"actor_id":actor["id"],"visibility":visibility,
        "title":f"{doc.get('title','Document')} · {to_status.replace('_',' ')}",
        "summary":note or f"Document moved from {from_status or 'created'} to {to_status}.",
        "action_required":action,"action_label":labels.get(to_status),
        "priority":"high" if to_status in {"correction_requested","rejected"} else "normal",
        "event_status":"open","payload":{"document_type":doc.get("document_type"),"version":doc.get("version"),"from_status":from_status,"to_status":to_status},
        "created_at":now(),"updated_at":now(),
    }
    await get_backend().insert("business_events",row)
    if visibility=="customer" and doc.get("customer_id"):
        await get_backend().insert("outbound_notifications",{
            "notification_id":f"ntf_{secrets.token_urlsafe(16)}","event_id":row["event_id"],"recipient_role":"customer",
            "recipient_id":doc["customer_id"],"channel":"portal","destination":None,"subject":row["title"],"body":row["summary"],
            "delivery_status":"delivered","provider":"native_portal","provider_message_id":None,"attempts":1,"last_error":None,
            "created_at":now(),"updated_at":now(),
        })
    return row

@app.get("/documents/health")
async def health():
    return {"status":"ok","service":"document-movement","version":"1.1.0","configured":bool(os.getenv("INSFORGE_BASE_URL") and os.getenv("INSFORGE_API_KEY")),"storage_enabled":os.getenv("INSFORGE_STORAGE_ENABLED","false").lower()=="true","timeline_integration":True}

@app.post("/documents")
async def create_document(payload: DocumentCreate, x_role: str|None=Header(None,alias="X-Role"), authorization: str|None=Header(None,alias="Authorization"), x_employee_id: str|None=Header(None,alias="X-Employee-Id")):
    actor=identity(x_role,authorization,x_employee_id)
    customer_id=actor["id"] if actor["role"]=="customer" else payload.customer_id
    if actor["role"]=="customer" and not customer_id: raise HTTPException(403,"Customer scope required")
    status="customer_submitted" if actor["role"]=="customer" else "requested"
    doc_id=f"doc_{secrets.token_urlsafe(16)}"; ts=now()
    row={"document_id":doc_id,"trade_case_id":payload.trade_case_id,"customer_id":customer_id,"document_type":payload.document_type,"title":payload.title,"storage_object_key":payload.storage_object_key,"version":payload.version,"status":status,"customer_visible":payload.customer_visible if actor["role"]!="customer" else True,"created_by_role":actor["role"],"created_by_id":actor["id"],"created_at":ts,"updated_at":ts}
    try:
        result=await get_backend().insert("trade_documents",row)
        movement=await audit(doc_id,actor,None,status,"Document registered")
        timeline=await publish_timeline(row,actor,None,status,"Document registered")
    except InsForgeConfigurationError as exc: raise HTTPException(503,str(exc)) from exc
    except Exception as exc: raise HTTPException(503,f"Document persistence unavailable: {type(exc).__name__}") from exc
    return {"document":row,"movement":movement,"timeline_event":timeline,"persistence":result}

@app.get("/documents")
async def list_documents(trade_case_id: str|None=Query(default=None,max_length=160), customer_id: str|None=Query(default=None,max_length=160), x_role: str|None=Header(None,alias="X-Role"), authorization: str|None=Header(None,alias="Authorization"), x_employee_id: str|None=Header(None,alias="X-Employee-Id")):
    actor=identity(x_role,authorization,x_employee_id); params={"order":"updated_at.desc","limit":"250"}
    if trade_case_id: params["trade_case_id"]=f"eq.{trade_case_id}"
    if actor["role"]=="customer": params["customer_id"]=f"eq.{actor['id']}"; params["customer_visible"]="eq.true"
    elif customer_id: params["customer_id"]=f"eq.{customer_id}"
    try: rows=await get_backend().select("trade_documents",params=params)
    except Exception as exc: raise HTTPException(503,f"Document persistence unavailable: {type(exc).__name__}") from exc
    return {"documents":rows or [],"actor":actor}

@app.post("/documents/{document_id}/move")
async def move_document(document_id: str, payload: MoveRequest, x_role: str|None=Header(None,alias="X-Role"), authorization: str|None=Header(None,alias="Authorization"), x_employee_id: str|None=Header(None,alias="X-Employee-Id")):
    actor=identity(x_role,authorization,x_employee_id)
    if payload.to_status not in ROLE_MOVES[actor["role"]]: raise HTTPException(403,"Role cannot perform this document movement")
    rows=await get_backend().select("trade_documents",params={"document_id":f"eq.{document_id}","limit":"1"})
    if not rows: raise HTTPException(404,"Document not found")
    doc=rows[0]
    if actor["role"]=="customer" and doc.get("customer_id")!=actor["id"]: raise HTTPException(403,"Customer scope mismatch")
    current=doc.get("status")
    if payload.to_status not in TRANSITIONS.get(current,set()): raise HTTPException(409,f"Invalid transition {current} -> {payload.to_status}")
    values={"status":payload.to_status,"updated_at":now()}
    if payload.customer_visible is not None:
        if actor["role"]=="customer": raise HTTPException(403,"Customers cannot change visibility policy")
        values["customer_visible"]=payload.customer_visible; doc["customer_visible"]=payload.customer_visible
    result=await get_backend().patch("trade_documents",values,params={"document_id":f"eq.{document_id}"})
    event=await audit(document_id,actor,current,payload.to_status,payload.note)
    timeline=await publish_timeline(doc,actor,current,payload.to_status,payload.note)
    return {"document_id":document_id,"from_status":current,"to_status":payload.to_status,"movement":event,"timeline_event":timeline,"persistence":result}

@app.get("/documents/{document_id}/movements")
async def movements(document_id: str, x_role: str|None=Header(None,alias="X-Role"), authorization: str|None=Header(None,alias="Authorization"), x_employee_id: str|None=Header(None,alias="X-Employee-Id")):
    actor=identity(x_role,authorization,x_employee_id)
    docs=await get_backend().select("trade_documents",params={"document_id":f"eq.{document_id}","limit":"1"})
    if not docs: raise HTTPException(404,"Document not found")
    if actor["role"]=="customer" and (docs[0].get("customer_id")!=actor["id"] or not docs[0].get("customer_visible")): raise HTTPException(403,"Customer scope mismatch")
    rows=await get_backend().select("document_movements",params={"document_id":f"eq.{document_id}","order":"created_at.asc","limit":"250"})
    return {"movements":rows or []}
