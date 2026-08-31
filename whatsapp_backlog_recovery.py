from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import whatsapp_api as core
from insforge_backend import get_backend
from whatsapp_self_healing import record_recovery_event


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        s=str(value).replace("Z","+00:00")
        dt=datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _body(row: dict[str, Any]) -> str:
    return str(row.get("text") or row.get("body") or row.get("content") or "").strip()


async def find_unanswered(limit: int = 200) -> list[dict[str, Any]]:
    backend=get_backend()
    rows=await backend.select("whatsapp_messages", params={"order":"created_at.asc","limit":str(max(1,min(limit*20,5000)))}) or []
    by_phone: dict[str,list[dict[str,Any]]] = {}
    for row in rows:
        phone=str(row.get("phone") or row.get("from_phone") or row.get("to_phone") or "").strip()
        if phone:
            by_phone.setdefault(phone,[]).append(row)
    pending=[]
    now=datetime.now(timezone.utc)
    for phone,msgs in by_phone.items():
        latest_in=None
        latest_out=None
        for m in msgs:
            direction=str(m.get("direction") or "").lower()
            if direction=="inbound": latest_in=m
            elif direction=="outbound": latest_out=m
        if not latest_in:
            continue
        in_dt=_parse_dt(latest_in.get("created_at"))
        out_dt=_parse_dt((latest_out or {}).get("created_at"))
        if out_dt and in_dt and out_dt >= in_dt:
            continue
        age_hours=((now-in_dt).total_seconds()/3600) if in_dt else None
        pending.append({
            "phone":phone,
            "message":latest_in,
            "message_text":_body(latest_in),
            "created_at":latest_in.get("created_at"),
            "age_hours":round(age_hours,2) if age_hours is not None else None,
            "reply_mode":"freeform" if age_hours is not None and age_hours < 23.5 else "template_required",
        })
    pending.sort(key=lambda x: str(x.get("created_at") or ""))
    return pending[:limit]


async def drain_backlog(limit: int = 50) -> dict[str, Any]:
    cfg=await core._config()
    if not core._send_ready(cfg):
        return {"status":"deferred","reason":"meta_cloud_send_not_ready","processed":0}
    pending=await find_unanswered(limit)
    sent=[]; template_required=[]; failed=[]
    for item in pending:
        phone=item["phone"]
        text=item.get("message_text") or ""
        if not text:
            continue
        if item["reply_mode"] != "freeform":
            template_required.append({"phone":phone,"created_at":item.get("created_at"),"reason":"outside_customer_service_window"})
            continue
        try:
            reply=await core._generate_ai_reply(text, None)
            if not reply.strip():
                raise RuntimeError("empty_ai_reply")
            await core._send_text(cfg,to=phone,body=reply,preview_url=False,lead_id=item["message"].get("lead_id"),customer_id=item["message"].get("customer_id"),source_url=None,autonomous=True)
            sent.append({"phone":phone,"created_at":item.get("created_at")})
        except Exception as exc:
            failed.append({"phone":phone,"error_type":type(exc).__name__})
    result={
        "status":"ok" if not failed else "partial",
        "pending_found":len(pending),
        "processed":len(sent),
        "sent":sent,
        "template_required":template_required,
        "failed":failed,
        "duplicate_protection":"latest_outbound_must_be_older_than_latest_inbound",
        "policy_window_guard":True,
    }
    await record_recovery_event("backlog_drain", {"status":result["status"],"processed":len(sent),"template_required":len(template_required),"failed":len(failed)})
    return result
