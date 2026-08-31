from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from communication_agentic_api import _mcp_follow_up, _mcp_handoff, _mcp_note
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY Business OS Mission Executor", version="1.0.0", docs_url=None, redoc_url=None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


async def _mission(mission_id: str) -> dict[str, Any]:
    rows = await get_backend().select(
        "business_events",
        params={
            "source_type": "eq.business_os_mission",
            "source_id": f"eq.{mission_id}",
            "order": "created_at.desc",
            "limit": "1",
        },
    ) or []
    if not rows:
        raise HTTPException(404, "Business OS mission not found")
    return rows[0]


async def _record_execution_event(
    *, mission: dict[str, Any], execution_id: str, state: str, step: str,
    summary: str, evidence: dict[str, Any] | None = None, action_required: bool = False,
) -> dict[str, Any]:
    ts = _now()
    row = {
        "event_id": f"evt_{secrets.token_urlsafe(16)}",
        "event_type": "task",
        "source_type": "business_os_execution",
        "source_id": str(mission.get("source_id") or ""),
        "trade_case_id": mission.get("trade_case_id"),
        "customer_id": mission.get("customer_id"),
        "actor_role": "ai",
        "actor_id": "business_os_executor",
        "visibility": "internal",
        "title": f"{step}: {str(mission.get('title') or '')[:180]}",
        "summary": summary[:3000],
        "action_required": action_required,
        "action_label": "Owner governance gate" if action_required else None,
        "priority": mission.get("priority") or "normal",
        "event_status": "open" if action_required or state in {"executing", "failed"} else "completed",
        "payload": {
            "execution_id": execution_id,
            "mission_id": mission.get("source_id"),
            "state": state,
            "step": step,
            "evidence": evidence or {},
        },
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("business_events", row)
    return row


async def execute_mission_internal(mission_id: str) -> dict[str, Any]:
    mission = await _mission(mission_id)
    payload = mission.get("payload") if isinstance(mission.get("payload"), dict) else {}
    objective = str(mission.get("title") or mission.get("summary") or "Business OS mission").strip()
    high_risk = bool(mission.get("action_required")) or bool(payload.get("high_risk")) or not bool(payload.get("autonomous_execution_allowed", True))
    execution_id = f"exec_{secrets.token_urlsafe(14)}"

    if high_risk:
        gate = await _record_execution_event(
            mission=mission,
            execution_id=execution_id,
            state="governance_required",
            step="governance_gate",
            summary="Mission contains a binding, financial, legal, compliance-release, destructive or irreversible action. Autonomous execution stopped before commitment.",
            evidence={"fail_closed": True},
            action_required=True,
        )
        return {"status": "governance_required", "mission_id": mission_id, "execution_id": execution_id, "event_id": gate["event_id"]}

    await _record_execution_event(
        mission=mission,
        execution_id=execution_id,
        state="executing",
        step="load_context",
        summary="Loaded persisted mission, department, customer/trade-case identifiers and execution policy.",
        evidence={
            "department": payload.get("department"),
            "customer_id": mission.get("customer_id"),
            "trade_case_id": mission.get("trade_case_id"),
        },
    )

    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    contact_id = context.get("contact_id")
    conversation_id = context.get("conversation_id")
    trade_case_id = mission.get("trade_case_id") or context.get("trade_case_id")

    note = await _mcp_note({
        "content": f"Business OS execution started for mission {mission_id}. Objective: {objective}",
        "note_type": "SUMMARY",
        "contact_id": contact_id,
        "conversation_id": conversation_id,
        "trade_case_id": trade_case_id,
    })

    follow_up = await _mcp_follow_up({
        "objective": objective,
        "mission_id": mission_id,
        "contact_id": contact_id,
        "conversation_id": conversation_id,
        "trade_case_id": trade_case_id,
    })

    handoff = None
    if bool(context.get("human_handoff_requested")):
        handoff = await _mcp_handoff({
            "reason": str(context.get("handoff_reason") or objective)[:1200],
            "urgency": str(mission.get("priority") or "high"),
            "conversation_id": conversation_id,
        })

    await _record_execution_event(
        mission=mission,
        execution_id=execution_id,
        state="executing",
        step="execute_reversible_work",
        summary="Queued a non-binding follow-up action and recorded an execution note. Optional handoff was requested when explicitly present in mission context.",
        evidence={"note": note, "follow_up": follow_up, "handoff": handoff},
    )

    action_id = str(follow_up.get("action_id") or "") if isinstance(follow_up, dict) else ""
    note_id = str(note.get("note_id") or "") if isinstance(note, dict) else ""
    action_rows = await get_backend().select("communication_action_queue", params={"action_id": f"eq.{action_id}", "limit": "1"}) if action_id else []
    note_rows = await get_backend().select("communication_agent_notes", params={"note_id": f"eq.{note_id}", "limit": "1"}) if note_id else []
    verified = bool(action_rows) and bool(note_rows)

    state = "completed" if verified else "failed"
    final = await _record_execution_event(
        mission=mission,
        execution_id=execution_id,
        state=state,
        step="verify_and_close_loop",
        summary="Mission execution evidence verified in the durable action queue and agent-note store." if verified else "Mission execution could not verify all durable evidence; retry or operator review is required.",
        evidence={
            "action_id": action_id,
            "action_persisted": bool(action_rows),
            "note_id": note_id,
            "note_persisted": bool(note_rows),
            "binding_action_executed": False,
        },
        action_required=not verified,
    )
    return {
        "status": state,
        "mission_id": mission_id,
        "execution_id": execution_id,
        "verified": verified,
        "action_id": action_id or None,
        "note_id": note_id or None,
        "event_id": final["event_id"],
        "binding_action_executed": False,
    }


class BatchRun(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


@app.get("/business-os/executor/health")
async def executor_health() -> dict[str, Any]:
    persistence = persistent_backend_status()
    return {
        "status": "ok" if persistence.get("configured") else "configuration_required",
        "service": "sahjony-business-os-mission-executor",
        "version": "1.0.0",
        "state_machine": ["planned", "executing", "verified", "completed", "governance_required", "failed"],
        "durable_action_queue": True,
        "durable_execution_evidence": True,
        "autonomous_nonbinding_execution": True,
        "binding_actions_fail_closed": True,
        "persistence_provider": persistence.get("provider"),
    }


@app.post("/business-os/missions/{mission_id}/execute")
async def execute_mission(mission_id: str, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    return await execute_mission_internal(mission_id)


@app.get("/business-os/missions/{mission_id}/executions")
async def mission_executions(mission_id: str, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    rows = await get_backend().select(
        "business_events",
        params={"source_type": "eq.business_os_execution", "source_id": f"eq.{mission_id}", "order": "created_at.desc", "limit": "200"},
    ) or []
    return {"status": "ok", "mission_id": mission_id, "count": len(rows), "executions": rows}


@app.post("/business-os/executor/run-ready")
async def run_ready(payload: BatchRun, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    missions = await get_backend().select(
        "business_events",
        params={"source_type": "eq.business_os_mission", "event_status": "eq.open", "order": "created_at.asc", "limit": str(payload.limit)},
    ) or []
    results: list[dict[str, Any]] = []
    for mission in missions:
        mission_id = str(mission.get("source_id") or "")
        if not mission_id:
            continue
        execution_events = await get_backend().select(
            "business_events",
            params={"source_type": "eq.business_os_execution", "source_id": f"eq.{mission_id}", "order": "created_at.desc", "limit": "1"},
        ) or []
        if execution_events:
            state = ((execution_events[0].get("payload") or {}).get("state") if isinstance(execution_events[0].get("payload"), dict) else None)
            if state in {"completed", "executing", "governance_required"}:
                continue
        results.append(await execute_mission_internal(mission_id))
    return {"status": "ok", "attempted": len(results), "results": results}
