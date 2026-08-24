from __future__ import annotations

import base64
import email
import imaplib
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from auth import verify_owner_token

app = FastAPI(title="SAHJONY Native Gmail Transport", version="1.0.0", docs_url=None, redoc_url=None)

MAILBOX = os.getenv("OPERATIONAL_MAILBOX", "sahjonyllc@gmail.com").strip()
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "").strip()
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "").strip()
GMAIL_REFRESH_TOKEN = os.getenv("GMAIL_REFRESH_TOKEN", "").strip()
GMAIL_TOKEN_URL = os.getenv("GMAIL_TOKEN_URL", "https://oauth2.googleapis.com/token").strip()
GMAIL_API_BASE = os.getenv("GMAIL_API_BASE", "https://gmail.googleapis.com/gmail/v1").rstrip("/")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "465") or "465")
IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com").strip()
IMAP_PORT = int(os.getenv("IMAP_PORT", "993") or "993")
GMAIL_SMTP_APP_PASSWORD = os.getenv("GMAIL_SMTP_APP_PASSWORD", "").strip().replace(" ", "")


class NativeEmailSend(BaseModel):
    to: list[EmailStr] = Field(min_length=1, max_length=50)
    cc: list[EmailStr] = Field(default_factory=list, max_length=50)
    bcc: list[EmailStr] = Field(default_factory=list, max_length=50)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=50000)
    reply_to: EmailStr | None = None


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if not verify_owner_token(token):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


def _oauth_configured() -> bool:
    return bool(GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN)


def _smtp_configured() -> bool:
    return bool(MAILBOX and SMTP_HOST and GMAIL_SMTP_APP_PASSWORD)


def _imap_configured() -> bool:
    return bool(MAILBOX and IMAP_HOST and GMAIL_SMTP_APP_PASSWORD)


def _http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None, timeout: int = 15) -> dict[str, Any]:
    request = urllib.request.Request(url, method=method, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise HTTPException(status_code=502, detail=f"Gmail provider HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Gmail provider unavailable: {type(exc).__name__}") from exc


def _access_token() -> str:
    if not _oauth_configured():
        raise HTTPException(status_code=503, detail="Gmail OAuth credentials are not configured")
    body = urllib.parse.urlencode({
        "client_id": GMAIL_CLIENT_ID,
        "client_secret": GMAIL_CLIENT_SECRET,
        "refresh_token": GMAIL_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode()
    payload = _http_json(
        GMAIL_TOKEN_URL,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
    )
    token = str(payload.get("access_token") or "")
    if not token:
        raise HTTPException(status_code=502, detail="Google did not return an access token")
    return token


def _gmail_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"}


def _decode_b64url(value: str | None) -> str:
    if not value:
        return ""
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", "replace")
    except Exception:
        return ""


def _gmail_body(payload: dict[str, Any]) -> str:
    mime = str(payload.get("mimeType") or "")
    data = ((payload.get("body") or {}).get("data"))
    if mime.startswith("text/plain") and data:
        return _decode_b64url(data)
    for part in payload.get("parts") or []:
        body = _gmail_body(part)
        if body:
            return body
    if data:
        return _decode_b64url(data)
    return ""


def _header_map(payload: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in payload.get("headers") or []:
        name = str(item.get("name") or "").lower()
        value = str(item.get("value") or "")
        if name:
            result[name] = value
    return result


def _send_gmail(payload: NativeEmailSend) -> dict[str, Any]:
    message = EmailMessage()
    message["From"] = MAILBOX
    message["To"] = ", ".join(str(x) for x in payload.to)
    if payload.cc:
        message["Cc"] = ", ".join(str(x) for x in payload.cc)
    if payload.bcc:
        message["Bcc"] = ", ".join(str(x) for x in payload.bcc)
    if payload.reply_to:
        message["Reply-To"] = str(payload.reply_to)
    message["Subject"] = payload.subject
    message.set_content(payload.body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
    result = _http_json(
        f"{GMAIL_API_BASE}/users/me/messages/send",
        method="POST",
        headers=_gmail_headers(),
        data=json.dumps({"raw": raw}).encode(),
    )
    return {"provider": "gmail_api_oauth", "message_id": result.get("id"), "thread_id": result.get("threadId")}


def _send_smtp(payload: NativeEmailSend) -> dict[str, Any]:
    if not _smtp_configured():
        raise HTTPException(status_code=503, detail="SMTP credentials are not configured")
    message = EmailMessage()
    message["From"] = MAILBOX
    message["To"] = ", ".join(str(x) for x in payload.to)
    if payload.cc:
        message["Cc"] = ", ".join(str(x) for x in payload.cc)
    if payload.reply_to:
        message["Reply-To"] = str(payload.reply_to)
    message["Subject"] = payload.subject
    message.set_content(payload.body)
    recipients = [str(x) for x in payload.to + payload.cc + payload.bcc]
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=20) as server:
            server.login(MAILBOX, GMAIL_SMTP_APP_PASSWORD)
            refused = server.send_message(message, from_addr=MAILBOX, to_addrs=recipients)
        return {"provider": "gmail_smtp", "accepted": len(recipients) - len(refused), "refused": list(refused.keys())}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMTP delivery failed: {type(exc).__name__}") from exc


def _inbox_gmail(limit: int, query: str | None) -> list[dict[str, Any]]:
    params = {"maxResults": str(limit)}
    if query:
        params["q"] = query
    listing = _http_json(f"{GMAIL_API_BASE}/users/me/messages?{urllib.parse.urlencode(params)}", headers=_gmail_headers())
    rows: list[dict[str, Any]] = []
    for item in listing.get("messages") or []:
        message_id = item.get("id")
        if not message_id:
            continue
        full = _http_json(f"{GMAIL_API_BASE}/users/me/messages/{urllib.parse.quote(str(message_id))}?format=full", headers=_gmail_headers())
        payload = full.get("payload") or {}
        headers = _header_map(payload)
        rows.append({
            "id": full.get("id"),
            "thread_id": full.get("threadId"),
            "from": headers.get("from"),
            "to": headers.get("to"),
            "subject": headers.get("subject"),
            "date": headers.get("date"),
            "snippet": full.get("snippet"),
            "body": _gmail_body(payload)[:20000],
            "labels": full.get("labelIds") or [],
        })
    return rows


def _decode_imap_message(raw: bytes, uid: str) -> dict[str, Any]:
    msg = email.message_from_bytes(raw)
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition") or "").lower():
                data = part.get_payload(decode=True) or b""
                body = data.decode(part.get_content_charset() or "utf-8", "replace")
                if body:
                    break
    else:
        data = msg.get_payload(decode=True) or b""
        body = data.decode(msg.get_content_charset() or "utf-8", "replace")
    return {"id": uid, "thread_id": None, "from": msg.get("From"), "to": msg.get("To"), "subject": msg.get("Subject"), "date": msg.get("Date"), "snippet": body[:500], "body": body[:20000], "labels": []}


def _inbox_imap(limit: int) -> list[dict[str, Any]]:
    if not _imap_configured():
        raise HTTPException(status_code=503, detail="IMAP credentials are not configured")
    try:
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ssl.create_default_context()) as client:
            client.login(MAILBOX, GMAIL_SMTP_APP_PASSWORD)
            client.select("INBOX", readonly=True)
            status, data = client.uid("search", None, "ALL")
            if status != "OK":
                return []
            uids = (data[0] or b"").split()[-limit:][::-1]
            rows: list[dict[str, Any]] = []
            for uid_b in uids:
                uid = uid_b.decode()
                status, fetched = client.uid("fetch", uid, "(RFC822)")
                if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                    continue
                rows.append(_decode_imap_message(fetched[0][1], uid))
            return rows
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"IMAP receive failed: {type(exc).__name__}") from exc


@app.get("/native-email/health")
def native_email_health() -> dict[str, Any]:
    oauth = _oauth_configured()
    smtp = _smtp_configured()
    imap = _imap_configured()
    receive_mode = "gmail_api_oauth" if oauth else ("gmail_imap" if imap else "not_configured")
    send_mode = "gmail_api_oauth" if oauth else ("gmail_smtp" if smtp else "not_configured")
    return {
        "status": "ok" if (oauth or (smtp and imap)) else "configuration_required",
        "service": "native-gmail-transport",
        "mailbox": MAILBOX,
        "provider": "gmail",
        "oauth_configured": oauth,
        "smtp_configured": smtp,
        "imap_configured": imap,
        "send_mode": send_mode,
        "receive_mode": receive_mode,
        "direct_platform_send_receive_ready": bool(oauth or (smtp and imap)),
        "preferred_mode": "gmail_api_oauth",
        "required_oauth_env": ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"],
        "fallback_env": ["GMAIL_SMTP_APP_PASSWORD"],
        "secrets_exposed": False,
    }


@app.get("/native-email/inbox")
def native_email_inbox(
    limit: int = Query(default=25, ge=1, le=100),
    q: str | None = Query(default=None, max_length=500),
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _owner(authorization)
    if _oauth_configured():
        rows = _inbox_gmail(limit, q)
        mode = "gmail_api_oauth"
    elif _imap_configured():
        rows = _inbox_imap(limit)
        mode = "gmail_imap"
    else:
        raise HTTPException(status_code=503, detail="Native Gmail receive is not configured")
    return {"mailbox": MAILBOX, "mode": mode, "messages": rows}


@app.post("/native-email/send")
def native_email_send(
    payload: NativeEmailSend,
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _owner(authorization)
    if _oauth_configured():
        result = _send_gmail(payload)
    elif _smtp_configured():
        result = _send_smtp(payload)
    else:
        raise HTTPException(status_code=503, detail="Native Gmail send is not configured")
    return {"status": "sent", "mailbox": MAILBOX, **result}
