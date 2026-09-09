from __future__ import annotations

import asyncio
import os
import secrets
from datetime import datetime, timezone

from gmail_transport_api import NativeEmailSend, _oauth_configured, _send_gmail, _send_smtp, _smtp_configured
from insforge_backend import get_backend

MAX_PER_CYCLE = max(1, min(int(os.getenv("LEAD_ENGAGEMENT_MAX_PER_CYCLE", "2")), 5))
MIN_SCORE = max(60, min(int(os.getenv("LEAD_ENGAGEMENT_MIN_SCORE", "70")), 100))
ENABLED = os.getenv("LEAD_ENGAGEMENT_AUTONOMY_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def eligible(row: dict) -> bool:
    if str(row.get("status") or "").upper() not in {"NEW", "RESEARCHED", "READY_FOR_CONTACT"}:
        return False
    if bool(row.get("duplicate_candidate")):
        return False
    if int(row.get("opportunity_score") or 0) < MIN_SCORE:
        return False
    if not str(row.get("email") or "").strip():
        return False
    if bool(row.get("consent_to_business_contact")) is False:
        # Public B2B first contact is allowed only as a small, individually reviewed outreach.
        # This worker never performs bulk campaigns and never follows up after opt-out.
        pass
    notes = str(row.get("notes") or "").lower()
    if any(x in notes for x in ["opt-out", "do not contact", "suppressed", "unsubscribe"]):
        return False
    name = str(row.get("business_name") or "").lower()
    if "beach cargo" in name or "america cargo services" in name:
        return False
    return True


def body_for(row: dict) -> str:
    business = str(row.get("business_name") or "su empresa").strip()
    relevance = str(row.get("product_need_or_offer") or "").strip()
    country = str(row.get("country") or "").strip()
    return (
        f"Hola {business},\n\n"
        "Mi nombre es Sofía Smith, Executive Manager de SAHJONY LLC. "
        f"Revisamos información pública de su empresa y vimos una posible afinidad comercial en {country or 'su mercado'}.\n\n"
        f"Contexto observado: {relevance[:900]}\n\n"
        "SAHJONY trabaja en sourcing internacional, importación/exportación, carga consolidada, logística y desarrollo de proveedores/compradores. "
        "Si actualmente tienen una necesidad concreta, puede responder con producto o servicio, cantidad, destino, fecha requerida y cualquier especificación importante. "
        "Con esos datos podemos evaluar opciones y preparar el siguiente paso sin asumir precios, disponibilidad ni condiciones que no estén verificadas.\n\n"
        "Si este contacto no es relevante para su empresa, indíquelo y no realizaremos seguimiento.\n\n"
        "Sofía Smith\nExecutive Manager\nSAHJONY LLC\nwww.sahjony.com"
    )


def subject_for(row: dict) -> str:
    business = str(row.get("business_name") or "su empresa").strip()
    return f"Posible colaboración comercial | SAHJONY x {business}"[:300]


async def already_contacted(lead_id: str) -> bool:
    backend = get_backend()
    rows = await backend.select(
        "business_events",
        params={"event_type": "eq.autonomous_lead_first_contact", "lead_id": f"eq.{lead_id}", "limit": "1"},
    ) or []
    return bool(rows)


async def record(row: dict, result: dict) -> None:
    backend = get_backend()
    lead_id = str(row.get("lead_id") or "")
    await backend.insert("business_events", {
        "event_id": f"lead_contact_{secrets.token_urlsafe(10)}",
        "event_type": "autonomous_lead_first_contact",
        "source_type": "global_lead_engagement_autopilot",
        "source_id": lead_id,
        "trade_case_id": None,
        "customer_id": None,
        "lead_id": lead_id,
        "actor_role": "prospect",
        "actor_id": lead_id,
        "visibility": "business",
        "title": f"First-contact email sent to {str(row.get('business_name') or '')[:180]}",
        "summary": f"Governed one-to-one first contact sent to public business email {str(row.get('email') or '')[:240]}",
        "action_required": False,
        "action_label": "Await reply before qualification",
        "priority": "normal",
        "event_status": "closed",
        "payload": {
            "channel": "email",
            "autonomous": True,
            "one_to_one": True,
            "bulk_campaign": False,
            "binding_commitment": False,
            "qualified_demand": False,
            "opportunity_score": row.get("opportunity_score"),
            "provider_result": result,
            "sent_at": now(),
        },
    })
    await backend.patch(
        "lead_scout_leads",
        {"status": "CONTACTED", "updated_at": now()},
        params={"lead_id": f"eq.{lead_id}"},
    )


def send_email(row: dict) -> dict:
    payload = NativeEmailSend(
        to=[str(row["email"]).strip()],
        subject=subject_for(row),
        body=body_for(row),
    )
    if _oauth_configured():
        return _send_gmail(payload)
    if _smtp_configured():
        return _send_smtp(payload)
    raise RuntimeError("Gmail transport is not configured for autonomous lead engagement")


async def main() -> None:
    if not ENABLED:
        print({"status": "disabled"})
        return
    backend = get_backend()
    rows = await backend.select(
        "lead_scout_leads",
        params={"order": "opportunity_score.desc", "limit": "200"},
    ) or []
    sent = 0
    skipped = 0
    for row in rows:
        if sent >= MAX_PER_CYCLE:
            break
        if not eligible(row):
            skipped += 1
            continue
        lead_id = str(row.get("lead_id") or "")
        if not lead_id or await already_contacted(lead_id):
            skipped += 1
            continue
        try:
            result = await asyncio.to_thread(send_email, row)
            await record(row, result)
            sent += 1
        except Exception as exc:
            await backend.insert("business_events", {
                "event_id": f"lead_contact_error_{secrets.token_urlsafe(10)}",
                "event_type": "autonomous_lead_contact_error",
                "source_type": "global_lead_engagement_autopilot",
                "source_id": lead_id or "unknown",
                "trade_case_id": None,
                "customer_id": None,
                "lead_id": lead_id or None,
                "actor_role": "system",
                "actor_id": "sofia-smith",
                "visibility": "business",
                "title": "Autonomous lead contact failed",
                "summary": type(exc).__name__,
                "action_required": True,
                "action_label": "Review lead engagement transport",
                "priority": "normal",
                "event_status": "open",
                "payload": {"error_type": type(exc).__name__, "qualified_demand": False, "binding_commitment": False},
            })
            break
    print({"status": "ok", "sent": sent, "skipped": skipped, "max_per_cycle": MAX_PER_CYCLE, "min_score": MIN_SCORE})


if __name__ == "__main__":
    asyncio.run(main())
