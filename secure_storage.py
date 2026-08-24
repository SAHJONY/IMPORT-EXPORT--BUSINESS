from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

import boto3
from botocore.config import Config
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


_STORAGE_PROFILES = (
    {
        "provider": "insforge_s3",
        "endpoint": "INSFORGE_S3_ENDPOINT",
        "access_key": "INSFORGE_S3_ACCESS_KEY_ID",
        "secret_key": "INSFORGE_S3_SECRET_ACCESS_KEY",
        "bucket": "INSFORGE_STORAGE_BUCKET",
        "region": "INSFORGE_S3_REGION",
    },
    {
        "provider": "cloudflare_r2",
        "endpoint": "CLOUDFLARE_R2_ENDPOINT",
        "access_key": "CLOUDFLARE_R2_ACCESS_KEY_ID",
        "secret_key": "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
        "bucket": "CLOUDFLARE_R2_BUCKET",
        "region": "CLOUDFLARE_R2_REGION",
    },
    {
        "provider": "s3_compatible",
        "endpoint": "STORAGE_S3_ENDPOINT",
        "access_key": "STORAGE_S3_ACCESS_KEY_ID",
        "secret_key": "STORAGE_S3_SECRET_ACCESS_KEY",
        "bucket": "STORAGE_S3_BUCKET",
        "region": "STORAGE_S3_REGION",
    },
)


def _value(name: str) -> str:
    return os.getenv(name, "").strip()


def _selected_profile() -> dict | None:
    for profile in _STORAGE_PROFILES:
        if all(_value(profile[key]) for key in ("endpoint", "access_key", "secret_key", "bucket")):
            return profile
    return None


def storage_configuration_status() -> dict:
    selected = _selected_profile()
    partial_profiles: list[str] = []
    for profile in _STORAGE_PROFILES:
        values = [_value(profile[key]) for key in ("endpoint", "access_key", "secret_key", "bucket")]
        if any(values) and not all(values):
            partial_profiles.append(str(profile["provider"]))
    return {
        "configured": selected is not None,
        "provider": selected["provider"] if selected else None,
        "partial_profiles": partial_profiles,
        "signed_urls": True,
        "server_derived_keys": True,
        "raw_storage_credentials_exposed": False,
    }


def _profile() -> dict:
    selected = _selected_profile()
    if not selected:
        raise HTTPException(status_code=503, detail="Secure S3-compatible document storage is not configured")
    return selected


def policy() -> StoragePolicy:
    profile = _profile()
    return StoragePolicy(
        bucket=_value(profile["bucket"]),
        max_bytes=int(os.getenv("DOCUMENT_MAX_BYTES", str(25 * 1024 * 1024))),
        upload_ttl_seconds=int(os.getenv("DOCUMENT_UPLOAD_URL_TTL_SECONDS", "600")),
        download_ttl_seconds=int(os.getenv("DOCUMENT_DOWNLOAD_URL_TTL_SECONDS", "300")),
    )


def _client():
    profile = _profile()
    endpoint = _value(profile["endpoint"])
    access_key = _value(profile["access_key"])
    secret_key = _value(profile["secret_key"])
    region = _value(profile["region"]) or ("auto" if profile["provider"] == "cloudflare_r2" else "us-east-2")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
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


def create_upload_url(*, key: str, content_type: str, size_bytes: int) -> dict:
    p = policy()
    client = _client()
    url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": p.bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=p.upload_ttl_seconds,
    )
    return {
        "url": url,
        "method": "PUT",
        "headers": {"Content-Type": content_type},
        "expires_in": p.upload_ttl_seconds,
        "max_bytes": p.max_bytes,
        "expected_size": size_bytes,
    }


def create_download_url(*, key: str, download_name: str | None = None) -> dict:
    p = policy()
    params = {"Bucket": p.bucket, "Key": key}
    if download_name:
        params["ResponseContentDisposition"] = f'attachment; filename="{sanitize_filename(download_name)}"'
    url = _client().generate_presigned_url("get_object", Params=params, ExpiresIn=p.download_ttl_seconds)
    return {"url": url, "expires_in": p.download_ttl_seconds}


def verify_uploaded_object(*, key: str, expected_content_type: str, expected_size: int) -> dict:
    p = policy()
    try:
        head = _client().head_object(Bucket=p.bucket, Key=key)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Uploaded object could not be verified: {type(exc).__name__}") from exc
    size = int(head.get("ContentLength") or 0)
    content_type = str(head.get("ContentType") or "").split(";")[0].strip().lower()
    if size != expected_size:
        raise HTTPException(status_code=409, detail="Uploaded file size does not match declared size")
    if content_type != expected_content_type:
        raise HTTPException(status_code=409, detail="Uploaded MIME type does not match declared MIME type")
    etag = str(head.get("ETag") or "").strip('"') or None
    return {"size_bytes": size, "content_type": content_type, "etag": etag, "verified": True}


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
