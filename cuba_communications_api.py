from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field

from auth import verify_owner_token
from insforge_backend import get_backend, persistent_backend_status
from voice_agent_api import _openai_key, _reasoning_model, _realtime_model, _realtime_voice

app = FastAPI(title="SAHJONY Cuba Communications Department", version="1.1.0", docs_url=None, redoc_url=None)

PreferredContact = Literal["direct_text", "whatsapp", "email", "phone", "none"]
RequestStatus = Literal["RECEIVED", "REVIEWING", "WAITING_CUSTOMER", "ELIGIBLE", "NOT_AVAILABLE", "CLOSED"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


def _communications_ready() -> bool:
    return bool(persistent_backend_status().get("configured") and _openai_key())


class CubaCommunicationsRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=80)
    email: EmailStr | None = None
    province: str | None = Field(default=None, max_length=120)
    municipality: str | None = Field(default=None, max_length=120)
    service_address: str | None = Field(default=None, max_length=500)
    preferred_contact: PreferredContact = "direct_text"
    wants_communication_os: bool = True
    wants_free_internet: bool = False
    wants_starlink: bool = False
    has_existing_starlink: bool = False
    household_or_personal_use: bool = True
    notes: str | None = Field(default=None, max_length=3000)
    consent_to_contact: bool = True
    website: str | None = Field(default=None, max_length=200)


class OwnerStatusUpdate(BaseModel):
    status: RequestStatus
    communication_os_status: str | None = Field(default=None, max_length=120)
    free_internet_status: str | None = Field(default=None, max_length=160)
    starlink_status: str | None = Field(default=None, max_length=160)
    owner_note: str | None = Field(default=None, max_length=3000)


@app.get("/cuba-communications/health")
async def health() -> dict[str, Any]:
    persistence = persistent_backend_status()
    return {
        "status": "ok" if persistence.get("configured") else "configuration_required",
        "service": "sahjony-cuba-communications-department",
        "version": "1.1.0",
        "language": "es",
        "audience": "personas_y_clientes_en_cuba",
        "communication_os": {
            "available_over_supported_internet": _communications_ready(),
            "direct_text": True,
            "internet_voice": True,
            "video": True,
            "screen_share": True,
            "notifications": True,
            "offline_queue": True,
            "reasoning_model": _reasoning_model(),
            "realtime_model": _realtime_model(),
            "realtime_voice": _realtime_voice(),
        },
        "free_internet": {
            "optional": True,
            "free_to_end_user": True,
            "sponsor_or_program_funded": True,
            "requires_active_program": True,
            "requires_verified_backhaul": True,
            "requires_provider_terms_allow_sharing": True,
            "not_guaranteed_by_request": True,
            "local_wifi_without_internet_supported": True,
        },
        "starlink": {
            "optional": True,
            "included": False,
            "sahjony_is_starlink_reseller": False,
            "customer_pays_provider_directly": True,
            "availability_must_be_verified_with_starlink": True,
            "activation_must_be_authorized_by_provider_and_applicable_law": True,
            "official_availability_url": "https://starlink.com/map",
            "status_policy": "NEVER_CLAIM_AVAILABLE_UNTIL_PROVIDER_CONFIRMS_ADDRESS_AND_ACTIVATION",
        },
        "compliance": {
            "telecommunications_and_internet_services_subject_to_applicable_us_cuba_rules": True,
            "no_sanctions_evasion": True,
            "no_provider_activation_bypass": True,
            "no_unverified_free_internet_promise": True,
            "fail_closed": True,
        },
        "persistence": persistence,
    }


@app.post("/cuba-communications/requests")
async def create_request(payload: CubaCommunicationsRequest):
    if payload.website:
        raise HTTPException(400, "Invalid submission")
    if not payload.consent_to_contact:
        raise HTTPException(422, "Debes autorizar el contacto para registrar la solicitud")
    if not payload.wants_communication_os and not payload.wants_free_internet and not payload.wants_starlink:
        raise HTTPException(422, "Selecciona al menos un servicio")
    if not persistent_backend_status().get("configured"):
        raise HTTPException(503, "El registro de solicitudes no está disponible temporalmente")

    request_id = f"cubacomm_{secrets.token_urlsafe(12)}"
    status_token = secrets.token_urlsafe(24)
    ts = _now()
    row = {
        "request_id": request_id,
        "status_token": status_token,
        "status": "RECEIVED",
        "full_name": payload.full_name,
        "phone": payload.phone,
        "email": str(payload.email) if payload.email else None,
        "province": payload.province,
        "municipality": payload.municipality,
        "service_address": payload.service_address,
        "preferred_contact": payload.preferred_contact,
        "wants_communication_os": payload.wants_communication_os,
        "wants_free_internet": payload.wants_free_internet,
        "wants_starlink": payload.wants_starlink,
        "has_existing_starlink": payload.has_existing_starlink,
        "household_or_personal_use": payload.household_or_personal_use,
        "notes": payload.notes,
        "communication_os_status": "ELIGIBILITY_REVIEW" if payload.wants_communication_os else "NOT_REQUESTED",
        "free_internet_status": "PROGRAM_AVAILABILITY_REVIEW" if payload.wants_free_internet else "NOT_REQUESTED",
        "free_internet_is_sponsor_or_program_funded": True,
        "free_internet_guaranteed": False,
        "starlink_status": "AVAILABILITY_CHECK_REQUIRED" if payload.wants_starlink else "NOT_REQUESTED",
        "starlink_customer_pays_provider_directly": True,
        "starlink_provider_activation_required": True,
        "starlink_availability_confirmed": False,
        "sahjony_starlink_reseller": False,
        "consent_to_contact": True,
        "created_at": ts,
        "updated_at": ts,
    }
    await get_backend().insert("cuba_communications_requests", row)
    return {
        "status": "RECEIVED",
        "request_id": request_id,
        "status_token": status_token,
        "communication_os_status": row["communication_os_status"],
        "free_internet_status": row["free_internet_status"],
        "starlink_status": row["starlink_status"],
        "free_internet_note": "El acceso puede ser gratis para el usuario final cuando exista un programa financiado, backhaul verificado y términos del proveedor que permitan compartirlo.",
        "starlink_note": "La disponibilidad y activación de Starlink deben confirmarse directamente con Starlink para la dirección y cuenta aplicables.",
    }


@app.get("/cuba-communications/requests/{request_id}/status")
async def request_status(request_id: str, x_request_token: str | None = Header(None, alias="X-Request-Token")):
    rows = await get_backend().select("cuba_communications_requests", params={"request_id": f"eq.{request_id}", "limit": "1"})
    if not rows:
        raise HTTPException(404, "Solicitud no encontrada")
    row = rows[0]
    if not x_request_token or not secrets.compare_digest(str(row.get("status_token") or ""), x_request_token):
        raise HTTPException(403, "Token privado inválido")
    return {
        "request_id": request_id,
        "status": row.get("status"),
        "communication_os_status": row.get("communication_os_status"),
        "free_internet_status": row.get("free_internet_status"),
        "starlink_status": row.get("starlink_status"),
        "wants_communication_os": row.get("wants_communication_os"),
        "wants_free_internet": row.get("wants_free_internet"),
        "wants_starlink": row.get("wants_starlink"),
        "starlink_availability_confirmed": bool(row.get("starlink_availability_confirmed")),
        "updated_at": row.get("updated_at"),
    }


@app.get("/cuba-communications/owner/requests")
async def owner_requests(authorization: str | None = Header(None, alias="Authorization"), limit: int = 200):
    _owner(authorization)
    rows = await get_backend().select("cuba_communications_requests", params={"order": "updated_at.desc", "limit": str(max(1, min(limit, 500)))})
    return {"status": "ok", "count": len(rows or []), "requests": rows or []}


@app.post("/cuba-communications/owner/requests/{request_id}/status")
async def owner_update(request_id: str, payload: OwnerStatusUpdate, authorization: str | None = Header(None, alias="Authorization")):
    _owner(authorization)
    values: dict[str, Any] = {"status": payload.status, "updated_at": _now()}
    if payload.communication_os_status is not None:
        values["communication_os_status"] = payload.communication_os_status
    if payload.free_internet_status is not None:
        values["free_internet_status"] = payload.free_internet_status
        values["free_internet_guaranteed"] = payload.free_internet_status.upper() in {"ACTIVE_PASS_ISSUED", "ACTIVE_PROGRAM_CONFIRMED"}
    if payload.starlink_status is not None:
        values["starlink_status"] = payload.starlink_status
        values["starlink_availability_confirmed"] = payload.starlink_status.upper() in {"PROVIDER_CONFIRMED", "AVAILABLE_CONFIRMED"}
    if payload.owner_note is not None:
        values["owner_note"] = payload.owner_note
    updated = await get_backend().patch("cuba_communications_requests", values, params={"request_id": f"eq.{request_id}"})
    if not updated:
        raise HTTPException(404, "Solicitud no encontrada")
    return {"status": "updated", "request_id": request_id, "record": updated[0]}
