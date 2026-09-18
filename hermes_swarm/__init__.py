"""Hermes Agent Swarm — design scaffold (NOT live).

A Python port of the GEV workforce-core governance contract for SAHJONY's
WhatsApp transport. Agents read, classify, draft, enrich, and escalate.
No agent sends: the only send path is the existing governed outbox workflow,
which is invoked solely by Juan's per-message dispatch. This package holds
no credentials and contains no network code.

Status: DESIGNED. The swarm goes live ONLY on Juan's explicit word.
"""

from hermes_swarm.governance import (
    AGENT_TIERS,
    ESCALATION_QUEUE_KEY,
    LOG_CAP,
    LANG_POLICY,
    SANCTIONS_HARD_STOP,
    Draft,
    ReviewResult,
    check_sanctions,
    classify_track,
    default_roster,
    escalate,
    log_action,
    register_workforce,
    review_draft,
)

__all__ = [
    "AGENT_TIERS",
    "ESCALATION_QUEUE_KEY",
    "LOG_CAP",
    "LANG_POLICY",
    "SANCTIONS_HARD_STOP",
    "Draft",
    "ReviewResult",
    "check_sanctions",
    "classify_track",
    "default_roster",
    "escalate",
    "log_action",
    "register_workforce",
    "review_draft",
]
