from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY WhatsApp Relationship Memory", version="1.0.0", docs_url=None, redoc_url=None)

FactState = Literal["known", "uncertain", "missing"]

CORE_FACTS = [
    "contact_name",
    "company",
    "role",
    "preferred_language",
    "product",
    "specification",
    "quantity",
    "container_type",
    "origin",
    "destination",
    "target_delivery_date",
    "target_budget",
    "incoterm",
    "payment_preference",
    "decision_authority",
    "importer_or_importing_entity",
]

PROGRESSIVE_DISCOVERY_PRIORITY = [
    "product",
    "quantity",
    "destination",
    "target_delivery_date",
    "specification",
    "container_type",
    "origin",
    "target_budget",
    "incoterm",
    "payment_preference",
    "importer_or_importing_entity",
    "decision_authority",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


class RelationshipFact(BaseModel):
    key: str = Field(min_length=2, max_length=160)
    value: str | float | int | bool | None = None
    state: FactState = "known"
    source: str = Field(default="conversation", max_length=160)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    note: str | None = Field(default=None, max_length=2000)


class MemoryUpsert(BaseModel):
    facts: list[RelationshipFact] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    next_action: str | None = Field(default=None, max_length=2000)
    relationship_stage: str | None = Field(default=None, max_length=120)


async def _lead(lead_id: str) -> dict[str, Any]:
    rows = await get_backend().select("whatsapp_leads", params={"lead_id": f"eq.{lead_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(status_code=404, detail="WhatsApp lead not found")
    return rows[0]


async def _events(lead_id: str) -> list[dict[str, Any]]:
    try:
        return await get_backend().select(
            "business_events",
            params={"lead_id": f"eq.{lead_id}", "order": "created_at.asc", "limit": "2000"},
        ) or []
    except Exception:
        return []


def _merge_memory(lead: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    facts: dict[str, dict[str, Any]] = {}
    commitments: list[str] = []
    objections: list[str] = []
    next_action: str | None = None
    relationship_stage: str | None = None

    # Seed safe facts already present on the durable lead row.
    seed_map = {
        "contact_name": lead.get("name") or lead.get("contact_name"),
        "company": lead.get("company") or lead.get("business_name"),
        "preferred_language": lead.get("language"),
    }
    for key, value in seed_map.items():
        if value not in (None, ""):
            facts[key] = {"key": key, "value": value, "state": "known", "source": "whatsapp_lead", "confidence": 1.0}

    # Qualification events are authoritative conversational memory for trade requirements.
    qualification_keys = {
        "product_need": "product",
        "specifications": "specification",
        "quantity": "quantity",
        "container_type": "container_type",
        "origin": "origin",
        "destination": "destination",
        "target_budget": "target_budget",
        "target_delivery_date": "target_delivery_date",
        "preferred_incoterm": "incoterm",
    }

    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        for source_key, memory_key in qualification_keys.items():
            value = payload.get(source_key)
            if value not in (None, ""):
                facts[memory_key] = {"key": memory_key, "value": value, "state": "known", "source": "qualification", "confidence": 1.0}

        if event.get("source_type") == "whatsapp_relationship_memory":
            for item in payload.get("facts") or []:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if key:
                    facts[key] = item
            commitments.extend(str(x) for x in (payload.get("commitments") or []) if str(x).strip())
            objections.extend(str(x) for x in (payload.get("objections") or []) if str(x).strip())
            if payload.get("next_action"):
                next_action = str(payload["next_action"])
            if payload.get("relationship_stage"):
                relationship_stage = str(payload["relationship_stage"])

        # Sales brain/stage events can contribute next action and relationship stage.
        if payload.get("next_action"):
            next_action = str(payload["next_action"])
        if payload.get("stage"):
            relationship_stage = str(payload["stage"])

    # Deduplicate while preserving order.
    commitments = list(dict.fromkeys(commitments))[-50:]
    objections = list(dict.fromkeys(objections))[-50:]

    known = {k: v for k, v in facts.items() if str(v.get("state") or "known") == "known" and v.get("value") not in (None, "")}
    uncertain = {k: v for k, v in facts.items() if str(v.get("state") or "") == "uncertain"}
    missing = [key for key in CORE_FACTS if key not in known]
    next_questions = [key for key in PROGRESSIVE_DISCOVERY_PRIORITY if key in missing][:2]

    return {
        "facts": facts,
        "known": known,
        "uncertain": uncertain,
        "missing": missing,
        "next_questions": next_questions,
        "commitments": commitments,
        "objections": objections,
        "next_action": next_action,
        "relationship_stage": relationship_stage or "NEW",
        "rules": {
            "repeat_known_fact_questions": False,
            "max_questions_per_turn": 2,
            "confirm_uncertain_once": True,
            "changed_facts_replace_prior": True,
            "unknown_means_unknown": True,
        },
    }


@app.get("/whatsapp/relationship-memory/health")
async def relationship_memory_health() -> dict[str, Any]:
    persistence = persistent_backend_status()
    return {
        "status": "ok" if persistence.get("configured") else "configuration_required",
        "service": "whatsapp-relationship-memory-360",
        "version": "1.0.0",
        "persona": "Sofia Reyes",
        "durable": bool(persistence.get("configured")),
        "persistent_backend": persistence.get("provider"),
        "progressive_discovery": True,
        "known_fact_repeat_suppression": True,
        "commitment_memory": True,
        "objection_memory": True,
        "next_best_action_memory": True,
        "max_questions_per_turn": 2,
    }


@app.get("/whatsapp/relationship-memory/leads/{lead_id}")
async def relationship_memory(lead_id: str, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    lead = await _lead(lead_id)
    memory = _merge_memory(lead, await _events(lead_id))
    return {"status": "ok", "lead_id": lead_id, "phone": lead.get("phone"), "memory": memory}


@app.post("/whatsapp/relationship-memory/leads/{lead_id}")
async def upsert_relationship_memory(lead_id: str, payload: MemoryUpsert, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    lead = await _lead(lead_id)
    ts = _now()
    row = {
        "event_id": f"evt_{secrets.token_urlsafe(16)}",
        "event_type": "memory_update",
        "source_type": "whatsapp_relationship_memory",
        "source_id": lead_id,
        "trade_case_id": None,
        "customer_id": None,
        "lead_id": lead_id,
        "actor_role": "system",
        "actor_id": "sofia-reyes-relationship-memory",
        "visibility": "internal",
        "title": "WhatsApp relationship memory updated",
        "summary": payload.next_action or "Relationship facts, commitments and objections updated.",
        "action_required": bool(payload.next_action),
        "action_label": payload.next_action,
        "priority": "high" if payload.next_action else "normal",
        "event_status": "open" if payload.next_action else "closed",
        "payload": payload.model_dump(),
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("business_events", row)
    memory = _merge_memory(lead, await _events(lead_id))
    return {"status": "updated", "lead_id": lead_id, "event_id": row["event_id"], "memory": memory}


@app.get("/whatsapp/relationship-memory/leads/{lead_id}/prompt-context")
async def prompt_context(lead_id: str, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    lead = await _lead(lead_id)
    memory = _merge_memory(lead, await _events(lead_id))
    known_lines = [f"- {k}: {v.get('value')}" for k, v in memory["known"].items()]
    context = "\n".join([
        "RELATIONSHIP MEMORY — DO NOT ASK FOR KNOWN FACTS AGAIN",
        *(known_lines or ["- No durable facts yet"]),
        f"Relationship stage: {memory['relationship_stage']}",
        f"Open commitments: {memory['commitments'][-5:]}",
        f"Known objections: {memory['objections'][-5:]}",
        f"Next action: {memory['next_action'] or 'none recorded'}",
        f"Only ask up to 2 missing items now: {memory['next_questions']}",
        "If a fact changed, acknowledge the change and replace the old fact. If uncertain, confirm it once. Keep the reply conversational and commercially useful.",
    ])
    return {"status": "ok", "lead_id": lead_id, "prompt_context": context, "memory": memory}
