from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from auth import verify_customer_token, verify_owner_token
from insforge_backend import InsForgeConfigurationError, get_backend

app = FastAPI(
    title="SAHJONY Global Trade Communications",
    description="Role-scoped owner, employee and customer communication layer.",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)

Role = Literal["owner", "employee", "customer"]
Priority = Literal["normal", "high", "urgent"]


class MessageCreate(BaseModel):
    thread_id: str | None = Field(default=None, max_length=120)
    recipient_role: Role
    recipient_id: str | None = Field(default=None, max_length=160)
    customer_id: str | None = Field(default=None, max_length=160)
    trade_case_id: str | None = Field(default=None, max_length=160)
    subject: str = Field(min_length=2, max_length=240)
    body: str = Field(min_length=1, max_length=10000)
    priority: Priority = "normal"
    escalation_requested: bool = False


class MessageStatus(BaseModel):
    status: Literal["read", "resolved"]


def _employee_token() -> str:
    token = os.getenv("EMPLOYEE_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="Employee communications are not configured")
    return token


def _identity(role: str | None, authorization: str | None, employee_id: str | None) -> dict[str, str]:
    if role not in {"owner", "employee", "customer"}:
        raise HTTPException(status_code=400, detail="X-Role must be owner, employee or customer")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()

    if role == "owner":
        if not verify_owner_token(token):
            raise HTTPException(status_code=403, detail="Invalid owner credential")
        return {"role": "owner", "id": "owner"}

    if role == "employee":
        if not secrets.compare_digest(token, _employee_token()):
            raise HTTPException(status_code=403, detail="Invalid employee credential")
        safe_id = (employee_id or "staff").strip()[:160]
        return {"role": "employee", "id": safe_id or "staff"}

    customer = verify_customer_token(token)
    if not customer:
        raise HTTPException(status_code=403, detail="Invalid customer credential")
    return {"role": "customer", "id": str(customer["participant_id"])}


def _validate_route(sender: dict[str, str], payload: MessageCreate) -> None:
    sender_role = sender["role"]
    recipient_role = payload.recipient_role

    if sender_role == "customer":
        if recipient_role not in {"employee", "owner"}:
            raise HTTPException(status_code=403, detail="Customers may contact operations or request owner escalation")
        if payload.customer_id and payload.customer_id != sender["id"]:
            raise HTTPException(status_code=403, detail="Customer scope mismatch")

    if sender_role == "employee" and recipient_role == "customer" and not payload.customer_id:
        raise HTTPException(status_code=400, detail="Customer recipient messages require customer_id")

    if recipient_role == "customer" and not (payload.customer_id or payload.recipient_id):
        raise HTTPException(status_code=400, detail="Customer recipient must be explicitly scoped")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/communications/health")
async def health() -> dict[str, Any]:
    configured = bool(os.getenv("INSFORGE_BASE_URL") and os.getenv("INSFORGE_API_KEY"))
    return {
        "status": "ok",
        "service": "tri-role-communications",
        "persistence": "insforge",
        "configured": configured,
        "employee_auth_configured": bool(os.getenv("EMPLOYEE_TOKEN")),
        "roles": ["owner", "employee", "customer"],
        "tenant_policy": "customer-isolated",
    }


@app.post("/communications/messages")
async def create_message(
    payload: MessageCreate,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    sender = _identity(x_role, authorization, x_employee_id)
    _validate_route(sender, payload)

    customer_id = sender["id"] if sender["role"] == "customer" else payload.customer_id
    thread_id = payload.thread_id or f"thr_{secrets.token_urlsafe(16)}"
    message_id = f"msg_{secrets.token_urlsafe(18)}"
    created_at = _now()
    row = {
        "message_id": message_id,
        "thread_id": thread_id,
        "sender_role": sender["role"],
        "sender_id": sender["id"],
        "recipient_role": payload.recipient_role,
        "recipient_id": payload.recipient_id,
        "customer_id": customer_id,
        "trade_case_id": payload.trade_case_id,
        "subject": payload.subject,
        "body": payload.body,
        "priority": payload.priority,
        "status": "sent",
        "escalation_requested": payload.escalation_requested,
        "created_at": created_at,
        "updated_at": created_at,
    }
    try:
        result = await get_backend().insert("communications", row)
    except InsForgeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Communication persistence unavailable: {type(exc).__name__}") from exc
    return {"message": row, "persistence": result}


@app.get("/communications/messages")
async def list_messages(
    thread_id: str | None = Query(default=None, max_length=120),
    customer_id: str | None = Query(default=None, max_length=160),
    trade_case_id: str | None = Query(default=None, max_length=160),
    limit: int = Query(default=100, ge=1, le=250),
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = _identity(x_role, authorization, x_employee_id)
    params: dict[str, str] = {"order": "created_at.desc", "limit": str(limit)}
    if thread_id:
        params["thread_id"] = f"eq.{thread_id}"
    if trade_case_id:
        params["trade_case_id"] = f"eq.{trade_case_id}"

    if actor["role"] == "customer":
        params["customer_id"] = f"eq.{actor['id']}"
    elif customer_id:
        params["customer_id"] = f"eq.{customer_id}"

    try:
        rows = await get_backend().select("communications", params=params)
    except InsForgeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Communication persistence unavailable: {type(exc).__name__}") from exc

    rows = rows or []
    if actor["role"] == "employee":
        rows = [
            row for row in rows
            if row.get("sender_role") == "employee"
            or row.get("recipient_role") == "employee"
            or row.get("escalation_requested") is True
        ]
    return {"messages": rows, "actor": actor}


@app.patch("/communications/messages/{message_id}")
async def update_message_status(
    message_id: str,
    payload: MessageStatus,
    x_role: str | None = Header(None, alias="X-Role"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_employee_id: str | None = Header(None, alias="X-Employee-Id"),
):
    actor = _identity(x_role, authorization, x_employee_id)
    if actor["role"] == "customer" and payload.status == "resolved":
        raise HTTPException(status_code=403, detail="Customers cannot resolve operational threads")
    try:
        result = await get_backend().patch(
            "communications",
            {"status": payload.status, "updated_at": _now()},
            params={"message_id": f"eq.{message_id}"},
        )
    except InsForgeConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Communication persistence unavailable: {type(exc).__name__}") from exc
    return {"message_id": message_id, "status": payload.status, "actor": actor, "persistence": result}
