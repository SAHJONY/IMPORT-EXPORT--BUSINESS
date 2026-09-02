from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(title="SAHJONY Global World Clock & Trade Timezone OS", version="1.0.1", docs_url=None, redoc_url=None)

COUNTRY_TZ = {
    "US":"America/Chicago","CA":"America/Toronto","MX":"America/Mexico_City","CU":"America/Havana",
    "GT":"America/Guatemala","BZ":"America/Belize","SV":"America/El_Salvador","HN":"America/Tegucigalpa",
    "NI":"America/Managua","CR":"America/Costa_Rica","PA":"America/Panama","DO":"America/Santo_Domingo",
    "JM":"America/Jamaica","TT":"America/Port_of_Spain","BS":"America/Nassau","BB":"America/Barbados",
    "CO":"America/Bogota","VE":"America/Caracas","EC":"America/Guayaquil","PE":"America/Lima",
    "BO":"America/La_Paz","CL":"America/Santiago","AR":"America/Argentina/Buenos_Aires","UY":"America/Montevideo",
    "PY":"America/Asuncion","BR":"America/Sao_Paulo","GY":"America/Guyana","SR":"America/Paramaribo",
    "GB":"Europe/London","IE":"Europe/Dublin","ES":"Europe/Madrid","PT":"Europe/Lisbon","FR":"Europe/Paris",
    "DE":"Europe/Berlin","IT":"Europe/Rome","NL":"Europe/Amsterdam","BE":"Europe/Brussels","CH":"Europe/Zurich",
    "PL":"Europe/Warsaw","TR":"Europe/Istanbul","UA":"Europe/Kyiv","RO":"Europe/Bucharest","GR":"Europe/Athens",
    "AE":"Asia/Dubai","SA":"Asia/Riyadh","QA":"Asia/Qatar","OM":"Asia/Muscat","BH":"Asia/Bahrain","KW":"Asia/Kuwait",
    "IL":"Asia/Jerusalem","EG":"Africa/Cairo","MA":"Africa/Casablanca","DZ":"Africa/Algiers","ZA":"Africa/Johannesburg",
    "NG":"Africa/Lagos","KE":"Africa/Nairobi","GH":"Africa/Accra","TZ":"Africa/Dar_es_Salaam","ET":"Africa/Addis_Ababa",
    "IN":"Asia/Kolkata","PK":"Asia/Karachi","BD":"Asia/Dhaka","LK":"Asia/Colombo","NP":"Asia/Kathmandu",
    "CN":"Asia/Shanghai","HK":"Asia/Hong_Kong","TW":"Asia/Taipei","JP":"Asia/Tokyo","KR":"Asia/Seoul",
    "SG":"Asia/Singapore","MY":"Asia/Kuala_Lumpur","TH":"Asia/Bangkok","VN":"Asia/Ho_Chi_Minh","ID":"Asia/Jakarta",
    "PH":"Asia/Manila","KH":"Asia/Phnom_Penh","MM":"Asia/Yangon","AU":"Australia/Sydney","NZ":"Pacific/Auckland",
    "RU":"Europe/Moscow","KZ":"Asia/Almaty","UZ":"Asia/Tashkent","AZ":"Asia/Baku","GE":"Asia/Tbilisi",
}

TRADE_HUBS = [
    ("Houston","America/Chicago"),("New York","America/New_York"),("Los Angeles","America/Los_Angeles"),
    ("Mexico City","America/Mexico_City"),("Havana","America/Havana"),("Panama City","America/Panama"),
    ("Bogota","America/Bogota"),("Caracas","America/Caracas"),("Lima","America/Lima"),
    ("Sao Paulo","America/Sao_Paulo"),("Buenos Aires","America/Argentina/Buenos_Aires"),("Santiago","America/Santiago"),
    ("London","Europe/London"),("Madrid","Europe/Madrid"),("Rotterdam","Europe/Amsterdam"),("Frankfurt","Europe/Berlin"),
    ("Istanbul","Europe/Istanbul"),("Dubai","Asia/Dubai"),("Riyadh","Asia/Riyadh"),("Mumbai","Asia/Kolkata"),
    ("Singapore","Asia/Singapore"),("Bangkok","Asia/Bangkok"),("Ho Chi Minh City","Asia/Ho_Chi_Minh"),
    ("Shenzhen/Shanghai","Asia/Shanghai"),("Hong Kong","Asia/Hong_Kong"),("Tokyo","Asia/Tokyo"),
    ("Seoul","Asia/Seoul"),("Sydney","Australia/Sydney"),("Auckland","Pacific/Auckland"),
    ("Johannesburg","Africa/Johannesburg"),("Lagos","Africa/Lagos"),("Nairobi","Africa/Nairobi"),("Cairo","Africa/Cairo"),
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, f"Unknown IANA timezone: {name}")


def offset_label(dt: datetime) -> str:
    offset = dt.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"UTC{sign}{minutes//60:02d}:{minutes%60:02d}"


def is_working(local: datetime, start_hour: int, end_hour: int, include_weekends: bool = False) -> bool:
    if not include_weekends and local.weekday() >= 5:
        return False
    if start_hour <= end_hour:
        return start_hour <= local.hour < end_hour
    return local.hour >= start_hour or local.hour < end_hour


def next_work_start(local: datetime, start_hour: int, include_weekends: bool = False) -> datetime:
    candidate = local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    if local < candidate and (include_weekends or candidate.weekday() < 5):
        return candidate
    candidate += timedelta(days=1)
    while not include_weekends and candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def zone_snapshot(tz_name: str, now_utc: datetime, work_start: int = 9, work_end: int = 17) -> dict[str, Any]:
    z = safe_zone(tz_name)
    local = now_utc.astimezone(z)
    working = is_working(local, work_start, work_end)
    nxt = None if working else next_work_start(local, work_start)
    return {
        "timezone": tz_name,
        "local_time": local.isoformat(),
        "local_date": local.date().isoformat(),
        "weekday": local.strftime("%A"),
        "utc_offset": offset_label(local),
        "abbreviation": local.tzname(),
        "working_hours": {"start": f"{work_start:02d}:00", "end": f"{work_end:02d}:00", "weekdays_only": True},
        "currently_in_working_hours": working,
        "next_work_start_local": nxt.isoformat() if nxt else None,
        "next_work_start_utc": nxt.astimezone(timezone.utc).isoformat() if nxt else None,
    }


class LeadTimeProfile(BaseModel):
    lead_id: str | None = None
    company: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = None
    preferred_start_hour: int = Field(default=9, ge=0, le=23)
    preferred_end_hour: int = Field(default=17, ge=0, le=23)
    include_weekends: bool = False
    urgency: str = Field(default="normal", pattern="^(low|normal|high|critical)$")


@app.get("/world-clock/health")
async def health():
    return {
        "status":"ok","service":"global-world-clock-trade-os",
        "iana_timezone_database":True,"timezone_count":len(available_timezones()),"dst_aware":True,
        "lead_local_working_hours":True,"24x7_follow_the_sun_routing":True,"binding_actions_allowed":False,
    }


@app.get("/world-clock/zones")
async def zones(q: str | None = None, limit: int = Query(1000, ge=1, le=1000)):
    names = sorted(available_timezones())
    if q:
        needle = q.lower().strip()
        names = [x for x in names if needle in x.lower()]
    return {"count":len(names[:limit]),"total_matching":len(names),"zones":names[:limit]}


@app.get("/world-clock/now")
async def now(tz: str = Query("America/Chicago")):
    return zone_snapshot(tz, utc_now())


@app.get("/world-clock/hubs")
async def hubs():
    current = utc_now()
    rows = []
    for city, tz_name in TRADE_HUBS:
        snap = zone_snapshot(tz_name, current)
        rows.append({"city":city, **snap})
    rows.sort(key=lambda r: (not r["currently_in_working_hours"], r["local_time"]))
    return {"as_of_utc":current.isoformat(),"count":len(rows),"hubs":rows}


@app.post("/world-clock/lead-window")
async def lead_window(profile: LeadTimeProfile):
    tz_name = profile.timezone
    inferred = False
    if not tz_name and profile.country_code:
        tz_name = COUNTRY_TZ.get(profile.country_code.upper())
        inferred = bool(tz_name)
    if not tz_name:
        raise HTTPException(422, "Lead timezone required when no country fallback is available")
    z = safe_zone(tz_name)
    current = utc_now()
    local = current.astimezone(z)
    active = is_working(local, profile.preferred_start_hour, profile.preferred_end_hour, profile.include_weekends)
    nxt = None if active else next_work_start(local, profile.preferred_start_hour, profile.include_weekends)
    if profile.urgency == "critical": recommended = "IMMEDIATE_REVIEW"
    elif active: recommended = "CONTACT_WINDOW_OPEN"
    else: recommended = "QUEUE_FOR_NEXT_LOCAL_WORK_WINDOW"
    return {
        "lead_id":profile.lead_id,"company":profile.company,"timezone":tz_name,"timezone_inferred":inferred,
        "local_time":local.isoformat(),"utc_offset":offset_label(local),"within_preferred_hours":active,
        "recommended_action":recommended,
        "next_contact_local":nxt.isoformat() if nxt else local.isoformat(),
        "next_contact_utc":nxt.astimezone(timezone.utc).isoformat() if nxt else current.isoformat(),
        "urgency":profile.urgency,
        "policy":"Use local-business-hour awareness for outreach; critical inbound leads may be reviewed immediately without making binding commitments.",
    }


@app.get("/world-clock/follow-the-sun")
async def follow_the_sun():
    current = utc_now()
    active, next_up = [], []
    for city, tz_name in TRADE_HUBS:
        snap = zone_snapshot(tz_name, current)
        row = {"city":city,"timezone":tz_name,"local_time":snap["local_time"],"utc_offset":snap["utc_offset"]}
        if snap["currently_in_working_hours"]:
            active.append(row)
        else:
            row["next_work_start_utc"] = snap["next_work_start_utc"]
            next_up.append(row)
    next_up.sort(key=lambda x: x.get("next_work_start_utc") or "")
    return {
        "status":"ok","as_of_utc":current.isoformat(),"operating_model":"FOLLOW_THE_SUN_24X7",
        "active_trade_hubs_now":active,"next_trade_hubs_opening":next_up[:12],
        "instruction":"SOFIA should prioritize inbound and consented follow-up where local business hours are open, then hand off the queue as the earth rotates.",
        "binding_actions_allowed":False,
    }
