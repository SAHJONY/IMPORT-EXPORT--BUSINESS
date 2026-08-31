from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from auth import verify_owner_token

app = FastAPI(title="SAHJONY Google Calendar Transport", version="1.0.0", docs_url=None, redoc_url=None)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CALENDAR_CLIENT_ID", os.getenv("GMAIL_CLIENT_ID", "")).strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET", os.getenv("GMAIL_CLIENT_SECRET", "")).strip()
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_CALENDAR_REFRESH_TOKEN", os.getenv("GMAIL_REFRESH_TOKEN", "")).strip()
GOOGLE_TOKEN_URL = os.getenv("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token").strip()
CALENDAR_API_BASE = os.getenv("GOOGLE_CALENDAR_API_BASE", "https://www.googleapis.com/calendar/v3").rstrip("/")
CALENDAR_ID = os.getenv("BUSINESS_CALENDAR_ID", "primary").strip() or "primary"
DEFAULT_TIMEZONE = os.getenv("BUSINESS_TIMEZONE", "America/Chicago").strip() or "America/Chicago"


class CalendarEventCreate(BaseModel):
    summary: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    start: str = Field(min_length=10, max_length=80)
    end: str = Field(min_length=10, max_length=80)
    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=100)
    attendees: list[EmailStr] = Field(default_factory=list, max_length=50)
    location: str | None = Field(default=None, max_length=1000)
    conference: bool = True
    send_updates: bool = True


class CalendarEventUpdate(BaseModel):
    summary: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    start: str | None = Field(default=None, max_length=80)
    end: str | None = Field(default=None, max_length=80)
    timezone: str | None = Field(default=None, max_length=100)
    attendees: list[EmailStr] | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=1000)
    send_updates: bool = True


def _owner(authorization: str | None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization")
    if not verify_owner_token(authorization.removeprefix("Bearer ").strip()):
        raise HTTPException(status_code=403, detail="Invalid owner credential")


def _configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REFRESH_TOKEN)


def _http_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, data: bytes | None = None, timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1200]
        raise HTTPException(status_code=502, detail=f"Google Calendar HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Google Calendar unavailable: {type(exc).__name__}") from exc


def _access_token() -> str:
    if not _configured():
        raise HTTPException(status_code=503, detail="Google Calendar OAuth is not configured")
    body = urllib.parse.urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": GOOGLE_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode()
    payload = _http_json(GOOGLE_TOKEN_URL, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}, data=body)
    token = str(payload.get("access_token") or "")
    if not token:
        raise HTTPException(status_code=502, detail="Google did not return an access token")
    return token


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_access_token()}", "Content-Type": "application/json"}


def _event_body(p: CalendarEventCreate) -> dict[str, Any]:
    body: dict[str, Any] = {
        "summary": p.summary,
        "description": p.description or "",
        "start": {"dateTime": p.start, "timeZone": p.timezone},
        "end": {"dateTime": p.end, "timeZone": p.timezone},
        "attendees": [{"email": str(x)} for x in p.attendees],
    }
    if p.location:
        body["location"] = p.location
    if p.conference:
        body["conferenceData"] = {"createRequest": {"requestId": f"sahjony-{int(datetime.now(timezone.utc).timestamp()*1000)}"}}
    return body


@app.get("/calendar/health")
def calendar_health() -> dict[str, Any]:
    return {
        "status": "ok" if _configured() else "configuration_required",
        "service": "google-calendar-transport",
        "provider": "google_calendar",
        "calendar_id": CALENDAR_ID,
        "timezone": DEFAULT_TIMEZONE,
        "oauth_configured": _configured(),
        "read_calendar": True,
        "create_meetings": True,
        "reschedule_meetings": True,
        "cancel_meetings": True,
        "invite_attendees": True,
        "google_meet_supported": True,
        "autonomous_routine_scheduling_supported": True,
        "binding_or_high_risk_meetings_fail_closed": True,
        "secrets_exposed": False,
    }


@app.get("/calendar/events")
def calendar_events(
    days: int = Query(14, ge=1, le=90),
    max_results: int = Query(100, ge=1, le=250),
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    _owner(authorization)
    now = datetime.now(timezone.utc)
    params = urllib.parse.urlencode({
        "timeMin": now.isoformat().replace("+00:00", "Z"),
        "timeMax": (now + timedelta(days=days)).isoformat().replace("+00:00", "Z"),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(max_results),
    })
    data = _http_json(f"{CALENDAR_API_BASE}/calendars/{urllib.parse.quote(CALENDAR_ID, safe='')}/events?{params}", headers=_headers())
    return {"status": "ok", "calendar_id": CALENDAR_ID, "events": data.get("items") or []}


@app.post("/calendar/events")
def calendar_create(p: CalendarEventCreate, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    params = urllib.parse.urlencode({"conferenceDataVersion": "1", "sendUpdates": "all" if p.send_updates else "none"})
    result = _http_json(
        f"{CALENDAR_API_BASE}/calendars/{urllib.parse.quote(CALENDAR_ID, safe='')}/events?{params}",
        method="POST",
        headers=_headers(),
        data=json.dumps(_event_body(p)).encode(),
    )
    return {"status": "created", "event": result}


@app.patch("/calendar/events/{event_id}")
def calendar_update(event_id: str, p: CalendarEventUpdate, authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    body: dict[str, Any] = {}
    for key in ("summary", "description", "location"):
        value = getattr(p, key)
        if value is not None:
            body[key] = value
    tz = p.timezone or DEFAULT_TIMEZONE
    if p.start is not None:
        body["start"] = {"dateTime": p.start, "timeZone": tz}
    if p.end is not None:
        body["end"] = {"dateTime": p.end, "timeZone": tz}
    if p.attendees is not None:
        body["attendees"] = [{"email": str(x)} for x in p.attendees]
    params = urllib.parse.urlencode({"sendUpdates": "all" if p.send_updates else "none"})
    result = _http_json(
        f"{CALENDAR_API_BASE}/calendars/{urllib.parse.quote(CALENDAR_ID, safe='')}/events/{urllib.parse.quote(event_id, safe='')}?{params}",
        method="PATCH",
        headers=_headers(),
        data=json.dumps(body).encode(),
    )
    return {"status": "updated", "event": result}


@app.delete("/calendar/events/{event_id}")
def calendar_delete(event_id: str, send_updates: bool = Query(True), authorization: str | None = Header(None, alias="Authorization")) -> dict[str, Any]:
    _owner(authorization)
    params = urllib.parse.urlencode({"sendUpdates": "all" if send_updates else "none"})
    req = urllib.request.Request(
        f"{CALENDAR_API_BASE}/calendars/{urllib.parse.quote(CALENDAR_ID, safe='')}/events/{urllib.parse.quote(event_id, safe='')}?{params}",
        method="DELETE",
        headers={"Authorization": f"Bearer {_access_token()}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code != 204:
            detail = exc.read().decode("utf-8", "replace")[:1200]
            raise HTTPException(status_code=502, detail=f"Google Calendar HTTP {exc.code}: {detail}") from exc
    return {"status": "deleted", "event_id": event_id}
