from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from insforge_backend import get_backend, persistent_backend_status

router = APIRouter()

SIGNATURE_VERSION = "crm-v1"
BRIDGE_ACTOR_ID = "openclaw-hostinger"
MAX_CLOCK_SKEW_SECONDS = 300


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bridge_secret() -> str:
    return (
        os.getenv("OPENCLAW_APP_BRIDGE_SECRET", "").strip()
        or os.getenv("SAHJONY_APP_BRIDGE_SECRET", "").strip()
    )


def _normalize_phone(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) < 8 or len(digits) > 15:
        raise HTTPException(status_code=400, detail="A valid international phone number is required")
    return digits


def _stable_id(prefix: str, value: str, length: int = 24) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}{digest}"


def _signature_material(*, timestamp: str, nonce: str, method: str, path: str, raw: bytes) -> bytes:
    body_hash = hashlib.sha256(raw).hexdigest()
    return (
        f"{SIGNATURE_VERSION}\n{timestamp}\n{nonce}\n{method.upper()}\n{path}\n{body_hash}"
    ).encode("utf-8")


def _verify_bridge_request(
    request: Request,
    raw: bytes,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
) -> None:
    secret = _bridge_secret()
    if len(secret) < 24:
        raise HTTPException(status_code=503, detail="Authorized CRM application bridge is not configured")
    try:
        request_time = int(timestamp or "")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid CRM bridge timestamp") from exc
    if abs(int(datetime.now(timezone.utc).timestamp()) - request_time) > MAX_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=401, detail="Expired CRM bridge request")
    clean_nonce = str(nonce or "").strip()
    if len(clean_nonce) < 12 or len(clean_nonce) > 160:
        raise HTTPException(status_code=401, detail="Invalid CRM bridge nonce")
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        _signature_material(
            timestamp=str(request_time),
            nonce=clean_nonce,
            method=request.method,
            path=request.url.path,
            raw=raw,
        ),
        hashlib.sha256,
    ).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid CRM bridge signature")


class CRMContactLookup(BaseModel):
    phone: str = Field(min_length=8, max_length=40)


class CRMSyncIn(BaseModel):
    operation_id: str = Field(min_length=8, max_length=160)
    phone: str = Field(min_length=8, max_length=40)
    contact_name: str | None = Field(default=None, max_length=256)
    company_name: str | None = Field(default=None, max_length=320)
    email: str | None = Field(default=None, max_length=320)
    country_code: str | None = Field(default=None, max_length=3)
    latest_message: str | None = Field(default=None, max_length=4096)


class CRMNoteIn(BaseModel):
    operation_id: str = Field(min_length=8, max_length=160)
    phone: str = Field(min_length=8, max_length=40)
    summary: str = Field(min_length=1, max_length=4000)
    note_type: Literal["conversation_note", "follow_up", "customer_request", "internal"] = "conversation_note"
    action_required: bool = False
    action_label: str | None = Field(default=None, max_length=240)


class CRMIntakeIn(BaseModel):
    operation_id: str = Field(min_length=8, max_length=160)
    phone: str = Field(min_length=8, max_length=40)
    product_need: str = Field(min_length=2, max_length=1000)
    destination_country: str = Field(min_length=2, max_length=3)
    specifications: str | None = Field(default=None, max_length=4000)
    quantity: float | None = None
    target_budget: float | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    target_delivery_date: str | None = Field(default=None, max_length=80)
    preferred_incoterm: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=4000)


class CRMOutreachPilotIn(BaseModel):
    operation_id: str = Field(min_length=8, max_length=160)
    limit: int = Field(default=25, ge=1, le=50)
    dry_run: bool = False


class CRMOutreachStatusIn(BaseModel):
    operation_id: str = Field(min_length=8, max_length=160)


async def _operation(operation_id: str) -> dict[str, Any] | None:
    rows = await get_backend().select(
        "crm_bridge_operations",
        params={"operation_id": f"eq.{operation_id}", "limit": "1"},
    ) or []
    return rows[0] if rows else None


def _safe_phone(value: Any) -> str:
    try:
        return _normalize_phone(str(value or ""))
    except HTTPException:
        return ""


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


async def run_outreach_pilot(payload: CRMOutreachPilotIn) -> dict[str, Any]:
    prior = await _operation(payload.operation_id)
    if prior:
        result = prior.get("result") if isinstance(prior.get("result"), dict) else {}
        return {"status": "duplicate", "operation_id": payload.operation_id, **result}
    backend = get_backend()
    accounts = await backend.select("customer_accounts", params={"limit": "5000"}) or []
    messages = await backend.select("whatsapp_messages", params={"limit": "5000"}) or []
    outbound = await backend.select("outbound_notifications", params={"channel": "eq.whatsapp", "limit": "5000"}) or []
    inbound_phones = {_safe_phone(r.get("phone")) for r in messages if str(r.get("direction") or "").lower() == "inbound"}
    inbound_phones.discard("")
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recently_contacted = set()
    for row in outbound:
        phone = _safe_phone(row.get("destination"))
        created = _parse_time(row.get("created_at") or row.get("updated_at"))
        if phone and created and created >= recent_cutoff:
            recently_contacted.add(phone)
    blocked = {"DO_NOT_CONTACT", "OPTED_OUT", "LOST"}
    candidates = []
    seen = set()
    for row in accounts:
        status = str(row.get("sales_status") or row.get("status") or "NEW").upper()
        consent_status = str(row.get("consent_status") or "").upper()
        phone = _safe_phone(row.get("phone"))
        if not phone or phone in seen or phone in recently_contacted:
            continue
        seen.add(phone)
        if status in blocked or consent_status in {"REVOKED", "DO_NOT_CONTACT"}:
            continue
        explicit_consent = row.get("consent_to_business_contact") is True or consent_status == "CONSENTED"
        prior_relationship = phone in inbound_phones
        if not (explicit_consent or prior_relationship):
            continue
        score = 0
        if status in {"REPLIED", "QUALIFIED_LEAD", "FOLLOW_UP_DUE"}: score += 50
        if prior_relationship: score += 30
        if explicit_consent: score += 20
        if row.get("legal_name") or row.get("trade_name"): score += 10
        candidates.append((score, row, phone))
    candidates.sort(key=lambda x: (-x[0], str(x[1].get("updated_at") or "")), reverse=False)
    selected = candidates[:payload.limit]
    if payload.dry_run:
        result = {"status": "planned", "operation_id": payload.operation_id, "eligible": len(candidates), "selected": len(selected), "queued": 0, "messages_sent": 0}
        await _record_operation(payload.operation_id, "outreach_pilot_dry_run", result)
        return result
    queued = 0
    for _, row, phone in selected:
        customer_id = str(row.get("customer_id") or "") or None
        name = str(row.get("contact_name") or row.get("trade_name") or row.get("legal_name") or "").strip()
        greeting = f"Hola {name}," if name else "Hola,"
        body = (
            f"{greeting} soy Sofía de SAHJONY LLC. Gracias por tu contacto/interés previo. "
            "¿Sigue activo tu proyecto de importación o abastecimiento? Si me indicas producto, cantidad, destino y fecha objetivo, preparo el siguiente paso. "
            "Si no deseas más mensajes, dímelo y no volveremos a contactarte."
        )[:4096]
        command_id = f"waq_{secrets.token_urlsafe(18)}"
        ts = _now()
        await backend.insert("whatsapp_openclaw_outbox", {
            "command_id": command_id, "channel": "whatsapp", "account_id": "default", "recipient": phone, "body": body,
            "preview_url": False, "lead_id": None, "customer_id": customer_id, "source_url": f"crm:outreach-pilot:{payload.operation_id}",
            "status": "queued", "attempts": 0, "lease_token": None, "lease_expires_at": None, "provider_message_id": None,
            "last_error": None, "created_at": ts, "updated_at": ts,
        })
        await backend.insert("outbound_notifications", {
            "notification_id": command_id, "event_id": payload.operation_id, "recipient_role": "customer", "recipient_id": customer_id or "external",
            "channel": "whatsapp", "destination": phone, "subject": "Governed WhatsApp reactivation", "body": body,
            "delivery_status": "queued", "provider": "hermes_whatsapp", "provider_message_id": None,
            "source_url": f"crm:outreach-pilot:{payload.operation_id}", "autonomous": True, "attempts": 0, "last_error": None,
            "created_at": ts, "updated_at": ts,
        })
        await backend.insert("customer_crm_audit", {
            "event_id": f"crm_{secrets.token_urlsafe(10)}", "customer_id": customer_id, "intake_id": None, "actor_role": "ai_agent",
            "actor_id": "sofia-smith", "event_type": "sofia_outreach_queued", "summary": "Governed WhatsApp reactivation queued; send evidence pending transport acknowledgement.",
            "payload": {"operation_id": payload.operation_id, "command_id": command_id, "consent_evidence": "explicit_or_prior_inbound", "message_sent": False}, "created_at": ts,
        })
        queued += 1
    result = {"status": "queued", "operation_id": payload.operation_id, "eligible": len(candidates), "selected": len(selected), "queued": queued, "messages_sent": 0}
    await _record_operation(payload.operation_id, "outreach_pilot", result)
    return result


async def outreach_pilot_status(payload: CRMOutreachStatusIn) -> dict[str, Any]:
    rows = await get_backend().select("outbound_notifications", params={"event_id": f"eq.{payload.operation_id}", "channel": "eq.whatsapp", "limit": "5000"}) or []
    counts = {}
    for row in rows:
        key = str(row.get("delivery_status") or "unknown").lower()
        counts[key] = counts.get(key, 0) + 1
    return {"status": "ok", "operation_id": payload.operation_id, "total": len(rows), "delivery": counts, "messages_sent": counts.get("sent", 0)}


async def _record_operation(operation_id: str, action: str, result: dict[str, Any]) -> None:
    await get_backend().insert(
        "crm_bridge_operations",
        {
            "operation_id": operation_id,
            "action": action,
            "actor_id": BRIDGE_ACTOR_ID,
            "status": "completed",
            "result": result,
            "completed_at": _now(),
            "updated_at": _now(),
        },
    )


async def _rows_by_phone(table: str, phone: str, *, limit: int = 25) -> list[dict[str, Any]]:
    backend = get_backend()
    seen: set[str] = set()
    found: list[dict[str, Any]] = []
    for candidate in (phone, f"+{phone}"):
        try:
            rows = await backend.select(table, params={"phone": f"eq.{candidate}", "limit": str(limit)}) or []
        except Exception:
            rows = []
        for row in rows:
            marker = json.dumps(row, sort_keys=True, default=str)
            if marker not in seen:
                seen.add(marker)
                found.append(row)
    if found:
        return found[:limit]

    # Compatibility fallback for older CRM rows that stored formatted phone numbers.
    try:
        rows = await backend.select(table, params={"limit": "10000"}) or []
    except Exception:
        rows = []
    for row in rows:
        raw = str(row.get("phone") or "")
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits != phone:
            continue
        marker = json.dumps(row, sort_keys=True, default=str)
        if marker not in seen:
            seen.add(marker)
            found.append(row)
        if len(found) >= limit:
            break
    return found


async def get_contact_context(phone_value: str) -> dict[str, Any]:
    phone = _normalize_phone(phone_value)
    backend = get_backend()
    leads = await _rows_by_phone("whatsapp_leads", phone, limit=5)
    customers = await _rows_by_phone("customer_accounts", phone, limit=5)
    customer_ids = [str(row.get("customer_id")) for row in customers if row.get("customer_id")]
    lead_ids = [str(row.get("lead_id")) for row in leads if row.get("lead_id")]

    intakes: list[dict[str, Any]] = []
    for customer_id in customer_ids[:5]:
        try:
            rows = await backend.select(
                "customer_trade_intakes",
                params={"customer_id": f"eq.{customer_id}", "order": "updated_at.desc", "limit": "20"},
            ) or []
            intakes.extend(rows)
        except Exception:
            continue

    try:
        messages = await backend.select(
            "whatsapp_messages",
            params={"phone": f"eq.{phone}", "order": "received_at.desc", "limit": "25"},
        ) or []
    except Exception:
        messages = []

    events: list[dict[str, Any]] = []
    for lead_id in lead_ids[:3]:
        try:
            rows = await backend.select(
                "business_events",
                params={"lead_id": f"eq.{lead_id}", "order": "created_at.desc", "limit": "25"},
            ) or []
            events.extend(rows)
        except Exception:
            continue

    return {
        "status": "ok",
        "phone": phone,
        "whatsapp_leads": leads,
        "customers": customers,
        "trade_intakes": intakes[:20],
        "recent_messages": messages[:25],
        "recent_events": events[:25],
        "crm_connected": True,
        "source_of_truth": "supabase_trade_persistence",
    }


async def _ensure_customer(
    *,
    phone: str,
    lead_id: str,
    contact_name: str | None = None,
    company_name: str | None = None,
    email: str | None = None,
    country_code: str | None = None,
    create_minimal: bool = False,
) -> dict[str, Any] | None:
    backend = get_backend()
    matches = await _rows_by_phone("customer_accounts", phone, limit=5)
    customer = matches[0] if matches else None
    ts = _now()
    if customer:
        customer_id = str(customer.get("customer_id") or "")
        values: dict[str, Any] = {
            "whatsapp_lead_id": lead_id,
            "last_contact_at": ts,
            "updated_at": ts,
        }
        if contact_name and not customer.get("contact_name"):
            values["contact_name"] = contact_name
        if company_name and not customer.get("legal_name"):
            values["legal_name"] = company_name
        if email and not customer.get("email"):
            values["email"] = email.strip().lower()
        if country_code and not customer.get("country_code"):
            values["country_code"] = country_code.upper()
        if customer_id:
            await backend.patch("customer_accounts", values, params={"customer_id": f"eq.{customer_id}"})
            return {**customer, **values}
        return customer

    if not (create_minimal or contact_name or company_name or email):
        return None

    customer_id = _stable_id("cus_wa_", phone, 20)
    row = {
        "customer_id": customer_id,
        "legal_name": company_name or None,
        "trade_name": company_name or None,
        "contact_name": contact_name or None,
        "email": email.strip().lower() if email else None,
        "phone": phone,
        "country_code": country_code.upper() if country_code else None,
        "status": "PROSPECT",
        "sales_status": "REPLIED",
        "source": "WHATSAPP",
        "whatsapp_lead_id": lead_id,
        "created_at": ts,
        "updated_at": ts,
        "last_contact_at": ts,
    }
    await backend.insert("customer_accounts", row)
    return row


async def sync_contact(payload: CRMSyncIn) -> dict[str, Any]:
    existing_op = await _operation(payload.operation_id)
    if existing_op:
        return {"status": "duplicate", "operation_id": payload.operation_id, "result": existing_op.get("result")}

    phone = _normalize_phone(payload.phone)
    backend = get_backend()
    lead_id = _stable_id("wa_", phone, 24)
    leads = await _rows_by_phone("whatsapp_leads", phone, limit=1)
    existing = leads[0] if leads else {}
    ts = _now()
    lead = {
        **existing,
        "lead_id": lead_id,
        "phone": phone,
        "contact_name": payload.contact_name or existing.get("contact_name"),
        "source": existing.get("source") or "WHATSAPP_INBOUND",
        "channel": "whatsapp",
        "status": existing.get("status") or "NEW",
        "first_seen_at": existing.get("first_seen_at") or ts,
        "last_seen_at": ts,
        "last_message": payload.latest_message[:4000] if payload.latest_message else existing.get("last_message"),
        "assigned_owner_id": existing.get("assigned_owner_id") or "owner",
        "ai_followup_allowed": existing.get("ai_followup_allowed", True),
        "crm_bridge_last_sync_at": ts,
        "updated_at": ts,
    }
    customer = await _ensure_customer(
        phone=phone,
        lead_id=lead_id,
        contact_name=payload.contact_name,
        company_name=payload.company_name,
        email=payload.email,
        country_code=payload.country_code,
    )
    if customer and customer.get("customer_id"):
        lead["crm_customer_id"] = customer["customer_id"]
    await backend.insert("whatsapp_leads", lead)

    event_id = _stable_id("evt_crm_", payload.operation_id, 24)
    await backend.insert(
        "business_events",
        {
            "event_id": event_id,
            "event_type": "crm_sync",
            "source_type": "openclaw_crm_bridge",
            "source_id": payload.operation_id,
            "trade_case_id": None,
            "customer_id": customer.get("customer_id") if customer else None,
            "lead_id": lead_id,
            "actor_role": "digital_representative",
            "actor_id": BRIDGE_ACTOR_ID,
            "visibility": "internal",
            "title": "WhatsApp CRM synchronized",
            "summary": "Authorized OpenClaw CRM synchronization completed",
            "action_required": False,
            "action_label": None,
            "priority": "normal",
            "event_status": "closed",
            "payload": {"channel": "whatsapp", "operation_id": payload.operation_id},
            "created_at": ts,
            "updated_at": ts,
        },
    )
    result = {
        "status": "synced",
        "operation_id": payload.operation_id,
        "lead_id": lead_id,
        "customer_id": customer.get("customer_id") if customer else None,
        "crm_connected": True,
    }
    await _record_operation(payload.operation_id, "sync", result)
    return result


async def add_note(payload: CRMNoteIn) -> dict[str, Any]:
    existing_op = await _operation(payload.operation_id)
    if existing_op:
        return {"status": "duplicate", "operation_id": payload.operation_id, "result": existing_op.get("result")}

    context = await get_contact_context(payload.phone)
    phone = context["phone"]
    lead = (context.get("whatsapp_leads") or [{}])[0]
    customer = (context.get("customers") or [{}])[0]
    lead_id = lead.get("lead_id") or _stable_id("wa_", phone, 24)
    event_id = _stable_id("evt_crm_", payload.operation_id, 24)
    ts = _now()
    await get_backend().insert(
        "business_events",
        {
            "event_id": event_id,
            "event_type": payload.note_type,
            "source_type": "openclaw_crm_bridge",
            "source_id": payload.operation_id,
            "trade_case_id": None,
            "customer_id": customer.get("customer_id"),
            "lead_id": lead_id,
            "actor_role": "digital_representative",
            "actor_id": BRIDGE_ACTOR_ID,
            "visibility": "internal",
            "title": "WhatsApp CRM note",
            "summary": payload.summary,
            "action_required": payload.action_required,
            "action_label": payload.action_label,
            "priority": "high" if payload.action_required else "normal",
            "event_status": "open" if payload.action_required else "closed",
            "payload": {"channel": "whatsapp", "operation_id": payload.operation_id},
            "created_at": ts,
            "updated_at": ts,
        },
    )
    result = {
        "status": "recorded",
        "operation_id": payload.operation_id,
        "event_id": event_id,
        "lead_id": lead_id,
        "customer_id": customer.get("customer_id"),
        "crm_connected": True,
    }
    await _record_operation(payload.operation_id, "note", result)
    return result


async def create_trade_intake(payload: CRMIntakeIn) -> dict[str, Any]:
    existing_op = await _operation(payload.operation_id)
    if existing_op:
        return {"status": "duplicate", "operation_id": payload.operation_id, "result": existing_op.get("result")}

    phone = _normalize_phone(payload.phone)
    lead_id = _stable_id("wa_", phone, 24)
    customer = await _ensure_customer(phone=phone, lead_id=lead_id, create_minimal=True)
    if not customer or not customer.get("customer_id"):
        raise HTTPException(status_code=503, detail="CRM customer linkage could not be created")
    customer_id = str(customer["customer_id"])
    intake_id = _stable_id("int_wa_", payload.operation_id, 22)
    ts = _now()
    row = {
        "intake_id": intake_id,
        "customer_id": customer_id,
        "product_need": payload.product_need,
        "specifications": payload.specifications,
        "quantity": payload.quantity,
        "target_budget": payload.target_budget,
        "currency": payload.currency.upper(),
        "destination_country": payload.destination_country.upper(),
        "target_delivery_date": payload.target_delivery_date,
        "preferred_incoterm": payload.preferred_incoterm,
        "notes": payload.notes,
        "status": "NEW",
        "qualification_status": "PENDING",
        "source": "WHATSAPP",
        "created_at": ts,
        "updated_at": ts,
    }
    backend = get_backend()
    await backend.insert("customer_trade_intakes", row)
    await backend.patch(
        "customer_accounts",
        {"sales_status": "QUALIFIED_LEAD", "updated_at": ts},
        params={"customer_id": f"eq.{customer_id}"},
    )
    event_id = _stable_id("evt_crm_", payload.operation_id, 24)
    await backend.insert(
        "business_events",
        {
            "event_id": event_id,
            "event_type": "trade_intake_created",
            "source_type": "openclaw_crm_bridge",
            "source_id": payload.operation_id,
            "trade_case_id": None,
            "customer_id": customer_id,
            "lead_id": lead_id,
            "actor_role": "digital_representative",
            "actor_id": BRIDGE_ACTOR_ID,
            "visibility": "internal",
            "title": "WhatsApp trade requirement captured",
            "summary": payload.product_need[:1000],
            "action_required": True,
            "action_label": "Qualify and source trade requirement",
            "priority": "high",
            "event_status": "open",
            "payload": {"intake_id": intake_id, "operation_id": payload.operation_id},
            "created_at": ts,
            "updated_at": ts,
        },
    )
    result = {
        "status": "created",
        "operation_id": payload.operation_id,
        "intake_id": intake_id,
        "customer_id": customer_id,
        "lead_id": lead_id,
        "crm_connected": True,
        "external_commitment_created": False,
    }
    await _record_operation(payload.operation_id, "intake", result)
    return result


async def crm_bridge_status() -> dict[str, Any]:
    persistence = persistent_backend_status()
    configured = len(_bridge_secret()) >= 24 and bool(persistence.get("configured"))
    if not configured:
        return {
            "status": "configuration_required",
            "service": "openclaw-crm-bridge",
            "authorized_bridge_configured": len(_bridge_secret()) >= 24,
            "backend_configured": bool(persistence.get("configured")),
            "provider": persistence.get("provider"),
            "read_scope": "crm_contact_360",
            "write_scopes": ["lead_sync", "internal_note", "trade_intake"],
            "destructive_scope": False,
            "external_commitment_scope": False,
        }
    try:
        await get_backend().select("whatsapp_leads", params={"limit": "1"})
        reachable = True
        error = None
    except Exception as exc:
        reachable = False
        error = type(exc).__name__
    return {
        "status": "ok" if reachable else "degraded",
        "service": "openclaw-crm-bridge",
        "authorized_bridge_configured": True,
        "backend_configured": True,
        "backend_reachable": reachable,
        "provider": persistence.get("provider"),
        "read_scope": "crm_contact_360",
        "write_scopes": ["lead_sync", "internal_note", "trade_intake"],
        "destructive_scope": False,
        "external_commitment_scope": False,
        "error": error,
    }


def _headers(
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
) -> tuple[str | None, str | None, str | None]:
    return timestamp, nonce, signature


@router.get("/whatsapp/crm/health")
async def crm_health(
    request: Request,
    x_sahjony_timestamp: str | None = Header(None, alias="X-SAHJONY-Timestamp"),
    x_sahjony_nonce: str | None = Header(None, alias="X-SAHJONY-Nonce"),
    x_sahjony_crm_signature: str | None = Header(None, alias="X-SAHJONY-CRM-Signature"),
) -> dict[str, Any]:
    _verify_bridge_request(request, b"", *_headers(x_sahjony_timestamp, x_sahjony_nonce, x_sahjony_crm_signature))
    return await crm_bridge_status()


@router.post("/whatsapp/crm/contact")
async def crm_contact(
    request: Request,
    x_sahjony_timestamp: str | None = Header(None, alias="X-SAHJONY-Timestamp"),
    x_sahjony_nonce: str | None = Header(None, alias="X-SAHJONY-Nonce"),
    x_sahjony_crm_signature: str | None = Header(None, alias="X-SAHJONY-CRM-Signature"),
) -> dict[str, Any]:
    raw = await request.body()
    _verify_bridge_request(request, raw, *_headers(x_sahjony_timestamp, x_sahjony_nonce, x_sahjony_crm_signature))
    try:
        payload = CRMContactLookup.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid CRM contact lookup") from exc
    return await get_contact_context(payload.phone)


@router.post("/whatsapp/crm/sync")
async def crm_sync(
    request: Request,
    x_sahjony_timestamp: str | None = Header(None, alias="X-SAHJONY-Timestamp"),
    x_sahjony_nonce: str | None = Header(None, alias="X-SAHJONY-Nonce"),
    x_sahjony_crm_signature: str | None = Header(None, alias="X-SAHJONY-CRM-Signature"),
) -> dict[str, Any]:
    raw = await request.body()
    _verify_bridge_request(request, raw, *_headers(x_sahjony_timestamp, x_sahjony_nonce, x_sahjony_crm_signature))
    try:
        payload = CRMSyncIn.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid CRM synchronization payload") from exc
    return await sync_contact(payload)


@router.post("/whatsapp/crm/note")
async def crm_note(
    request: Request,
    x_sahjony_timestamp: str | None = Header(None, alias="X-SAHJONY-Timestamp"),
    x_sahjony_nonce: str | None = Header(None, alias="X-SAHJONY-Nonce"),
    x_sahjony_crm_signature: str | None = Header(None, alias="X-SAHJONY-CRM-Signature"),
) -> dict[str, Any]:
    raw = await request.body()
    _verify_bridge_request(request, raw, *_headers(x_sahjony_timestamp, x_sahjony_nonce, x_sahjony_crm_signature))
    try:
        payload = CRMNoteIn.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid CRM note payload") from exc
    return await add_note(payload)


@router.post("/whatsapp/crm/outreach-pilot")
async def crm_outreach_pilot(
    request: Request,
    x_sahjony_timestamp: str | None = Header(None, alias="X-SAHJONY-Timestamp"),
    x_sahjony_nonce: str | None = Header(None, alias="X-SAHJONY-Nonce"),
    x_sahjony_crm_signature: str | None = Header(None, alias="X-SAHJONY-CRM-Signature"),
) -> dict[str, Any]:
    raw = await request.body()
    _verify_bridge_request(request, raw, *_headers(x_sahjony_timestamp, x_sahjony_nonce, x_sahjony_crm_signature))
    try:
        payload = CRMOutreachPilotIn.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid outreach pilot payload") from exc
    return await run_outreach_pilot(payload)


@router.post("/whatsapp/crm/outreach-pilot/status")
async def crm_outreach_pilot_status(
    request: Request,
    x_sahjony_timestamp: str | None = Header(None, alias="X-SAHJONY-Timestamp"),
    x_sahjony_nonce: str | None = Header(None, alias="X-SAHJONY-Nonce"),
    x_sahjony_crm_signature: str | None = Header(None, alias="X-SAHJONY-CRM-Signature"),
) -> dict[str, Any]:
    raw = await request.body()
    _verify_bridge_request(request, raw, *_headers(x_sahjony_timestamp, x_sahjony_nonce, x_sahjony_crm_signature))
    try:
        payload = CRMOutreachStatusIn.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid outreach status payload") from exc
    return await outreach_pilot_status(payload)


@router.post("/whatsapp/crm/intake")
async def crm_intake(
    request: Request,
    x_sahjony_timestamp: str | None = Header(None, alias="X-SAHJONY-Timestamp"),
    x_sahjony_nonce: str | None = Header(None, alias="X-SAHJONY-Nonce"),
    x_sahjony_crm_signature: str | None = Header(None, alias="X-SAHJONY-CRM-Signature"),
) -> dict[str, Any]:
    raw = await request.body()
    _verify_bridge_request(request, raw, *_headers(x_sahjony_timestamp, x_sahjony_nonce, x_sahjony_crm_signature))
    try:
        payload = CRMIntakeIn.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid CRM trade intake payload") from exc
    return await create_trade_intake(payload)
