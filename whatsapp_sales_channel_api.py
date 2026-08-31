from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status
from whatsapp_sales_brain import analyze_sales_conversation, frontier_status
from whatsapp_relationship_memory_api import _merge_memory

app = FastAPI(title="SAHJONY WhatsApp Agentic Sales Channel", version="2.1.0", docs_url=None, redoc_url=None)

Stage = Literal["NEW","ENGAGED","QUALIFYING","QUALIFIED","RFQ_READY","SOURCING","QUOTED","NEGOTIATING","WON","LOST","OPTED_OUT"]
BINDING_STAGES = {"QUOTED", "NEGOTIATING", "WON"}


def _now() -> str: return datetime.now(timezone.utc).isoformat()

def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(status_code=401, detail="Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()): raise HTTPException(status_code=403, detail="Invalid owner credential")

class StageUpdate(BaseModel):
    stage: Stage
    next_action: str | None = Field(default=None,max_length=1000)
    notes: str | None = Field(default=None,max_length=4000)
    priority: Literal["low","normal","high","urgent"]="high"
    evidence_verified: bool=False

class QualificationUpdate(BaseModel):
    product_need:str=Field(min_length=2,max_length=1000)
    specifications:str|None=Field(default=None,max_length=4000)
    quantity:str|None=Field(default=None,max_length=500)
    container_type:str|None=Field(default=None,max_length=200)
    origin:str|None=Field(default=None,max_length=500)
    destination:str|None=Field(default=None,max_length=500)
    target_budget:str|None=Field(default=None,max_length=500)
    target_delivery_date:str|None=Field(default=None,max_length=200)
    preferred_incoterm:str|None=Field(default=None,max_length=100)
    notes:str|None=Field(default=None,max_length=4000)

class BrainRun(BaseModel):
    complexity:Literal["normal","complex","critical","negotiation","rfq","sourcing","compliance","quote"]="normal"
    auto_advance_non_binding:bool=True

async def _stage_events(lead_id:str|None=None)->list[dict[str,Any]]:
    params={"source_type":"eq.whatsapp_sales","order":"created_at.desc","limit":"1000"}
    if lead_id:params["lead_id"]=f"eq.{lead_id}"
    try:return await get_backend().select("business_events",params=params) or []
    except Exception:return []

async def _all_events(lead_id:str)->list[dict[str,Any]]:
    try:return await get_backend().select("business_events",params={"lead_id":f"eq.{lead_id}","order":"created_at.asc","limit":"2000"}) or []
    except Exception:return []

def _latest_stage(events):
    for event in events:
        payload=event.get("payload") or {}
        if payload.get("stage"):return str(payload["stage"])
    return "NEW"

async def _record_sales_event(*,lead_id,title,summary,stage=None,payload=None,priority="high",action_required=True,action_label="Advance WhatsApp sales opportunity",actor_role="owner",actor_id="owner"):
    row={"event_id":f"evt_{secrets.token_urlsafe(16)}","event_type":"sales_stage" if stage else "sales_note","source_type":"whatsapp_sales","source_id":lead_id,"trade_case_id":None,"customer_id":None,"lead_id":lead_id,"actor_role":actor_role,"actor_id":actor_id,"visibility":"internal","title":title,"summary":summary[:4000],"action_required":action_required,"action_label":action_label,"priority":priority,"event_status":"open" if action_required else "closed","payload":{**(payload or {}),**({"stage":stage} if stage else {})},"created_at":_now()}
    await get_backend().insert("business_events",row);return row

def _transcript(messages):
    parts=[]
    for m in messages[-60:]:
        role="customer" if m.get("direction")=="inbound" else "sahjony"
        body=str(m.get("text") or m.get("body") or m.get("content") or "").strip()
        if body:parts.append(f"{role}: {body[:1600]}")
    return "\n".join(parts)

async def _lead_bundle(lead_id):
    backend=get_backend();rows=await backend.select("whatsapp_leads",params={"lead_id":f"eq.{lead_id}","limit":"1"}) or []
    if not rows:raise HTTPException(status_code=404,detail="WhatsApp lead not found")
    lead=rows[0];phone=str(lead.get("phone") or "")
    messages=await backend.select("whatsapp_messages",params={"phone":f"eq.{phone}","order":"created_at.asc","limit":"1000"}) or []
    events=await _stage_events(lead_id);return lead,messages,events

@app.get("/whatsapp/sales/health")
async def sales_health():
    persistence=persistent_backend_status();backend=get_backend();counts={"leads":0,"messages":0,"sales_events":0,"outbound":0}
    if persistence["configured"]:
        for key,table in (("leads","whatsapp_leads"),("messages","whatsapp_messages"),("outbound","outbound_notifications")):
            try:counts[key]=len(await backend.select(table,params={"limit":"5000"}) or [])
            except Exception:pass
        counts["sales_events"]=len(await _stage_events())
    return {"status":"ok" if persistence["configured"] else "configuration_required","service":"whatsapp-agentic-sales-channel","version":"2.1.0","pipeline_enabled":True,"lead_capture":True,"conversation_history":True,"qualification":True,"rfq_readiness":True,"owner_stage_control":True,"outbound_traceability":True,"agentic_sales_brain":True,"next_best_action_engine":True,"autonomous_non_binding_progression":True,"autonomous_binding_quotes":False,"verified_quote_gate":True,"sofia_human_conversation_policy":True,"relationship_memory_injection":True,"frontier":frontier_status(),"counts":counts,"persistence":persistence["provider"]}

@app.get("/whatsapp/sales/inbox")
async def sales_inbox(limit:int=Query(100,ge=1,le=500),authorization:str|None=Header(None,alias="Authorization")):
    _owner(authorization);backend=get_backend();leads=await backend.select("whatsapp_leads",params={"order":"updated_at.desc","limit":str(limit)}) or [];messages=await backend.select("whatsapp_messages",params={"order":"created_at.desc","limit":str(min(limit*10,2000))}) or [];sales_events=await _stage_events();events_by_lead={};msg_by_phone={}
    for event in sales_events:
        lid=str(event.get("lead_id") or "")
        if lid:events_by_lead.setdefault(lid,[]).append(event)
    for msg in messages:
        phone=str(msg.get("phone") or "")
        if phone:msg_by_phone.setdefault(phone,[]).append(msg)
    items=[]
    for lead in leads:
        lid=str(lead.get("lead_id") or "");phone=str(lead.get("phone") or "");ev=events_by_lead.get(lid,[]);conversation=msg_by_phone.get(phone,[]);stage=_latest_stage(ev);brain_event=next((x for x in ev if (x.get("payload") or {}).get("brain")),None);brain=(brain_event.get("payload") or {}).get("brain") if brain_event else None
        items.append({"lead":lead,"stage":stage,"opportunity_score":(brain or {}).get("opportunity_score"),"conversation":{"inbound":sum(1 for m in conversation if m.get("direction")=="inbound"),"outbound":sum(1 for m in conversation if m.get("direction")=="outbound"),"recent":conversation[:12]},"latest_sales_event":ev[0] if ev else None,"next_action":((ev[0].get("payload") or {}).get("next_action") if ev else None) or (brain or {}).get("next_best_action") or "Run frontier sales brain","attention_required":stage not in {"WON","LOST","OPTED_OUT"}})
    return {"status":"ok","count":len(items),"items":items}

@app.get("/whatsapp/sales/leads/{lead_id}")
async def sales_lead(lead_id:str,authorization:str|None=Header(None,alias="Authorization")):
    _owner(authorization);lead,messages,events=await _lead_bundle(lead_id);brain_event=next((x for x in events if (x.get("payload") or {}).get("brain")),None);memory=_merge_memory(lead,await _all_events(lead_id))
    return {"lead":lead,"stage":_latest_stage(events),"messages":messages,"sales_events":events,"latest_brain":((brain_event.get("payload") or {}).get("brain") if brain_event else None),"relationship_memory":memory}

@app.post("/whatsapp/sales/leads/{lead_id}/brain")
async def run_sales_brain(lead_id:str,p:BrainRun,authorization:str|None=Header(None,alias="Authorization")):
    _owner(authorization);lead,messages,events=await _lead_bundle(lead_id);current=_latest_stage(events);memory=_merge_memory(lead,await _all_events(lead_id))
    brain=await analyze_sales_conversation(transcript=_transcript(messages),current_stage=current,complexity=p.complexity,relationship_memory=memory)
    recommended=str(brain.get("recommended_stage") or current).upper()
    if recommended in BINDING_STAGES:recommended="RFQ_READY"
    stage=current
    if p.auto_advance_non_binding and recommended not in BINDING_STAGES and recommended!=current:stage=recommended
    event=await _record_sales_event(lead_id=lead_id,title=f"Sofia frontier sales brain · {brain.get('model') or brain.get('engine')}",summary=str(brain.get("next_best_action") or "Sales brain analysis completed"),stage=stage if stage!=current else None,payload={"brain":brain,"next_action":brain.get("next_best_action"),"recommended_stage":recommended,"previous_stage":current,"memory_applied":True},priority="urgent" if int(brain.get("opportunity_score") or 0)>=80 else "high",action_required=stage not in {"WON","LOST","OPTED_OUT"},action_label=str(brain.get("next_best_action") or "Advance opportunity"),actor_role="ai_agent",actor_id="sofia-reyes")
    return {"status":"analyzed","lead_id":lead_id,"stage":stage,"brain":brain,"relationship_memory":memory,"event":event}

@app.post("/whatsapp/sales/leads/{lead_id}/stage")
async def set_sales_stage(lead_id:str,p:StageUpdate,authorization:str|None=Header(None,alias="Authorization")):
    _owner(authorization)
    if p.stage in BINDING_STAGES and not p.evidence_verified:raise HTTPException(status_code=409,detail="Verified commercial evidence is required before QUOTED, NEGOTIATING or WON")
    rows=await get_backend().select("whatsapp_leads",params={"lead_id":f"eq.{lead_id}","limit":"1"}) or []
    if not rows:raise HTTPException(status_code=404,detail="WhatsApp lead not found")
    terminal=p.stage in {"WON","LOST","OPTED_OUT"};event=await _record_sales_event(lead_id=lead_id,title=f"WhatsApp sales stage → {p.stage}",summary=p.notes or p.next_action or f"Lead advanced to {p.stage}",stage=p.stage,payload={"next_action":p.next_action,"notes":p.notes,"evidence_verified":p.evidence_verified},priority=p.priority,action_required=not terminal,action_label=p.next_action or ("Sales cycle closed" if terminal else "Advance WhatsApp sales opportunity"));return {"status":"updated","lead_id":lead_id,"stage":p.stage,"event":event}

@app.post("/whatsapp/sales/leads/{lead_id}/qualify")
async def qualify_sales_lead(lead_id:str,p:QualificationUpdate,authorization:str|None=Header(None,alias="Authorization")):
    _owner(authorization);rows=await get_backend().select("whatsapp_leads",params={"lead_id":f"eq.{lead_id}","limit":"1"}) or []
    if not rows:raise HTTPException(status_code=404,detail="WhatsApp lead not found")
    payload=p.model_dump();event=await _record_sales_event(lead_id=lead_id,title="WhatsApp trade requirement qualified",summary=f"Qualified demand: {p.product_need}",stage="QUALIFIED",payload={**payload,"next_action":"Run frontier sales brain, validate suppliers, freight, compliance and landed cost before formal quote"},priority="high",action_required=True,action_label="Prepare RFQ and sourcing package");return {"status":"qualified","lead_id":lead_id,"stage":"QUALIFIED","qualification":payload,"event":event}

@app.get("/whatsapp/sales/pipeline")
async def sales_pipeline(authorization:str|None=Header(None,alias="Authorization")):
    _owner(authorization);backend=get_backend();leads=await backend.select("whatsapp_leads",params={"order":"updated_at.desc","limit":"5000"}) or [];events=await _stage_events();latest={}
    for event in events:
        lid=str(event.get("lead_id") or "");payload=event.get("payload") or {}
        if lid and lid not in latest and payload.get("stage"):latest[lid]=str(payload["stage"])
    stages={stage:0 for stage in ["NEW","ENGAGED","QUALIFYING","QUALIFIED","RFQ_READY","SOURCING","QUOTED","NEGOTIATING","WON","LOST","OPTED_OUT"]}
    for lead in leads:
        stage=latest.get(str(lead.get("lead_id") or ""),"NEW");stages[stage]=stages.get(stage,0)+1
    return {"status":"ok","total_leads":len(leads),"active_pipeline":sum(v for k,v in stages.items() if k not in {"WON","LOST","OPTED_OUT"}),"stages":stages,"frontier":frontier_status(),"recommended_next_step":"Run Sofia on NEW/ENGAGED leads, then work QUALIFIED and RFQ_READY opportunities first."}
