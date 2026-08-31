from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from insforge_backend import get_backend, persistent_backend_status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _event(*, mission: dict[str, Any], adapter: str, title: str, summary: str, payload: dict[str, Any]) -> dict[str, Any]:
    ts = _now()
    row = {
        "event_id": f"evt_{secrets.token_urlsafe(16)}",
        "event_type": "task",
        "source_type": "business_os_adapter",
        "source_id": str(mission.get("source_id") or ""),
        "trade_case_id": mission.get("trade_case_id"),
        "customer_id": mission.get("customer_id"),
        "actor_role": "ai",
        "actor_id": f"adapter:{adapter}",
        "visibility": "internal",
        "title": title[:240],
        "summary": summary[:3000],
        "action_required": False,
        "action_label": None,
        "priority": mission.get("priority") or "normal",
        "event_status": "completed",
        "payload": {"adapter": adapter, **payload},
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("business_events", row)
    rows = await get_backend().select("business_events", params={"event_id": f"eq.{row['event_id']}", "limit": "1"}) or []
    return {"adapter": adapter, "event_id": row["event_id"], "persisted": bool(rows), "record": rows[0] if rows else row}


async def execute_department_adapter(mission: dict[str, Any]) -> dict[str, Any]:
    payload = mission.get("payload") if isinstance(mission.get("payload"), dict) else {}
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    department = str(payload.get("department") or "executive").strip().lower()
    objective = str(mission.get("title") or mission.get("summary") or "Business OS mission").strip()

    if department in {"sales", "customer_success", "partnerships", "marketing", "cuba_trade_desk", "energy"}:
        return await _event(
            mission=mission,
            adapter="revenue_pipeline",
            title=f"Revenue pipeline action · {objective}",
            summary="Created a durable revenue-pipeline work item for qualification, next-best-action and follow-up. No binding price or commitment was released.",
            payload={
                "operation": "qualification_and_next_best_action",
                "department": department,
                "lead_id": context.get("lead_id"),
                "conversation_id": context.get("conversation_id"),
                "autonomous": True,
                "binding": False,
            },
        )

    if department == "sourcing":
        return await _event(
            mission=mission,
            adapter="sourcing_rfq",
            title=f"RFQ preparation · {objective}",
            summary="Created a durable sourcing/RFQ preparation work item including supplier discovery, offer comparison and evidence requirements. Supplier commitment remains gated.",
            payload={
                "operation": "rfq_prepare_and_supplier_shortlist",
                "product": context.get("product"),
                "quantity": context.get("quantity"),
                "origin": context.get("origin"),
                "destination": context.get("destination"),
                "supplier_commitment_allowed": False,
            },
        )

    if department in {"operations", "logistics"}:
        return await _event(
            mission=mission,
            adapter="operations_milestone",
            title=f"Operations milestone · {objective}",
            summary="Created a durable operations milestone for status coordination, document requests and next-action tracking.",
            payload={
                "operation": "milestone_and_document_coordination",
                "shipment_id": context.get("shipment_id"),
                "trade_case_id": mission.get("trade_case_id"),
                "release_authority": False,
            },
        )

    if department == "finance":
        return await _event(
            mission=mission,
            adapter="finance_analysis",
            title=f"Finance analysis · {objective}",
            summary="Created a durable finance-analysis work item for margin, invoice/payment-status or reconciliation research. No movement of funds is authorized.",
            payload={"operation": "margin_and_reconciliation_research", "funds_authority": False},
        )

    if department == "compliance":
        return await _event(
            mission=mission,
            adapter="compliance_research",
            title=f"Compliance research · {objective}",
            summary="Created a durable compliance research/checklist work item. Shipment release and regulatory conclusions remain governed.",
            payload={"operation": "screening_and_document_checklist", "release_authority": False},
        )

    if department in {"executive", "administration", "application"}:
        persistence = persistent_backend_status()
        return await _event(
            mission=mission,
            adapter="application_ops",
            title=f"Application operations check · {objective}",
            summary="Executed an application/persistence health inspection and persisted the observed result as execution evidence.",
            payload={
                "operation": "runtime_health_and_data_quality_check",
                "persistence_provider": persistence.get("provider"),
                "persistence_configured": bool(persistence.get("configured")),
                "supabase_configured": bool(persistence.get("supabase_configured")),
                "destructive_action": False,
            },
        )

    return await _event(
        mission=mission,
        adapter="general_operations",
        title=f"Department work item · {objective}",
        summary="Created and verified a durable reversible work item for the assigned department.",
        payload={"operation": "reversible_department_work", "department": department, "binding": False},
    )
