from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from auth import verify_owner_token

app = FastAPI(title="SAHJONY Gmail Deletion Control", version="1.0.0", docs_url=None, redoc_url=None)

GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "").strip()
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "").strip()
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "").strip()
GMAIL_TOKEN_URL = os.getenv("GMAIL_TOKEN_URL", "https://oauth2.googleapis.com/token").strip()
GMAIL_API_BASE = os.getenv("GMAIL_API_BASE", "https://gmail.googleapis.com/gmail/v1").rstrip("/")

class GmailDeleteRequest(BaseModel):
    confirmation: str = Field(min_length=1, max_length=64)

def owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if not verify_owner_token(token):
        raise HTTPException(403, "Invalid owner credential")

def configured() -> bool:
    return bool(GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN)

def http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, method=method, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise HTTPException(502, f"Gmail provider HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise HTTPException(502, f"Gmail provider unavailable: {type(exc).__name__}") from exc

def access_token() -> str:
    if not configured():
        raise HTTPException(503, "Gmail OAuth credentials are not configured for mailbox deletion")
    body = urllib.parse.urlencode({"client_id": GMAIL_CLIENT_ID,"client_secret": GMAIL_CLIENT_SECRET,"refresh_token": GMAIL_REFRESH_TOKEN,"grant_type": "refresh_token"}).encode()
    payload = http_json(GMAIL_TOKEN_URL, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}, data=body)
    token = str(payload.get("access_token") or "")
    if not token:
        raise HTTPException(502, "Google did not return an access token")
    return token

def gmail_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token()}", "Content-Type": "application/json"}

def safe_message_id(message_id: str) -> str:
    value = message_id.strip()
    if not value or len(value) > 200 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for ch in value):
        raise HTTPException(400, "Invalid Gmail message id")
    return urllib.parse.quote(value)

@app.get("/native-email/delete-health")
def delete_health() -> dict[str, Any]:
    return {"status": "ok" if configured() else "configuration_required","service": "gmail-delete-control","owner_only": True,"trash_supported": configured(),"permanent_delete_supported": configured(),"oauth_required": True}

@app.post("/native-email/messages/{message_id}/trash")
def trash_message(message_id: str,payload: GmailDeleteRequest,authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    owner(authorization)
    if payload.confirmation != "TRASH":
        raise HTTPException(409, "Moving Gmail to Trash requires exact confirmation: TRASH")
    mid = safe_message_id(message_id)
    result = http_json(f"{GMAIL_API_BASE}/users/me/messages/{mid}/trash",method="POST",headers=gmail_headers(),data=b"{}")
    return {"status": "trashed", "message_id": result.get("id") or message_id, "thread_id": result.get("threadId")}

@app.delete("/native-email/messages/{message_id}")
def permanently_delete_message(message_id: str,payload: GmailDeleteRequest,authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    owner(authorization)
    if payload.confirmation != "DELETE PERMANENTLY":
        raise HTTPException(409, "Permanent Gmail deletion requires exact confirmation: DELETE PERMANENTLY")
    mid = safe_message_id(message_id)
    http_json(f"{GMAIL_API_BASE}/users/me/messages/{mid}", method="DELETE", headers=gmail_headers())
    return {"status": "deleted_permanently", "message_id": message_id}
