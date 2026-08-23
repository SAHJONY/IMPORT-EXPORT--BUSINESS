from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

from insforge_backend import get_backend

SEED_PATH = Path(__file__).resolve().parent / "data" / "cuba_mipyme_outreach_2026-08-23.json"
CAMPAIGN = "CUBA_MIPYME_OUTREACH_2026_08_23"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_seed() -> list[dict]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _sales_status(lead: dict) -> str:
    outreach_status = str(lead.get("outreach_status") or "").upper()
    if outreach_status.startswith("BOUNCED"):
        return "DO_NOT_CONTACT"
    if outreach_status == "SENT":
        return "CONTACTED"
    return "NEW"


async def bootstrap_cuba_mipyme_outreach() -> dict:
    """Upsert the verified outreach cohort as CRM prospects.

    This function is deliberately idempotent by normalized business email. It never creates
    a sourcing intake on behalf of a prospect; a trade intake is created only after the
    prospect submits an actual need or staff records one from a reply.
    """
    backend = get_backend()
    created = 0
    updated = 0
    unchanged = 0
    ts = _now()

    for lead in load_seed():
        email = lead["email"].strip().lower()
        sales_status = _sales_status(lead)
        existing = await backend.select(
            "customer_accounts",
            params={"email": f"eq.{email}", "limit": "1"},
        ) or []

        if existing:
            customer_id = existing[0]["customer_id"]
            patch = {
                "legal_name": lead["legal_name"],
                "trade_name": lead["legal_name"],
                "contact_name": "Equipo comercial",
                "country_code": "CU",
                "website": lead.get("funnel_url"),
                "status": existing[0].get("status") or "PROSPECT",
                "sales_status": sales_status,
                "source": CAMPAIGN,
                "updated_at": ts,
            }
            await backend.patch(
                "customer_accounts",
                patch,
                params={"customer_id": f"eq.{customer_id}"},
            )
            updated += 1
        else:
            customer_id = f"cus_{secrets.token_urlsafe(10)}"
            await backend.insert(
                "customer_accounts",
                {
                    "customer_id": customer_id,
                    "legal_name": lead["legal_name"],
                    "trade_name": lead["legal_name"],
                    "contact_name": "Equipo comercial",
                    "email": email,
                    "phone": None,
                    "country_code": "CU",
                    "website": lead.get("funnel_url"),
                    "status": "PROSPECT",
                    "sales_status": sales_status,
                    "assigned_employee_id": None,
                    "source": CAMPAIGN,
                    "created_at": ts,
                    "updated_at": ts,
                },
            )
            created += 1

        audit_marker = f"{CAMPAIGN}:{lead['gmail_message_id']}"
        prior_audit = await backend.select(
            "customer_crm_audit",
            params={"customer_id": f"eq.{customer_id}", "event_type": "eq.outreach_sent", "limit": "100"},
        ) or []
        if any((row.get("payload") or {}).get("marker") == audit_marker for row in prior_audit):
            unchanged += 1
            continue

        await backend.insert(
            "customer_crm_audit",
            {
                "event_id": f"crm_{secrets.token_urlsafe(10)}",
                "customer_id": customer_id,
                "intake_id": None,
                "actor_role": "owner",
                "actor_id": "owner",
                "event_type": "outreach_sent" if sales_status != "DO_NOT_CONTACT" else "outreach_bounced",
                "summary": "Spanish Cuba MIPYME sourcing outreach sent" if sales_status != "DO_NOT_CONTACT" else "Spanish Cuba MIPYME outreach bounced; address removed from follow-up",
                "payload": {
                    "marker": audit_marker,
                    "campaign": lead["campaign"],
                    "sector": lead.get("sector"),
                    "gmail_message_id": lead["gmail_message_id"],
                    "funnel_url": lead["funnel_url"],
                    "outreach_status": lead["outreach_status"],
                },
                "created_at": ts,
            },
        )

    return {
        "campaign": CAMPAIGN,
        "seed_count": len(load_seed()),
        "created": created,
        "updated": updated,
        "audit_already_present": unchanged,
        "contactable_count": sum(1 for lead in load_seed() if _sales_status(lead) != "DO_NOT_CONTACT"),
        "do_not_contact_count": sum(1 for lead in load_seed() if _sales_status(lead) == "DO_NOT_CONTACT"),
    }
