from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_customer_token, verify_owner_token
from insforge_backend import get_backend
from secure_storage import create_download_url, create_upload_url, object_key, validate_file, verify_uploaded_object

app = FastAPI(title="SAHJONY Secure Document Storage", version="1.0.0", docs_url=None, redoc_url=None)
Role = Literal["owner", "employee", "customer"]


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=3, max_length=160)
    size_bytes: int = Field(gt=0)


class ScanResult(BaseModel):
    status: Literal["clean", "infected", "error"]
    provider: str = Field(min_length=2, max_length=120)
    reference: str | None = Field(default=None, max_length=300)
    detail: str | None = Field(default=None, max_length=2000)


class RetentionUpdate(BaseModel):
    retention_until: str | None = None
    legal_hold: bool | None = None


def now():
    return datetime.now(timezone.utc).isoformat()


def employee_token():
    token = os.getenv("EMPLOYEE_TOKEN", "").strip()
    if not token:
        raise HTTPException(503, "Employee storage access is not configured")
    return token


def identity(role, authorization, employee_id):
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
        raise HTTPException(403, "Verified customer identity required")
    return {"role": "customer", "id": str(customer["participant_id"])}


async def load_document(document_id: str, actor: dict):
    rows = await get_backend().select("trade_documents", params={"document_id": f"eq.{document_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(404, "Document not found")
    doc = rows[0]
    if actor["role"] == "customer" and (doc.get("customer_id") != actor["id"] or not doc.get("customer_visible")):
        raise HTTPException(403, "Document outside customer scope")
    return doc


async def storage_event(document_id, actor, event_type, doc, detail=None):
    row = {
        "storage_event_id": f"dse_{secrets.token_urlsafe(14)}",
        "document_id": document_id,
        "event_type": event_type,
        "actor_role": actor["role"],
        "actor_id": actor["id"],
        "object_key": doc.get("storage_object_key"),
        "content_type": doc.get("content_type"),
        "size_bytes": doc.get("size_bytes"),
        "object_etag": doc.get("object_etag"),
        "detail": detail,
        "created_at": now(),
    }
    await get_backend().insert("document_storage_events", row)
    return row


@app.get("/document-storage/health")
async def health():
    configured = all(os.getenv(x, "").strip() for x in ["INSFORGE_S3_ENDPOINT", "INSFORGE_S3_ACCESS_KEY_ID", "INSFORGE_S3_SECRET_ACCESS_KEY", "INSFORGE_STORAGE_BUCKET"])
    return {"status": "ok", "service": "secure-document-storage", "configured": configured, "signed_urls": True, "server_derived_keys": True, "raw_storage_credentials_exposed": False}


@app.post("/document-storage/{document_id}/upload")
async def authorize_upload(document_id: str, payload: UploadRequest, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    doc = await load_document(document_id, actor)
    if doc.get("status") in {"released", "archived"}:
        raise HTTPException(409, "Released/archived documents cannot be overwritten; create a new version")
    safe_name = validate_file(payload.filename, payload.content_type.lower(), payload.size_bytes)
    key = object_key(trade_case_id=doc["trade_case_id"], document_id=document_id, version=int(doc.get("version") or 1), filename=safe_name)
    values = {
        "original_filename": safe_name,
        "storage_object_key": key,
        "content_type": payload.content_type.lower(),
        "size_bytes": payload.size_bytes,
        "storage_status": "upload_authorized",
        "malware_scan_status": "not_started",
        "updated_at": now(),
    }
    await get_backend().patch("trade_documents", values, params={"document_id": f"eq.{document_id}"})
    doc.update(values)
    signed = create_upload_url(key=key, content_type=payload.content_type.lower(), size_bytes=payload.size_bytes)
    await storage_event(document_id, actor, "upload_authorized", doc, "Short-lived signed upload URL issued")
    return {"document_id": document_id, "object_key": key, "upload": signed}


@app.post("/document-storage/{document_id}/complete")
async def complete_upload(document_id: str, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    doc = await load_document(document_id, actor)
    if not doc.get("storage_object_key") or not doc.get("content_type") or not doc.get("size_bytes"):
        raise HTTPException(409, "Upload was not authorized")
    verified = verify_uploaded_object(key=doc["storage_object_key"], expected_content_type=doc["content_type"], expected_size=int(doc["size_bytes"]))
    scan_required = os.getenv("DOCUMENT_MALWARE_SCAN_REQUIRED", "true").strip().lower() == "true"
    values = {
        "object_etag": verified.get("etag"),
        "storage_status": "scan_pending" if scan_required else "clean",
        "malware_scan_status": "pending" if scan_required else "waived",
        "updated_at": now(),
    }
    await get_backend().patch("trade_documents", values, params={"document_id": f"eq.{document_id}"})
    doc.update(values)
    await storage_event(document_id, actor, "upload_verified", doc, "Object size and MIME verified against declaration")
    if scan_required:
        await storage_event(document_id, {"role": "system", "id": "storage"}, "scan_requested", doc, "Awaiting configured malware scanning pipeline")
    return {"document_id": document_id, "verified": verified, "malware_scan_required": scan_required, "storage_status": values["storage_status"]}


@app.get("/document-storage/{document_id}/download")
async def authorize_download(document_id: str, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    doc = await load_document(document_id, actor)
    if doc.get("storage_status") != "clean" or doc.get("malware_scan_status") not in {"clean", "waived"}:
        raise HTTPException(423, "Document is not cleared for download")
    if not doc.get("storage_object_key"):
        raise HTTPException(404, "Document file is not available")
    signed = create_download_url(key=doc["storage_object_key"], download_name=doc.get("original_filename") or doc.get("title"))
    await storage_event(document_id, actor, "download_authorized", doc, "Short-lived signed download URL issued")
    return {"document_id": document_id, "download": signed}


@app.post("/document-storage/{document_id}/scan-result")
async def scan_result(document_id: str, payload: ScanResult, x_scan_secret: str | None = Header(None, alias="X-Scan-Secret")):
    expected = os.getenv("MALWARE_SCAN_CALLBACK_SECRET", "").strip()
    if not expected or not x_scan_secret or not secrets.compare_digest(x_scan_secret, expected):
        raise HTTPException(403, "Invalid scan callback credential")
    rows = await get_backend().select("trade_documents", params={"document_id": f"eq.{document_id}", "limit": "1"}) or []
    if not rows:
        raise HTTPException(404, "Document not found")
    doc = rows[0]
    storage_status = "clean" if payload.status == "clean" else "quarantined" if payload.status == "infected" else "scan_pending"
    values = {"malware_scan_status": payload.status, "malware_scan_provider": payload.provider, "malware_scan_reference": payload.reference, "storage_status": storage_status, "updated_at": now()}
    await get_backend().patch("trade_documents", values, params={"document_id": f"eq.{document_id}"})
    doc.update(values)
    await storage_event(document_id, {"role": "system", "id": payload.provider}, "scan_result", doc, payload.detail)
    if payload.status == "infected":
        await storage_event(document_id, {"role": "system", "id": payload.provider}, "quarantined", doc, "Malware scan detected unsafe content")
    return {"document_id": document_id, "storage_status": storage_status, "malware_scan_status": payload.status}


@app.patch("/document-storage/{document_id}/retention")
async def retention(document_id: str, payload: RetentionUpdate, x_role: str | None = Header(None, alias="X-Role"), authorization: str | None = Header(None, alias="Authorization"), x_employee_id: str | None = Header(None, alias="X-Employee-Id")):
    actor = identity(x_role, authorization, x_employee_id)
    if actor["role"] != "owner":
        raise HTTPException(403, "Only owner may change retention/legal hold")
    doc = await load_document(document_id, actor)
    values = {"updated_at": now()}
    if payload.retention_until is not None:
        values["retention_until"] = payload.retention_until
    if payload.legal_hold is not None:
        values["legal_hold"] = payload.legal_hold
    await get_backend().patch("trade_documents", values, params={"document_id": f"eq.{document_id}"})
    doc.update(values)
    await storage_event(document_id, actor, "legal_hold_changed" if payload.legal_hold is not None else "retention_changed", doc, "Owner governance update")
    return {"document_id": document_id, "retention_until": doc.get("retention_until"), "legal_hold": doc.get("legal_hold")}
