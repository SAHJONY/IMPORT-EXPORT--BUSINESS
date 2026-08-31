from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY WhatsApp RFQ Execution Engine", version="1.0.0", docs_url=None, redoc_url=None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


class RFQExecutionRequest(BaseModel):
    product: str = Field(min_length=2, max_length=500)
    specifications: str = Field(min_length=2, max_length=4000)
    quantity_per_shipment: str = Field(min_length=1, max_length=500)
    shipment_count: int = Field(default=1, ge=1, le=120)
    container_type: str | None = Field(default=None, max_length=200)
    packaging: str | None = Field(default=None, max_length=500)
    acceptable_origins: list[str] = Field(default_factory=list, max_length=20)
    destination: str = Field(min_length=2, max_length=500)
    incoterm: str | None = Field(default=None, max_length=100)
    target_budget: str | None = Field(default=None, max_length=500)
    payment_terms_target: str | None = Field(default=None, max_length=500)
    first_delivery_target: str | None = Field(default=None, max_length=300)
    importer_legal_name: str | None = Field(default=None, max_length=500)
    importer_contact: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)


async def _lead(lead_id: str) -> dict[str, Any]:
    rows = await get_backend().select("whatsapp_leads", params={"lead_id": f"eq.{lead_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(status_code=404, detail="WhatsApp lead not found")
    return rows[0]


async def _event(*, lead_id: str, event_type: str, title: str, summary: str, payload: dict[str, Any], priority: str = "high", action_required: bool = True, action_label: str | None = None) -> dict[str, Any]:
    ts = _now()
    row = {
        "event_id": f"evt_{secrets.token_urlsafe(16)}",
        "event_type": event_type,
        "source_type": "whatsapp_rfq_execution",
        "source_id": lead_id,
        "trade_case_id": None,
        "customer_id": None,
        "lead_id": lead_id,
        "actor_role": "ai_agent",
        "actor_id": "sofia-reyes-rfq-executor",
        "visibility": "internal",
        "title": title[:240],
        "summary": summary[:4000],
        "action_required": action_required,
        "action_label": action_label,
        "priority": priority,
        "event_status": "open" if action_required else "completed",
        "payload": payload,
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("business_events", row)
    check = await get_backend().select("business_events", params={"event_id": f"eq.{row['event_id']}", "limit": "1"}) or []
    if not check:
        raise HTTPException(status_code=500, detail="RFQ execution evidence could not be verified")
    return check[0]


def _rfq_id() -> str:
    return f"RFQ-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"


@app.get("/whatsapp/sales/rfq/health")
async def rfq_health() -> dict[str, Any]:
    persistence = persistent_backend_status()
    return {
        "status": "ok" if persistence.get("configured") else "configuration_required",
        "service": "whatsapp-rfq-execution-engine",
        "version": "1.0.0",
        "durable_rfq_creation": True,
        "sourcing_workstream": True,
        "logistics_workstream": True,
        "compliance_workstream": True,
        "quote_release": False,
        "binding_supplier_commitment": False,
        "evidence_required_before_quote": True,
        "persistence": persistence.get("provider"),
    }


@app.post("/whatsapp/sales/leads/{lead_id}/rfq/execute")
async def execute_rfq(lead_id: str, p: RFQExecutionRequest, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    lead = await _lead(lead_id)
    rfq_id = _rfq_id()
    package = {
        "rfq_id": rfq_id,
        "lead_id": lead_id,
        "phone": lead.get("phone"),
        "product": p.product,
        "specifications": p.specifications,
        "quantity_per_shipment": p.quantity_per_shipment,
        "shipment_count": p.shipment_count,
        "container_type": p.container_type,
        "packaging": p.packaging,
        "acceptable_origins": p.acceptable_origins,
        "destination": p.destination,
        "incoterm": p.incoterm,
        "target_budget": p.target_budget,
        "payment_terms_target": p.payment_terms_target,
        "first_delivery_target": p.first_delivery_target,
        "importer_legal_name": p.importer_legal_name,
        "importer_contact": p.importer_contact,
        "notes": p.notes,
        "status": "RFQ_READY",
        "quote_release_allowed": False,
        "supplier_commitment_allowed": False,
        "created_at": _now(),
    }

    created = await _event(
        lead_id=lead_id,
        event_type="rfq_created",
        title=f"RFQ created · {rfq_id}",
        summary=f"Structured RFQ created for {p.product}; sourcing, logistics and compliance evidence required before formal quote.",
        payload={"stage": "RFQ_READY", "rfq": package, "next_action": "Open sourcing, logistics and compliance workstreams"},
        priority="urgent",
        action_required=True,
        action_label="Execute RFQ workstreams",
    )

    sourcing = await _event(
        lead_id=lead_id,
        event_type="sourcing_workstream",
        title=f"Sourcing opened · {rfq_id}",
        summary="Supplier discovery and comparable-offer collection opened. No supplier has been selected or committed.",
        payload={
            "rfq_id": rfq_id,
            "department": "sourcing",
            "operation": "supplier_discovery_and_offer_collection",
            "acceptable_origins": p.acceptable_origins,
            "evidence_required": ["supplier identity", "formal/traceable offer", "specification match", "MOQ/capacity", "lead time", "offer validity"],
            "supplier_commitment_allowed": False,
        },
        action_label="Collect verified supplier offers",
    )

    logistics = await _event(
        lead_id=lead_id,
        event_type="logistics_workstream",
        title=f"Logistics review opened · {rfq_id}",
        summary="Freight and routing validation opened for the same commercial basis. No freight value is assumed until evidence is collected.",
        payload={
            "rfq_id": rfq_id,
            "department": "logistics",
            "operation": "freight_route_and_cost_validation",
            "destination": p.destination,
            "container_type": p.container_type,
            "incoterm": p.incoterm,
            "evidence_required": ["routing", "carrier/forwarder quote", "freight validity", "surcharges", "insurance scope where applicable"],
        },
        action_label="Validate freight and routing",
    )

    compliance = await _event(
        lead_id=lead_id,
        event_type="compliance_workstream",
        title=f"Compliance review opened · {rfq_id}",
        summary="Trade/compliance review opened. No regulatory conclusion or shipment release is implied.",
        payload={
            "rfq_id": rfq_id,
            "department": "compliance",
            "operation": "trade_requirements_and_document_review",
            "origins": p.acceptable_origins,
            "destination": p.destination,
            "importer_legal_name": p.importer_legal_name,
            "evidence_required": ["importer authority/role", "product documentation", "origin-specific requirements", "applicable licensing/sanctions/export-control review when relevant"],
            "release_authority": False,
        },
        action_label="Complete compliance evidence review",
    )

    return {
        "status": "executing",
        "lead_id": lead_id,
        "rfq_id": rfq_id,
        "stage": "RFQ_READY",
        "rfq": package,
        "evidence": {
            "rfq_created": created.get("event_id"),
            "sourcing": sourcing.get("event_id"),
            "logistics": logistics.get("event_id"),
            "compliance": compliance.get("event_id"),
        },
        "next_gate": "verified supplier + freight + compliance evidence before formal quote",
        "formal_quote_released": False,
    }


@app.get("/whatsapp/sales/leads/{lead_id}/rfq/executions")
async def rfq_executions(lead_id: str, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    await _lead(lead_id)
    rows = await get_backend().select(
        "business_events",
        params={"lead_id": f"eq.{lead_id}", "source_type": "eq.whatsapp_rfq_execution", "order": "created_at.desc", "limit": "500"},
    ) or []
    return {"status": "ok", "lead_id": lead_id, "count": len(rows), "events": rows}
