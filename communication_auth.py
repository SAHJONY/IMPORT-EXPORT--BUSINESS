from __future__ import annotations

import hmac
import os

from auth import hash_token
from database import get_connection


def verify_owner_token(provided: str) -> bool:
    expected = os.getenv("OWNER_TOKEN")
    return bool(expected) and hmac.compare_digest(provided, expected)


def verify_customer_token(provided: str):
    token_hash = hash_token(provided)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT participant_id, business_id FROM participants WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {"participant_id": row["participant_id"], "business_id": row["business_id"]}
