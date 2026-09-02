from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

OwnerMode = Literal["personal", "business", "blended"]

PERSONAL_DOMAINS = {
    "calendar": ["schedule", "reminders", "conflict_detection", "time_blocking"],
    "communications": ["drafting", "summaries", "follow_up", "contact_preparation"],
    "travel": ["research", "itineraries", "checklists", "change_monitoring"],
    "household": ["task_planning", "renewal_reminders", "document_checklists"],
    "learning": ["research", "briefings", "study_plans", "knowledge_capture"],
    "wellbeing": ["routine_planning", "appointment_reminders", "non_medical_tracking"],
}

BUSINESS_DOMAINS = {
    "executive": ["daily_brief", "decision_support", "priority_management"],
    "sales": ["pipeline", "qualification", "follow_up", "proposal_preparation"],
    "operations": ["missions", "exceptions", "vendors", "delivery_tracking"],
    "finance": ["analysis", "reconciliation", "cash_visibility", "margin_review"],
    "application": ["health", "incidents", "deployments", "data_quality"],
}

OWNER_ASSISTANT_CONTRACT = {
    "owner_id": "juan-gonzalez",
    "owner_name": "Juan Gonzalez",
    "assistant": "Sofia Reyes",
    "relationship": "private_personal_assistant_and_business_chief_of_staff",
    "access_cost": 0,
    "availability": "24x7",
    "default_timezone": "America/Chicago",
    "private_workspace": True,
    "personal_domains": PERSONAL_DOMAINS,
    "business_domains": BUSINESS_DOMAINS,
    "privacy": {
        "personal_data_visibility": "owner_only",
        "business_data_visibility": "owner_and_explicitly_authorized_business_roles",
        "cross_context_disclosure": "prohibited_without_owner_direction",
        "credentials_and_secrets": "never_reveal",
    },
}


def classify_owner_request(request: str, requested_mode: OwnerMode | None = None) -> OwnerMode:
    if requested_mode:
        return requested_mode
    text = request.lower()
    personal = any(word in text for word in ("personal", "family", "home", "trip", "travel", "doctor", "appointment", "birthday"))
    business = any(word in text for word in ("business", "sale", "customer", "supplier", "shipment", "invoice", "app", "deployment"))
    if personal and business:
        return "blended"
    return "personal" if personal else "business"


def build_owner_mission(request: str, requested_mode: OwnerMode | None = None) -> dict[str, Any]:
    mode = classify_owner_request(request, requested_mode)
    private = mode in {"personal", "blended"}
    return {
        "owner_id": "juan-gonzalez",
        "mode": mode,
        "request": request,
        "visibility": "owner" if private else "internal",
        "data_partition": "owner_private" if private else "business",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "success_criteria": [
            "answer Juan's request directly",
            "separate verified facts from assumptions",
            "record concrete next actions and deadlines",
            "preserve personal privacy and business confidentiality",
        ],
        "execution_policy": {
            "research_and_drafting": "autonomous",
            "reversible_owner_workspace_actions": "autonomous",
            "external_messages_or_bookings": "confirm_when_scope_or_recipient_is_ambiguous",
            "money_legal_medical_security_or_irreversible_actions": "explicit_owner_confirmation",
        },
    }
