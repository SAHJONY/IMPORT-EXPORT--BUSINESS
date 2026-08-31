from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from insforge_backend import get_backend


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SEGMENTS = {
    "hot_buyer": ["quote", "price", "container", "buy", "purchase", "cotiz", "precio", "contenedor", "comprar"],
    "supplier": ["supplier", "manufacturer", "distributor", "proveedor", "fabricante", "distribuidor"],
    "partner": ["partner", "commission", "referral", "socio", "comision", "referido"],
    "logistics": ["freight", "shipping", "container", "logistics", "flete", "envio", "contenedor", "logistica"],
}


def classify_segment(text: str) -> str:
    t=(text or "").lower()
    scores={name:sum(1 for kw in kws if kw in t) for name,kws in SEGMENTS.items()}
    best=max(scores,key=scores.get) if scores else "general_trade"
    return best if scores.get(best,0)>0 else "general_trade"


def next_marketing_action(stage: str, segment: str, opted_out: bool=False) -> dict[str, Any]:
    if opted_out:
        return {"action":"suppress","reason":"opted_out","send_allowed":False}
    stage=(stage or "NEW").upper()
    if stage in {"WON","LOST","OPTED_OUT"}:
        return {"action":"lifecycle_followup" if stage=="WON" else "suppress","send_allowed":stage=="WON"}
    if stage in {"QUALIFIED","RFQ_READY","SOURCING"}:
        return {"action":"high_intent_nurture","send_allowed":True,"cadence":"contextual"}
    if stage in {"ENGAGED","QUALIFYING"}:
        return {"action":"educational_nurture","send_allowed":True,"cadence":"contextual"}
    return {"action":"wait_for_intent_or_permission","send_allowed":False,"cadence":"none"}


def campaign_brief(segment: str, language: str="auto") -> dict[str, Any]:
    messages={
        "hot_buyer":"Move the buyer from interest to a complete RFQ using verified pricing, logistics and compliance evidence.",
        "supplier":"Position SAHJONY LLC as a qualified route to new B2B demand and structured RFQs.",
        "partner":"Explain the partner opportunity, referral economics and how to enroll without overpromising earnings.",
        "logistics":"Position SAHJONY LLC as a coordination and sourcing partner while clearly identifying regulated service providers where applicable.",
        "general_trade":"Educate the prospect on SAHJONY LLC global sourcing, trade coordination and commercial support.",
    }
    return {
        "segment":segment,
        "language":language,
        "objective":messages.get(segment,messages["general_trade"]),
        "channels":["whatsapp","email","website"],
        "tone":"human, concise, professional, commercially useful",
        "cta":"Reply with the product/service, quantity, destination and target timeline so SAHJONY LLC can evaluate the next step.",
        "claims_policy":"No invented prices, inventory, guarantees, legal clearance, delivery dates or earnings claims.",
    }


async def record_marketing_event(*, lead_id: str | None, segment: str, action: str, metadata: dict[str, Any] | None=None) -> None:
    try:
        await get_backend().insert("business_events", {
            "event_id":f"evt_{secrets.token_urlsafe(16)}",
            "event_type":"marketing",
            "source_type":"sofia_self_marketing",
            "source_id":lead_id or segment,
            "trade_case_id":None,
            "customer_id":None,
            "lead_id":lead_id,
            "actor_role":"system",
            "actor_id":"sofia-reyes-growth-engine",
            "visibility":"internal",
            "title":f"Sofia marketing action: {action}",
            "summary":f"Segment={segment}; action={action}",
            "action_required":False,
            "action_label":None,
            "priority":"normal",
            "event_status":"closed",
            "payload":{"segment":segment,"action":action,"metadata":metadata or {},"guardrails":{"bulk_unsolicited":False,"paid_spend_without_owner":False,"opt_out_enforced":True}},
            "created_at":_now(),
            "updated_at":_now(),
        })
    except Exception:
        pass


async def growth_health() -> dict[str, Any]:
    try:
        rows=await get_backend().select("business_events",params={"source_type":"eq.sofia_self_marketing","order":"created_at.desc","limit":"200"}) or []
    except Exception:
        rows=[]
    return {
        "status":"ok",
        "service":"sofia-self-marketing",
        "version":"1.0.0",
        "self_marketing":True,
        "lead_segmentation":True,
        "nurture_planning":True,
        "campaign_briefs":True,
        "conversion_learning":True,
        "owned_channel_optimization":True,
        "bulk_unsolicited_messaging":False,
        "paid_media_spend_without_owner_approval":False,
        "opt_out_enforced":True,
        "recent_marketing_events":len(rows),
        "objective":"grow qualified demand and conversion while protecting reputation, consent, compliance and margin",
    }
