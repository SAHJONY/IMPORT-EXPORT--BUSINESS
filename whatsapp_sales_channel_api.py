from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY WhatsApp Sales Channel", version="1.0.0", docs_url=None, redoc_url=None)

Stage = Literal["NEW","ENGAGED","QUALIFYING","QUALIFIED","RFQ_READY","SOURCING","QUOTED","NEGOTIATING","WON","LOST","OPTED_OUT"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


class StageUpdate(BaseModel):
    stage: Stage
    next_action: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)
    priority: Literal["low","normal","high","urgent"] = "high"


class QualificationUpdate(BaseModel):
    product_need: str = Field(min_length=2, max_length=1000)
    specifications: str | None = Field(default=None, max_length=4000)
    quantity: str | None = Field(default=None, max_length=500)
    container_type: str | None = Field(default=None, max_length=200)
    origin: str | None = Field(default=None, max_length=500)
    destination: str | None = Field(default=None, max_length=500)
    target_budget: str | None = Field(default=None, max_length=500)
    target_delivery_date: str | None = Field(default=None, max_length=200)
    preferred_incoterm: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=4000)


async def _stage_events(lead_id: str | None = None) -> list[dict[str, Any]]:
    params: dict[str, str] = {"source_type":"eq.whatsapp_sales","order":"created_at.desc","limit":"1000"}
    if lead_id:
        params["lead_id"] = f"eq.{lead_id}"
    try:
        return await get_backend().select("business_events", params=params) or []
    except Exception:
        return []


def _latest_stage(events: list[dict[str, Any]]) -> str:
    for event in events:
        payload = event.get("payload") or {}
        if payload.get("stage"):
            return str(payload["stage"])
    return "NEW"


async def _record_sales_event(*, lead_id: str, title: str, summary: str, stage: str | None = None, payload: dict[str, Any] | None = None, priority: str = "high", action_required: bool = True, action_label: str = "Advance WhatsApp sales opportunity") -> dict[str, Any]:
    row = {
        "event_id": f"evt_{secrets.token_urlsafe(16)}",
        "event_type": "sales_stage" if stage else "sales_note",
        "source_type": "whatsapp_sales",
        "source_id": lead_id,
        "trade_case_id": None,
        "customer_id": None,
        "lead_id": lead_id,
        "actor_role": "owner",
        "actor_id": "owner",
        "visibility": "internal",
        "title": title,
        "summary": summary[:4000],
        "action_required": action_required,
        "action_label": action_label,
        "priority": priority,
        "event_status": "open" if action_required else "closed",
        "payload": {**(payload or {}), **({"stage": stage} if stage else {})},
        "created_at": _now(),
    }
    await get_backend().insert("business_events", row)
    return row


@app.get("/whatsapp/sales/health")
async def sales_health():
    persistence = persistent_backend_status()
    backend = get_backend()
    counts = {"leads":0,"messages":0,"sales_events":0,"outbound":0}
    if persistence["configured"]:
        for key, table in (("leads","whatsapp_leads"),("messages","whatsapp_messages"),("outbound","outbound_notifications")):
            try:
                counts[key] = len(await backend.select(table, params={"limit":"5000"}) or [])
            except Exception:
                pass
        counts["sales_events"] = len(await _stage_events())
    return {
        "status":"ok" if persistence["configured"] else "configuration_required",
        "service":"whatsapp-sales-channel",
        "version":"1.0.0",
        "pipeline_enabled":True,
        "lead_capture":True,
        "conversation_history":True,
        "qualification":True,
        "rfq_readiness":True,
        "owner_stage_control":True,
        "outbound_traceability":True,
        "autonomous_binding_quotes":False,
        "counts":counts,
        "persistence":persistence["provider"],
    }


@app.get("/whatsapp/sales/inbox")
async def sales_inbox(limit: int = Query(100, ge=1, le=500), authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    backend = get_backend()
    leads = await backend.select("whatsapp_leads", params={"order":"updated_at.desc","limit":str(limit)}) or []
    messages = await backend.select("whatsapp_messages", params={"order":"created_at.desc","limit":str(min(limit*10, 2000))}) or []
    sales_events = await _stage_events()
    events_by_lead: dict[str, list[dict[str, Any]]] = {}
    for event in sales_events:
        lid = str(event.get("lead_id") or "")
        if lid:
            events_by_lead.setdefault(lid, []).append(event)
    msg_by_phone: dict[str, list[dict[str, Any]]] = {}
    for msg in messages:
        phone = str(msg.get("phone") or "")
        if phone:
            msg_by_phone.setdefault(phone, []).append(msg)
    items=[]
    for lead in leads:
        lid=str(lead.get("lead_id") or "")
        phone=str(lead.get("phone") or "")
        ev=events_by_lead.get(lid,[])
        conversation=msg_by_phone.get(phone,[])
        inbound=sum(1 for m in conversation if m.get("direction")=="inbound")
        outbound=sum(1 for m in conversation if m.get("direction")=="outbound")
        stage=_latest_stage(ev)
        items.append({
            "lead":lead,
            "stage":stage,
            "conversation":{"inbound":inbound,"outbound":outbound,"recent":conversation[:12]},
            "latest_sales_event":ev[0] if ev else None,
            "next_action":((ev[0].get("payload") or {}).get("next_action") if ev else None) or "Qualify trade requirement",
            "attention_required":stage not in {"WON","LOST","OPTED_OUT"},
        })
    return {"status":"ok","count":len(items),"items":items}


@app.get("/whatsapp/sales/leads/{lead_id}")
async def sales_lead(lead_id: str, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    backend=get_backend()
    rows=await backend.select("whatsapp_leads",params={"lead_id":f"eq.{lead_id}","limit":"1"}) or []
    if not rows:
        raise HTTPException(status_code=404,detail="WhatsApp lead not found")
    lead=rows[0]
    phone=str(lead.get("phone") or "")
    messages=await backend.select("whatsapp_messages",params={"phone":f"eq.{phone}","order":"created_at.asc","limit":"1000"}) or []
    events=await _stage_events(lead_id)
    try:
        outbound=await backend.select("outbound_notifications",params={"channel":"eq.whatsapp","destination":f"eq.{phone}","order":"created_at.desc","limit":"250"}) or []
    except Exception:
        outbound=[]
    return {"lead":lead,"stage":_latest_stage(events),"messages":messages,"sales_events":events,"outbound":outbound}


@app.post("/whatsapp/sales/leads/{lead_id}/stage")
async def set_sales_stage(lead_id: str, p: StageUpdate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    backend=get_backend()
    rows=await backend.select("whatsapp_leads",params={"lead_id":f"eq.{lead_id}","limit":"1"}) or []
    if not rows:
        raise HTTPException(status_code=404,detail="WhatsApp lead not found")
    terminal=p.stage in {"WON","LOST","OPTED_OUT"}
    event=await _record_sales_event(
        lead_id=lead_id,
        title=f"WhatsApp sales stage → {p.stage}",
        summary=p.notes or p.next_action or f"Lead advanced to {p.stage}",
        stage=p.stage,
        payload={"next_action":p.next_action,"notes":p.notes},
        priority=p.priority,
        action_required=not terminal,
        action_label=p.next_action or ("Sales cycle closed" if terminal else "Advance WhatsApp sales opportunity"),
    )
    return {"status":"updated","lead_id":lead_id,"stage":p.stage,"event":event}


@app.post("/whatsapp/sales/leads/{lead_id}/qualify")
async def qualify_sales_lead(lead_id: str, p: QualificationUpdate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    backend=get_backend()
    rows=await backend.select("whatsapp_leads",params={"lead_id":f"eq.{lead_id}","limit":"1"}) or []
    if not rows:
        raise HTTPException(status_code=404,detail="WhatsApp lead not found")
    payload=p.model_dump()
    event=await _record_sales_event(
        lead_id=lead_id,
        title="WhatsApp trade requirement qualified",
        summary=f"Qualified demand: {p.product_need}",
        stage="QUALIFIED",
        payload={**payload,"next_action":"Validate suppliers, freight, compliance and landed cost before formal quote"},
        priority="high",
        action_required=True,
        action_label="Prepare RFQ and sourcing package",
    )
    return {"status":"qualified","lead_id":lead_id,"stage":"QUALIFIED","qualification":payload,"event":event}


@app.get("/whatsapp/sales/pipeline")
async def sales_pipeline(authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    backend=get_backend()
    leads=await backend.select("whatsapp_leads",params={"order":"updated_at.desc","limit":"5000"}) or []
    events=await _stage_events()
    latest: dict[str,str]={}
    for event in events:
        lid=str(event.get("lead_id") or "")
        payload=event.get("payload") or {}
        if lid and lid not in latest and payload.get("stage"):
            latest[lid]=str(payload["stage"])
    stages={stage:0 for stage in ["NEW","ENGAGED","QUALIFYING","QUALIFIED","RFQ_READY","SOURCING","QUOTED","NEGOTIATING","WON","LOST","OPTED_OUT"]}
    for lead in leads:
        stage=latest.get(str(lead.get("lead_id") or ""),"NEW")
        stages[stage]=stages.get(stage,0)+1
    active=sum(v for k,v in stages.items() if k not in {"WON","LOST","OPTED_OUT"})
    return {"status":"ok","total_leads":len(leads),"active_pipeline":active,"stages":stages,"recommended_next_step":"Work QUALIFIED and RFQ_READY leads first, then advance SOURCING and QUOTED opportunities."}
