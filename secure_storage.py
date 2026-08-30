from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from fastapi import HTTPException

SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/csv",
    "text/plain",
    "application/json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@dataclass(frozen=True)
class StoragePolicy:
    bucket: str
    max_bytes: int
    upload_ttl_seconds: int
    download_ttl_seconds: int


def _value(name: str) -> str:
    return os.getenv(name, "").strip()


def _supabase_url() -> str:
    return _value("SUPABASE_URL").rstrip("/")


def _supabase_key() -> str:
    return _value("SUPABASE_SERVICE_ROLE_KEY") or _value("SUPABASE_SECRET_KEY") or _value("SUPABASE_KEY")


def _storage_base() -> str:
    base = _supabase_url()
    return f"{base}/storage/v1" if base else ""


def _headers() -> dict[str, str]:
    key = _supabase_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def storage_configuration_status() -> dict:
    configured = bool(_supabase_url() and _supabase_key())
    return {
        "configured": configured,
        "provider": "supabase_storage" if configured else None,
        "bucket": _value("SUPABASE_STORAGE_BUCKET") or "trade-documents",
        "signed_urls": True,
        "server_derived_keys": True,
        "raw_storage_credentials_exposed": False,
        "canonical": "supabase",
    }


def _ensure_configured() -> None:
    if not _supabase_url() or not _supabase_key():
        raise HTTPException(status_code=503, detail="Supabase Storage is not configured")


def policy() -> StoragePolicy:
    _ensure_configured()
    return StoragePolicy(
        bucket=_value("SUPABASE_STORAGE_BUCKET") or "trade-documents",
        max_bytes=int(os.getenv("DOCUMENT_MAX_BYTES", str(25 * 1024 * 1024))),
        upload_ttl_seconds=int(os.getenv("DOCUMENT_UPLOAD_URL_TTL_SECONDS", "600")),
        download_ttl_seconds=int(os.getenv("DOCUMENT_DOWNLOAD_URL_TTL_SECONDS", "300")),
    )


def sanitize_filename(filename: str) -> str:
    base = filename.replace("\\", "/").split("/")[-1].strip()
    base = SAFE_SEGMENT.sub("_", base)[:180]
    if not base or base in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return base


def validate_file(filename: str, content_type: str, size_bytes: int) -> str:
    p = policy()
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=415, detail="File type is not allowed")
    if size_bytes <= 0 or size_bytes > p.max_bytes:
        raise HTTPException(status_code=413, detail=f"File must be between 1 byte and {p.max_bytes} bytes")
    return sanitize_filename(filename)


def object_key(*, trade_case_id: str, document_id: str, version: int, filename: str) -> str:
    case = SAFE_SEGMENT.sub("_", trade_case_id)[:160]
    doc = SAFE_SEGMENT.sub("_", document_id)[:160]
    name = sanitize_filename(filename)
    return f"trade-cases/{case}/documents/{doc}/v{version}/{name}"


def _encoded_object_path(bucket: str, key: str) -> str:
    safe_key = "/".join(quote(segment, safe="") for segment in key.split("/"))
    return f"{quote(bucket, safe='')}/{safe_key}"


def create_upload_url(*, key: str, content_type: str, size_bytes: int) -> dict:
    p = policy()
    path = _encoded_object_path(p.bucket, key)
    try:
        response = httpx.post(
            f"{_storage_base()}/object/upload/sign/{path}",
            headers=_headers(),
            json={"expiresIn": p.upload_ttl_seconds},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Supabase signed upload URL could not be created: {type(exc).__name__}") from exc

    relative = str(data.get("url") or data.get("signedURL") or data.get("signedUrl") or "")
    if not relative:
        raise HTTPException(status_code=503, detail="Supabase Storage did not return a signed upload URL")
    url = relative if relative.startswith("http") else f"{_storage_base()}{relative if relative.startswith('/') else '/' + relative}"
    return {
        "url": url,
        "method": "PUT",
        "headers": {"Content-Type": content_type},
        "expires_in": p.upload_ttl_seconds,
        "max_bytes": p.max_bytes,
        "expected_size": size_bytes,
        "provider": "supabase_storage",
        "token": data.get("token"),
    }


def create_download_url(*, key: str, download_name: str | None = None) -> dict:
    p = policy()
    path = _encoded_object_path(p.bucket, key)
    try:
        response = httpx.post(
            f"{_storage_base()}/object/sign/{path}",
            headers=_headers(),
            json={"expiresIn": p.download_ttl_seconds},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Supabase signed download URL could not be created: {type(exc).__name__}") from exc

    relative = str(data.get("signedURL") or data.get("signedUrl") or data.get("url") or "")
    if not relative:
        raise HTTPException(status_code=503, detail="Supabase Storage did not return a signed download URL")
    url = relative if relative.startswith("http") else f"{_storage_base()}{relative if relative.startswith('/') else '/' + relative}"
    if download_name:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}download={quote(sanitize_filename(download_name), safe='')}"
    return {"url": url, "expires_in": p.download_ttl_seconds, "provider": "supabase_storage"}


def verify_uploaded_object(*, key: str, expected_content_type: str, expected_size: int) -> dict:
    p = policy()
    path = _encoded_object_path(p.bucket, key)
    try:
        response = httpx.head(
            f"{_storage_base()}/object/{path}",
            headers={k: v for k, v in _headers().items() if k != "Content-Type"},
            timeout=15,
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Uploaded object could not be verified in Supabase Storage: {type(exc).__name__}") from exc

    size = int(response.headers.get("content-length") or 0)
    content_type = str(response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if size != expected_size:
        raise HTTPException(status_code=409, detail="Uploaded file size does not match declared size")
    if content_type and content_type != expected_content_type:
        raise HTTPException(status_code=409, detail="Uploaded MIME type does not match declared MIME type")
    etag = str(response.headers.get("etag") or "").strip('"') or None
    return {
        "size_bytes": size,
        "content_type": content_type or expected_content_type,
        "etag": etag,
        "verified": True,
        "provider": "supabase_storage",
    }


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
