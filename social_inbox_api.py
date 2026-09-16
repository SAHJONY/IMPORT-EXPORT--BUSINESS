"""SAHJONY Social Inbox API — owner view + ingest endpoint for social items.

Items are collected by the `facebook_ingest.py` scheduled job (which runs where
Juan's Facebook session lives but has no database credentials) and delivered
here by the owner's authenticated browser session. This module upserts them
into the `sahjony_trade_records` logical table `social_inbox_items` and exposes
them to the owner CRM hub. No Facebook mutations anywhere in this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(
    title="SAHJONY Social Inbox",
    version="1.1.0",
    docs_url=None,
    redoc_url=None,
)

TABLE = "social_inbox_items"
MAX_INGEST_ITEMS = 500
TEXT_LIMIT = 2000

# Fields the ingest endpoint accepts per item; anything else is dropped.
ITEM_FIELDS = (
    "platform", "external_id", "permalink", "author_name", "created_at",
    "text", "item_type", "source", "parent_external_id", "synced_at",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auth_owner(x_role: str | None, authorization: str | None) -> None:
    if x_role != "owner":
        raise HTTPException(403, "Owner role required")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(403, "Invalid owner credential")


@app.get("/crm/social-inbox/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "social_inbox",
        "table": TABLE,
        "writes": "facebook_ingest.py job only",
        "facebook_mutations": False,
    }


@app.get("/crm/social-inbox/items")
async def items(
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    limit: int = Query(100, ge=1, le=500),
    source: str | None = Query(None),
) -> dict[str, Any]:
    _auth_owner(x_role, authorization)
    params: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
    if source:
        params["source"] = f"eq.{source}"
    rows = await get_backend().select(TABLE, params=params)
    items_out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        items_out.append({
            "external_id": r.get("external_id", ""),
            "platform": r.get("platform", "facebook"),
            "source": r.get("source", ""),
            "item_type": r.get("item_type", ""),
            "permalink": r.get("permalink", ""),
            "author_name": r.get("author_name", ""),
            "created_at": r.get("created_at", ""),
            "text": r.get("text", ""),
            "parent_external_id": r.get("parent_external_id", ""),
            "synced_at": r.get("synced_at", ""),
        })
    return {"status": "ok", "count": len(items_out), "items": items_out, "read_at": _now_iso()}


def _clean_item(raw: Any) -> dict[str, Any] | None:
    """Validate + sanitize one ingested item. Returns None if unusable."""
    if not isinstance(raw, dict):
        return None
    external_id = str(raw.get("external_id") or "").strip()
    if not external_id or len(external_id) > 200:
        return None
    source = str(raw.get("source") or "").strip()
    if source not in ("page", "profile", "group", "messenger"):
        return None
    item_type = str(raw.get("item_type") or "").strip()
    if item_type not in ("post", "comment", "message"):
        return None
    cleaned: dict[str, Any] = {}
    for field in ITEM_FIELDS:
        value = raw.get(field)
        if value is None:
            cleaned[field] = ""
        elif field == "text" and isinstance(value, str):
            cleaned[field] = value[:TEXT_LIMIT]
        elif isinstance(value, str):
            cleaned[field] = value[:500]
        else:
            cleaned[field] = value
    cleaned["external_id"] = external_id
    cleaned["source"] = source
    cleaned["item_type"] = item_type
    if not cleaned.get("platform"):
        cleaned["platform"] = "facebook"
    if not cleaned.get("synced_at"):
        cleaned["synced_at"] = _now_iso()
    return cleaned


@app.post("/crm/social-inbox/ingest")
async def ingest(
    request: Request,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    """Owner-authenticated upsert of normalized social items.

    Body: {"items": [...]} or a raw JSON array. Dedupe is on
    `external_id` via the backend's (logical_table, record_key) upsert,
    so re-delivery never duplicates. This endpoint never touches Facebook.
    """
    _auth_owner(x_role, authorization)
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(400, "Body must be JSON")
    raw_items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        raise HTTPException(400, "Body must be {\"items\": [...]} or a JSON array")
    if len(raw_items) > MAX_INGEST_ITEMS:
        raise HTTPException(400, f"Too many items (max {MAX_INGEST_ITEMS})")
    cleaned = [c for c in (_clean_item(r) for r in raw_items) if c]
    rejected = len(raw_items) - len(cleaned)
    inserted = 0
    if cleaned:
        await get_backend().insert(TABLE, cleaned)
        inserted = len(cleaned)
    return {
        "status": "ok",
        "received": len(raw_items),
        "upserted": inserted,
        "rejected": rejected,
        "table": TABLE,
        "ingested_at": _now_iso(),
    }
