"""SAHJONY Social Inbox API — read-only owner view of ingested social items.

Items are written by the `facebook_ingest.py` scheduled job into the
`sahjony_trade_records` logical table `social_inbox_items`. This module
exposes them to the owner CRM hub. No writes, no Facebook mutations here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query

from auth import verify_owner_token
from insforge_backend import get_backend

app = FastAPI(
    title="SAHJONY Social Inbox",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

TABLE = "social_inbox_items"


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
