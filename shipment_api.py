from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field

from auth import verify_customer_token, verify_owner_token
from credentialed_providers import ProviderConfigurationError, maersk_provider
from insforge_backend import InsForgeConfigurationError, get_backend, persistent_backend_status

app = FastAPI(title="SAHJONY Global Trade Shipments", version="1.1.0", docs_url=None, redoc_url=None)

Role = Literal["owner", "employee", "customer"]
Mode = Literal["ocean", "air", "ground", "lcl", "parcel", "multimodal"]


class ShipmentCreate(BaseModel):
    trade_case_id: str = Field(min_length=1, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    transport_mode: Mode
    provider: str = Field(default="maersk", min_length=2, max_length=80)
    tracking_reference: str = Field(min_length=4, max_length=120)
    booking_reference: str | None = Field(default=None, max_length=120)
    container_number: str | None = Field(default=None, max_length=120)
    bill_of_lading: str | None = Field(default=None, max_length=120)
    air_waybill: str | None = Field(default=None, max_length=120)
    origin_name: str | None = Field(default=None, max_length=240)
    origin_code: str | None = Field(default=None, max_length=40)
    destination_name: str | None = Field(default=None, max_length=240)
    destination_code: str | None = Field(default=None, max_length=40)
    customer_visible: bool = True


class PackageCreate(BaseModel):
    customer_id: str | None = Field(default=None, max_length=160)
    quantity: int = Field(default=1, ge=1, le=100)
    origin_name: str | None = Field(default=None, max_length=240)
    destination_name: str | None = Field(default=None, max_length=240)
    customer_visible: bool = True


class PackageScanIn(BaseModel):
    stage: str = Field(min_length=2, max_length=100)
    event_label: str = Field(min_length=2, max_length=300)
    location_name: str | None = Field(default=None, max_length=240)
    location_code: str | None = Field(default=None, max_length=80)
    customer_visible: bool = True


def _tracking_secret() -> bytes:
    value = (os.getenv("TRACKING_SIGNING_SECRET") or os.getenv("OWNER_SESSION_SECRET") or "").strip()
    if not value:
        raise HTTPException(503, "Tracking signing secret is not configured")
    return value.encode()


def _b64(v: bytes) -> str:
    return base64.urlsafe_b64encode(v).decode().rstrip("=")


def public_tracking_token(shipment_id: str) -> str:
    payload = shipment_id.encode()
    sig = hmac.new(_tracking_secret(), payload, hashlib.sha256).digest()[:18]
    return _b64(payload) + "." + _b64(sig)


def shipment_id_from_token(token: str) -> str:
    try:
        encoded, signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        expected = hmac.new(_tracking_secret(), payload, hashlib.sha256).digest()[:18]
        received = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if not hmac.compare_digest(expected, received):
            raise ValueError("bad signature")
        shipment_id = payload.decode()
        if not shipment_id.startswith("shp_"):
            raise ValueError("bad shipment id")
        return shipment_id
    except Exception as exc:
        raise HTTPException(404, "Tracking code not found") from exc


def tracking_url(token: str) -> str:
    base = (os.getenv("PUBLIC_APP_URL") or "https://www.sahjony.com").rstrip("/")
    return f"{base}/track/{token}"


class MilestoneIn(BaseModel):
    stage: str = Field(min_length=2, max_length=100)
    event_code: str | None = Field(default=None, max_length=100)
    event_label: str = Field(min_length=2, max_length=300)
    status: Literal["planned", "estimated", "confirmed", "exception", "cancelled"] = "confirmed"
    location_name: str | None = Field(default=None, max_length=240)
    location_code: str | None = Field(default=None, max_length=80)
    terminal: str | None = Field(default=None, max_length=240)
    event_time: str | None = None
    event_time_type: str | None = Field(default=None, max_length=80)
    source: str = Field(default="manual", max_length=80)
    customer_visible: bool = True
    exception_detail: str | None = Field(default=None, max_length=2000)


class ShipmentPatch(BaseModel):
    current_stage: str | None = Field(default=None, max_length=100)
    current_status: str | None = Field(default=None, max_length=100)
    current_location: str | None = Field(default=None, max_length=240)
    estimated_delivery_at: str | None = None
    actual_delivery_at: str | None = None
    exception_code: str | None = Field(default=None, max_length=100)
    exception_detail: str | None = Field(default=None, max_length=2000)
    customer_visible: bool | None = None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def employee_token() -> str:
    token = os.getenv("EMPLOYEE_TOKEN")
    if not token:
        raise HTTPException(503, "Employee shipment workflow is not configured")
    return token


def identity(role: str | None, authorization: str | None, employee_id: str | None) -> dict[str, str]:
    if role not in {"owner", "employee", "customer"}:
        raise HTTPException(400, "Invalid X-Role")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if role == "owner":
        if not verify_owner_token(token):
            raise HTTPException(403, "Invalid owner credential")
        return {"role": "owner", "id": "owner"}
    if role == "employee":
        if not secrets.compare_digest(token, employee_token()):
            raise HTTPException(403, "Invalid employee credential")
        return {"role": "employee", "id": (employee_id or "staff")[:160]}
    customer = verify_customer_token(token)
    if not customer:
        raise HTTPException(403, "Invalid customer credential")
    return {"role": "customer", "id": str(customer["participant_id"])}


async def publish_event(*, shipment: dict[str, Any], event_type: str, title: str, body: str | None, customer_visible: bool, action_required: bool = False, severity: str = "info") -> None:
    row = {
        "event_id": f"evt_{secrets.token_urlsafe(16)}",
        "trade_case_id": shipment.get("trade_case_id"),
        "customer_id": shipment.get("customer_id"),
        "event_type": event_type,
        "title": title,
        "body": body,
        "source_type": "shipment",
        "source_id": shipment.get("shipment_id"),
        "actor_role": "system",
        "actor_id": shipment.get("provider") or "tracking-provider",
        "severity": severity,
        "action_required": action_required,
        "customer_visible": customer_visible,
        "created_at": now(),
    }
    try:
        await get_backend().insert("business_events", row)
        if customer_visible and shipment.get("customer_id"):
            await get_backend().insert("outbound_notifications", {
                "notification_id": f"ntf_{secrets.token_urlsafe(16)}",
                "event_id": row["event_id"],
                "customer_id": shipment.get("customer_id"),
                "channel": "portal",
                "destination": shipment.get("customer_id"),
                "status": "queued",
                "attempt_count": 0,
                "created_at": now(),
                "updated_at": now(),
            })
    except Exception:
        # Tracking state is authoritative; communication fan-out must not block persistence.
        pass


async def get_shipment_or_404(shipment_id: str, actor: dict[str, str]) -> dict[str, Any]:
    rows = await get_backend().select("shipments", params={"shipment_id": f"eq.{shipment_id}", "limit": "1"})
    if not rows:
        raise HTTPException(404, "Shipment not found")
    shipment = rows[0]
    if actor["role"] == "customer":
        if shipment.get("customer_id") != actor["id"] or not shipment.get("customer_visible"):
            raise HTTPException(403, "Customer shipment scope mismatch")
    return shipment


@app.get("/shipments/health")
async def health() -> dict[str, Any]:
    persistence = persistent_backend_status()
    return {
        "status": "ok",
        "service": "end-to-end-shipment-tracking",
        "persistence_configured": persistence["configured"],
        "persistence_provider": persistence["provider"],
        "database_url_configured": persistence["database_url_configured"],
        "insforge_configured": persistence["insforge_configured"],
        "maersk_configured": maersk_provider.configured,
        "provider_path_configured": bool(os.getenv("MAERSK_TRACKING_PATH_TEMPLATE")),
        "modes": ["ocean", "air", "ground", "lcl", "parcel", "multimodal"],
        "package_tracking_qr": True,
        "public_tracking_tokens": True,
        "chain_of_custody_scans": True,
    }


@app.post("/shipments")
async def create_shipment(payload: ShipmentCreate, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    customer_id = actor["id"] if actor["role"] == "customer" else payload.customer_id
    if actor["role"] == "customer" and not customer_id:
        raise HTTPException(403, "Customer scope required")
    shipment_id = f"shp_{secrets.token_urlsafe(16)}"
    ts = now()
    row = {
        "shipment_id": shipment_id,
        "trade_case_id": payload.trade_case_id,
        "customer_id": customer_id,
        "transport_mode": payload.transport_mode,
        "provider": payload.provider.lower(),
        "tracking_reference": payload.tracking_reference.strip(),
        "booking_reference": payload.booking_reference,
        "container_number": payload.container_number,
        "bill_of_lading": payload.bill_of_lading,
        "air_waybill": payload.air_waybill,
        "origin_name": payload.origin_name,
        "origin_code": payload.origin_code,
        "destination_name": payload.destination_name,
        "destination_code": payload.destination_code,
        "current_stage": "booked",
        "current_status": "pending",
        "delay_minutes": 0,
        "customer_visible": True if actor["role"] == "customer" else payload.customer_visible,
        "created_by_role": actor["role"],
        "created_by_id": actor["id"],
        "created_at": ts,
        "updated_at": ts,
    }
    try:
        result = await get_backend().insert("shipments", row)
    except InsForgeConfigurationError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, f"Shipment persistence unavailable: {type(exc).__name__}") from exc
    await publish_event(shipment=row, event_type="shipment_created", title=f"Shipment tracking started · {payload.tracking_reference}", body=f"{payload.transport_mode.upper()} shipment linked to case {payload.trade_case_id}.", customer_visible=row["customer_visible"])
    return {"shipment": row, "persistence": result}


@app.get("/shipments")
async def list_shipments(trade_case_id: str | None = Query(default=None, max_length=160), customer_id: str | None = Query(default=None, max_length=160), x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    params: dict[str, str] = {"order": "updated_at.desc", "limit": "250"}
    if trade_case_id:
        params["trade_case_id"] = f"eq.{trade_case_id}"
    if actor["role"] == "customer":
        params["customer_id"] = f"eq.{actor['id']}"
        params["customer_visible"] = "eq.true"
    elif customer_id:
        params["customer_id"] = f"eq.{customer_id}"
    try:
        rows = await get_backend().select("shipments", params=params)
    except Exception as exc:
        raise HTTPException(503, f"Shipment persistence unavailable: {type(exc).__name__}") from exc
    return {"shipments": rows or [], "actor": actor}


@app.get("/shipments/{shipment_id}")
async def get_shipment(shipment_id: str, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    shipment = await get_shipment_or_404(shipment_id, actor)
    params = {"shipment_id": f"eq.{shipment_id}", "order": "event_time.asc,created_at.asc", "limit": "500"}
    if actor["role"] == "customer":
        params["customer_visible"] = "eq.true"
    milestones = await get_backend().select("shipment_milestones", params=params)
    return {"shipment": shipment, "milestones": milestones or []}


@app.post("/shipments/{shipment_id}/milestones")
async def add_milestone(shipment_id: str, payload: MilestoneIn, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    if actor["role"] == "customer":
        raise HTTPException(403, "Customers cannot create operational shipment milestones")
    shipment = await get_shipment_or_404(shipment_id, actor)
    ts = now()
    milestone = {
        "milestone_id": f"mls_{secrets.token_urlsafe(16)}",
        "shipment_id": shipment_id,
        "stage": payload.stage,
        "event_code": payload.event_code,
        "event_label": payload.event_label,
        "status": payload.status,
        "location_name": payload.location_name,
        "location_code": payload.location_code,
        "terminal": payload.terminal,
        "transport_mode": shipment.get("transport_mode"),
        "event_time": payload.event_time,
        "event_time_type": payload.event_time_type,
        "source": payload.source,
        "customer_visible": payload.customer_visible,
        "created_at": ts,
    }
    await get_backend().insert("shipment_milestones", milestone)
    patch = {
        "current_stage": payload.stage,
        "current_status": "exception" if payload.status == "exception" else "in_transit",
        "current_location": payload.location_name,
        "last_event_at": payload.event_time or ts,
        "updated_at": ts,
    }
    if payload.status == "exception":
        patch["exception_code"] = payload.event_code or "shipment_exception"
        patch["exception_detail"] = payload.exception_detail or payload.event_label
    await get_backend().patch("shipments", patch, params={"shipment_id": f"eq.{shipment_id}"})
    shipment.update(patch)
    await publish_event(shipment=shipment, event_type="shipment_exception" if payload.status == "exception" else "shipment_milestone", title=payload.event_label, body=payload.exception_detail or payload.location_name, customer_visible=payload.customer_visible and shipment.get("customer_visible", False), action_required=payload.status == "exception", severity="urgent" if payload.status == "exception" else "info")
    return {"milestone": milestone, "shipment": shipment}


@app.patch("/shipments/{shipment_id}")
async def patch_shipment(shipment_id: str, payload: ShipmentPatch, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    if actor["role"] == "customer":
        raise HTTPException(403, "Customers cannot alter operational shipment state")
    shipment = await get_shipment_or_404(shipment_id, actor)
    values = {k: v for k, v in payload.model_dump().items() if v is not None}
    if values.get("actual_delivery_at"):
        if shipment.get("exception_code"):
            raise HTTPException(409, "Shipment delivery cannot be confirmed while an exception is unresolved")
        values["current_stage"] = "delivered"
        values["current_status"] = "delivered"
    values["updated_at"] = now()
    result = await get_backend().patch("shipments", values, params={"shipment_id": f"eq.{shipment_id}"})
    shipment.update(values)
    return {"shipment": shipment, "persistence": result}


@app.post("/shipments/{shipment_id}/sync")
async def sync_shipment(shipment_id: str, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    if actor["role"] == "customer":
        raise HTTPException(403, "Customers cannot trigger provider synchronization")
    shipment = await get_shipment_or_404(shipment_id, actor)
    if shipment.get("provider") != "maersk":
        raise HTTPException(409, "Automatic sync is currently configured only for the Maersk provider adapter")
    template = os.getenv("MAERSK_TRACKING_PATH_TEMPLATE", "").strip()
    if not template:
        raise HTTPException(503, "MAERSK_TRACKING_PATH_TEMPLATE is not configured; provider sync is fail-closed")
    if "{tracking_reference}" not in template:
        raise HTTPException(503, "MAERSK_TRACKING_PATH_TEMPLATE must include {tracking_reference}")
    try:
        response = await maersk_provider.request("GET", template.format(tracking_reference=shipment["tracking_reference"]))
        payload: Any = response.json()
    except (ProviderConfigurationError, Exception) as exc:
        sync = {"sync_id": f"syn_{secrets.token_urlsafe(16)}", "shipment_id": shipment_id, "provider": "maersk", "sync_status": "error", "new_milestones": 0, "eta_changed": False, "exception_detected": False, "detail": type(exc).__name__, "synced_at": now()}
        try:
            await get_backend().insert("shipment_sync_events", sync)
        except Exception:
            pass
        raise HTTPException(503, f"Maersk synchronization unavailable: {type(exc).__name__}") from exc

    sync_time = now()
    sync = {"sync_id": f"syn_{secrets.token_urlsafe(16)}", "shipment_id": shipment_id, "provider": "maersk", "sync_status": "success", "new_milestones": 0, "eta_changed": False, "exception_detected": False, "detail": "Provider payload captured; normalization adapter may be extended per contracted API response schema.", "synced_at": sync_time}
    await get_backend().insert("shipment_sync_events", sync)
    await get_backend().patch("shipments", {"last_provider_sync_at": sync_time, "updated_at": sync_time}, params={"shipment_id": f"eq.{shipment_id}"})
    return {"shipment_id": shipment_id, "sync": sync, "provider_payload": payload}


@app.post("/shipments/{shipment_id}/packages")
async def create_packages(shipment_id: str, payload: PackageCreate, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    if actor["role"] == "customer":
        raise HTTPException(403, "Customers cannot create package custody records")
    parent = await get_shipment_or_404(shipment_id, actor)
    ts = now()
    packages = []
    for index in range(1, payload.quantity + 1):
        package_id = f"shp_{secrets.token_urlsafe(16)}"
        ref = "SJ-" + secrets.token_hex(6).upper()
        row = {
            "shipment_id": package_id, "trade_case_id": parent["trade_case_id"],
            "customer_id": payload.customer_id or parent.get("customer_id"),
            "transport_mode": "parcel", "provider": "sahjony", "tracking_reference": ref,
            "booking_reference": f"PARENT:{shipment_id}", "container_number": parent.get("container_number"),
            "bill_of_lading": parent.get("bill_of_lading"), "air_waybill": parent.get("air_waybill"),
            "origin_name": payload.origin_name or parent.get("origin_name"),
            "origin_code": parent.get("origin_code"),
            "destination_name": payload.destination_name or parent.get("destination_name"),
            "destination_code": parent.get("destination_code"),
            "current_stage": "package_created", "current_status": "pending", "delay_minutes": 0,
            "customer_visible": payload.customer_visible, "created_by_role": actor["role"],
            "created_by_id": actor["id"], "created_at": ts, "updated_at": ts,
        }
        await get_backend().insert("shipments", row)
        token = public_tracking_token(package_id)
        packages.append({
            "package_no": index, "shipment_id": package_id, "tracking_reference": ref,
            "tracking_token": token, "tracking_url": tracking_url(token),
            "qr_url": f"/tracking/qr/{token}",
        })
    return {"parent_shipment_id": shipment_id, "package_count": len(packages), "packages": packages}


@app.get("/tracking/public/{token}")
async def public_tracking(token: str):
    shipment_id = shipment_id_from_token(token)
    rows = await get_backend().select("shipments", params={"shipment_id": f"eq.{shipment_id}", "customer_visible": "eq.true", "limit": "1"})
    if not rows:
        raise HTTPException(404, "Tracking code not found")
    shipment = rows[0]
    milestones = await get_backend().select("shipment_milestones", params={"shipment_id": f"eq.{shipment_id}", "customer_visible": "eq.true", "order": "event_time.asc,created_at.asc", "limit": "500"}) or []
    safe = {k: shipment.get(k) for k in ("tracking_reference","transport_mode","origin_name","destination_name","current_stage","current_status","current_location","estimated_delivery_at","actual_delivery_at","last_event_at","updated_at")}
    return {"shipment": safe, "milestones": milestones, "tracking_url": tracking_url(token)}


@app.get("/tracking/qr/{token}")
async def tracking_qr(token: str):
    shipment_id_from_token(token)
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(tracking_url(token), image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(content=buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=300"})


@app.post("/tracking/scan/{token}")
async def scan_package(token: str, payload: PackageScanIn, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    if actor["role"] == "customer":
        raise HTTPException(403, "Customers cannot create custody scans")
    shipment_id = shipment_id_from_token(token)
    shipment = await get_shipment_or_404(shipment_id, actor)
    ts = now()
    milestone = {
        "milestone_id": f"mls_{secrets.token_urlsafe(16)}", "shipment_id": shipment_id,
        "stage": payload.stage, "event_code": "QR_SCAN", "event_label": payload.event_label,
        "status": "confirmed", "location_name": payload.location_name, "location_code": payload.location_code,
        "terminal": None, "transport_mode": shipment.get("transport_mode"), "event_time": ts,
        "event_time_type": "actual", "source": f"qr_scan:{actor['role']}:{actor['id']}",
        "customer_visible": payload.customer_visible, "created_at": ts,
    }
    await get_backend().insert("shipment_milestones", milestone)
    patch = {"current_stage": payload.stage, "current_status": "in_transit", "current_location": payload.location_name, "last_event_at": ts, "updated_at": ts}
    await get_backend().patch("shipments", patch, params={"shipment_id": f"eq.{shipment_id}"})
    return {"status": "recorded", "tracking_reference": shipment.get("tracking_reference"), "milestone": milestone}
