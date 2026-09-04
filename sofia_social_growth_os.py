from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Literal

Platform = Literal["facebook", "instagram", "linkedin", "x", "tiktok", "youtube"]

SOFIA_IDENTITY = {
    "name": "Sofia Smith",
    "title": "Trade Concierge & Account Executive",
    "company": "SAHJONY LLC",
    "positioning": "Global trade, sourcing, logistics, supplier and buyer relationship management",
    "ownership": "SAHJONY LLC",
    "identity_policy": "Company-controlled commercial persona. Do not fabricate personal biography, credentials, residence, education or employment history.",
}

PLATFORMS: list[Platform] = ["facebook", "instagram", "linkedin", "x", "tiktok", "youtube"]

@dataclass
class SocialObjective:
    objective: str
    metric: str
    target: float
    horizon_days: int

@dataclass
class SocialAction:
    platform: Platform
    action: str
    purpose: str
    requires_human_authentication: bool = False
    requires_budget_approval: bool = False
    policy_gate: str | None = None


def social_identity() -> dict[str, Any]:
    return {**SOFIA_IDENTITY, "platforms": PLATFORMS}


def default_objectives() -> list[dict[str, Any]]:
    items = [
        SocialObjective("Generate qualified trade conversations", "qualified_conversations", 50, 30),
        SocialObjective("Convert social conversations into WhatsApp/email leads", "social_to_crm_conversion_rate", 0.20, 30),
        SocialObjective("Grow relevant B2B audience", "qualified_follower_growth", 0.10, 30),
        SocialObjective("Create RFQ-ready opportunities", "rfq_ready_from_social", 10, 30),
        SocialObjective("Maintain response discipline", "median_response_minutes", 15, 30),
    ]
    return [asdict(x) for x in items]


def autonomous_capabilities() -> dict[str, Any]:
    return {
        "content_planning": True,
        "multilingual_content_generation": True,
        "organic_post_drafting": True,
        "comment_reply_drafting": True,
        "dm_qualification": True,
        "lead_capture": True,
        "crm_handoff": True,
        "whatsapp_handoff": True,
        "email_handoff": True,
        "rfq_handoff": True,
        "relationship_memory_360": True,
        "social_listening": True,
        "opportunity_detection": True,
        "content_repurposing": True,
        "a_b_variant_generation": True,
        "performance_learning": True,
        "self_marketing": True,
        "self_selling": True,
        "self_healing": True,
        "platform_failover": True,
        "autonomous_paid_ad_spend": False,
        "mass_unsolicited_dm": False,
        "fake_personal_biography": False,
        "binding_offer_without_evidence": False,
    }


def account_activation_plan() -> list[dict[str, Any]]:
    """One-time platform account creation/login can require human verification.
    After connection, normal publishing/reply/lead workflows can be automated through approved APIs.
    """
    actions = [
        SocialAction("facebook", "Create or connect Sofia/SAHJONY professional presence", "Business discovery and Messenger/WhatsApp funnel", True),
        SocialAction("instagram", "Create or connect professional account", "Visual trade content and inbound DMs", True),
        SocialAction("linkedin", "Create company-approved employee/brand presence", "B2B buyers, suppliers and partnerships", True),
        SocialAction("x", "Create or connect business-facing account", "Trade intelligence and conversations", True),
        SocialAction("tiktok", "Create or connect business account", "Educational short-form demand generation", True),
        SocialAction("youtube", "Create or connect branded channel", "Long-form trade education and searchable authority", True),
    ]
    return [asdict(x) for x in actions]


def daily_operating_loop() -> dict[str, Any]:
    return {
        "cycle": [
            "Read platform inboxes, comments, mentions and performance data",
            "Load Relationship Memory 360 for known contacts",
            "Classify buyer/supplier/partner/service intent",
            "Prioritize conversations by commercial value and urgency",
            "Respond naturally using the contact's language and known context",
            "Move qualified conversations to WhatsApp/email/CRM/RFQ",
            "Generate and schedule educational/commercial organic content",
            "Measure engagement, qualified conversations, RFQ readiness and conversion",
            "Promote winning message patterns; retire weak variants",
            "Detect channel/API failures and route to recovery/fallback",
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def content_pillars() -> list[dict[str, str]]:
    return [
        {"pillar": "Buyer demand", "purpose": "Show how SAHJONY helps buyers source verified products and logistics"},
        {"pillar": "Supplier access", "purpose": "Recruit manufacturers, distributors and wholesalers"},
        {"pillar": "Trade education", "purpose": "Explain Incoterms, freight, documents, payment and compliance clearly"},
        {"pillar": "Deal intelligence", "purpose": "Discuss categories, markets and opportunities without inventing prices or availability"},
        {"pillar": "Proof and process", "purpose": "Show workflow, tracking, RFQ discipline and customer service"},
        {"pillar": "Partnerships", "purpose": "Recruit logistics, customs, sourcing and last-mile partners"},
    ]


def message_policy() -> dict[str, Any]:
    return {
        "tone": "human, concise, commercially intelligent, non-robotic",
        "identity": "Sofia Smith — Trade Concierge & Account Executive, SAHJONY LLC",
        "do": [
            "Answer inbound messages and legitimate existing relationships promptly",
            "Ask at most the fewest questions needed to advance the opportunity",
            "Use known relationship context and avoid repeated questions",
            "Offer a clear next step: WhatsApp, email, call, RFQ or meeting",
            "Respect opt-outs and platform messaging windows",
            "Use verified evidence for pricing, availability, compliance and commitments",
        ],
        "dont": [
            "Send bulk unsolicited direct messages",
            "Invent customers, testimonials, certifications, deals, prices or inventory",
            "Claim a fabricated personal life or professional history",
            "Purchase ads or spend company funds without authorization",
            "Release binding commercial terms without required evidence/decision gates",
        ],
    }


def social_health() -> dict[str, Any]:
    return {
        "status": "ready_for_account_connections",
        "service": "sofia-social-growth-os",
        "version": "1.0.0",
        "identity": social_identity(),
        "autonomy": autonomous_capabilities(),
        "objectives": default_objectives(),
        "content_pillars": content_pillars(),
        "activation": account_activation_plan(),
        "policy": message_policy(),
        "operating_loop": daily_operating_loop(),
        "note": "Actual social account creation and API authorization may require one-time platform login, verification or acceptance by the human business owner. Once connected, the operating layer is designed for autonomous ongoing management within platform and company policy.",
    }
