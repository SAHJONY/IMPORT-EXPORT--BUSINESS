from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

BLOCKED_STATUSES = {"DO_NOT_CONTACT", "OPTED_OUT", "LOST"}
ACTIVE_STATUSES = {"NEW", "PROSPECT", "FOLLOW_UP_DUE", "REPLIED", "QUALIFIED_LEAD"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _consented(lead: dict[str, Any]) -> bool:
    consent = lead.get("consent_to_business_contact")
    if consent is True:
        return True
    return _text(lead.get("consent_status")).upper() in {"CONSENTED", "TRANSACTIONAL_ONLY"}


def score_crm_lead(lead: dict[str, Any], *, has_intake: bool = False) -> dict[str, Any]:
    status = _text(lead.get("sales_status") or lead.get("status") or "NEW").upper()
    blocked = status in BLOCKED_STATUSES or _text(lead.get("consent_status")).upper() in {"REVOKED", "DO_NOT_CONTACT"}
    contactable = bool(_text(lead.get("email")) or _text(lead.get("phone")))
    consented = _consented(lead)
    components = {
        "active_status": 20 if status in ACTIVE_STATUSES else 5,
        "contactability": 20 if contactable else 0,
        "business_identity": 15 if _text(lead.get("legal_name") or lead.get("business_name") or lead.get("buyer_company")) else 0,
        "commercial_need": 25 if has_intake or _text(lead.get("product_need") or lead.get("product_description")) else 0,
        "engagement": 15 if status in {"REPLIED", "QUALIFIED_LEAD", "FOLLOW_UP_DUE"} else 0,
        "consent": 5 if consented else 0,
    }
    score = 0 if blocked else min(100, sum(components.values()))
    if blocked:
        next_action = "Do not contact; preserve suppression state."
    elif has_intake:
        next_action = "Qualify the trade requirement and prepare the sourcing path."
    elif not contactable:
        next_action = "Research and verify a legitimate business contact route."
    elif consented:
        next_action = "Prepare a personalized, non-binding Sofia follow-up."
    else:
        next_action = "Research and queue for owner-reviewed outreach; no autonomous message."
    return {
        "score": score,
        "components": components,
        "status": status,
        "blocked": blocked,
        "contactable": contactable,
        "consented": consented,
        "autonomous_outreach_allowed": bool(contactable and consented and not blocked),
        "next_best_action": next_action,
    }


def build_growth_queue(accounts: list[dict[str, Any]], intakes: list[dict[str, Any]], external: list[dict[str, Any]], whatsapp: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    intake_ids = {str(row.get("customer_id")) for row in intakes if row.get("customer_id")}
    queue: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, rows in (("customer_crm", accounts), ("external_research", external), ("whatsapp_crm", whatsapp or [])):
        for lead in rows:
            identity = _text(lead.get("customer_id") or lead.get("id") or lead.get("lead_id") or lead.get("email") or lead.get("phone"))
            if not identity or identity in seen:
                continue
            seen.add(identity)
            assessment = score_crm_lead(lead, has_intake=identity in intake_ids)
            queue.append({
                "lead_ref": identity,
                "source": source,
                "company": _text(lead.get("legal_name") or lead.get("business_name") or lead.get("buyer_company") or lead.get("buyer_name")),
                "contact_name": _text(lead.get("contact_name") or lead.get("buyer_name")),
                "country": _text(lead.get("country_code") or lead.get("buyer_country") or lead.get("destination")),
                "assessment": assessment,
            })
    queue.sort(key=lambda row: (-int(row["assessment"]["score"]), row["lead_ref"]))
    return queue


def growth_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "sofia-crm-growth-engine",
        "primary_brain": "gpt-5.6-sol",
        "anthropic_role": "independent_review_for_high_risk_or_ambiguous_leads",
        "crm_sources": ["customer_accounts", "customer_trade_intakes", "external_trade_prospects", "whatsapp_leads"],
        "capabilities": ["deduplicate", "score", "prioritize", "research", "qualify", "prepare_outreach", "schedule_follow_up"],
        "consent_enforced": True,
        "opt_out_enforced": True,
        "unsolicited_autonomous_outreach": False,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
