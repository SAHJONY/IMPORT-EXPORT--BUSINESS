from __future__ import annotations

from typing import Any

RESEARCH_FALLBACK_CHAIN = [
    "PRIMARY_SOURCES",
    "SECONDARY_SOURCES",
    "CRM_INTELLIGENCE",
    "ALTERNATE_SEARCH_PROVIDER",
    "PUBLIC_DIRECTORIES",
    "TRADE_RECORDS",
    "MANUAL_SOURCE_QUEUE",
]

OWNER_ESCALATION_ONLY = {
    "BINDING_CONTRACT",
    "PAYMENT_AUTHORIZATION",
    "LEGAL_COMMITMENT",
    "COMPLIANCE_CRITICAL_APPROVAL",
    "COUNTERPARTY_DISCLOSURE_APPROVAL",
    "CREDENTIAL_OR_ACCESS_ONLY_OWNER_CAN_PROVIDE",
}

RESEARCH_NEVER_OWNER_BLOCKER = {
    "WEB_SEARCH_UNAVAILABLE",
    "SEARCH_PROVIDER_UNCONFIGURED",
    "SINGLE_SOURCE_UNAVAILABLE",
    "SEARCH_RATE_LIMIT",
    "NO_INITIAL_BUYER_NAME",
    "NO_INITIAL_SUPPLIER_NAME",
}


def research_policy() -> dict[str, Any]:
    return {
        "policy_id": "SOFIA_NO_OWNER_DEPENDENCY_FOR_RESEARCH_V1",
        "mode": "AUTONOMOUS_NONBINDING",
        "fallback_chain": RESEARCH_FALLBACK_CHAIN,
        "owner_escalation_only": sorted(OWNER_ESCALATION_ONLY),
        "research_never_owner_blocker": sorted(RESEARCH_NEVER_OWNER_BLOCKER),
        "rules": [
            "Do not ask the owner to provide a buyer, supplier, or public-market lead merely because one research provider is unavailable.",
            "Continue through the research fallback chain until credible candidates or a documented exhausted-source result is produced.",
            "Keep discovered counterparties at RESEARCH until demand, authority, KYB and commercial evidence support promotion.",
            "Do not fabricate counterparties, demand, quotations, pricing, KYB, payment capability or revenue.",
            "Do not disclose protected counterparties, sign contracts, authorize payments, or make binding commitments without owner approval.",
            "When no source can be queried automatically, create a manual-source research queue rather than transferring research responsibility to the owner.",
        ],
    }


def research_next_action(*, has_contact: bool, has_verified_demand: bool, provider_available: bool = True) -> str:
    if has_verified_demand:
        return "Continue autonomous non-binding buyer/supplier matching, evidence collection, KYB preparation and commercial comparison."
    if has_contact:
        return "Enrich the lead, verify business identity and determine whether current demand exists; keep stage at RESEARCH until evidenced."
    if not provider_available:
        return "Continue through alternate public-source, CRM, directory and trade-record research paths; queue manual-source work if automation is exhausted."
    return "Research and verify a legitimate business contact and current trade need without requesting the owner to source the lead."
