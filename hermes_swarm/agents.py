"""The 7 Hermes swarm agents.

Each agent declares: role, tier, allowed_reads (named API references —
no URLs, no secrets), allowed_writes (scoped), and a draft() interface
that returns Draft objects (governance.Draft).

STRUCTURAL GUARANTEE: SwarmAgent.__init_subclass__ refuses to create any
subclass that defines a send/enqueue/deliver-style method. Combined with
the absence of an execute tier in AGENT_TIERS, of credentials, and of a
transport client, it is structurally impossible for an agent to reach the
wire. The ONLY path to the wire is the existing governed outbox workflow,
dispatched explicitly by Juan, one message at a time — and this package
cannot invoke it.

Named API references used below (defined in the transport, NOT in this
package):
- inbound event stream      signed Hermes event webhook consumer
                            (POST /whatsapp/hermes/events)
- recovery backlog          GET /whatsapp/recovery/backlog
- outbox status             GET /whatsapp/hermes/outbox/status (read-only)
- get_contact_context       CRM bridge read: crm_contact_360
- sync_contact              CRM bridge write, lead_sync scope only
- add_note                  CRM bridge write, internal_note scope only
- create_trade_intake       CRM bridge write, trade_intake scope only

Transport floors inherited by every agent: destructive_scope=false,
external_commitment_scope=false. The swarm cannot widen them.
"""

from __future__ import annotations

import itertools
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from hermes_swarm.governance import (
    AGENT_TIERS,
    Draft,
    check_sanctions,
    classify_track,
    escalate,
    log_action,
    review_draft,
    track_language,
)

_FORBIDDEN_METHOD_RE = re.compile(r"(send|enqueue|dispatch|transmit|deliver|post_outbound)")


class SwarmHalted(RuntimeError):
    """Raised when drafting is attempted while the kill switch is engaged."""


class SwarmAgent(ABC):
    """Base class for all swarm agents.

    Subclasses declare class attributes:
      agent_id       stable identifier (e.g. 'inbox-triage')
      role           human role name
      tier           one of AGENT_TIERS values (read / draft / propose)
      allowed_reads  tuple of NAMED API references (no URLs/secrets)
      allowed_writes tuple of scoped write descriptions
    and implement draft(context) -> Draft | None.
    """

    agent_id: str = ""
    role: str = ""
    tier: str = ""
    allowed_reads: tuple[str, ...] = ()
    allowed_writes: tuple[str, ...] = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Structural ban: no send-path method may ever exist on an agent.
        for name in dir(cls):
            if _FORBIDDEN_METHOD_RE.search(name):
                raise TypeError(
                    f"hermes_swarm: agent '{cls.__name__}' defines forbidden "
                    f"send-path method '{name}'. Agents may draft, never send."
                )
        if cls.tier not in frozenset(AGENT_TIERS.values()):
            raise TypeError(
                f"hermes_swarm: agent '{cls.__name__}' has invalid tier "
                f"'{cls.tier}'. There is no execute tier."
            )

    @abstractmethod
    def draft(self, context: "AgentContext") -> Draft | None:
        """Produce a Draft from the given context, or None when there is
        nothing safe to draft. Pure data out — no side effects here."""
        raise NotImplementedError

    def describe(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "tier": self.tier,
            "allowed_reads": list(self.allowed_reads),
            "allowed_writes": list(self.allowed_writes),
        }


@dataclass
class AgentContext:
    """Everything an agent may read for one conversation. One conversation
    carries exactly one track; agents never read across tracks.

    NOTE: no address/registration fields — Blocker #4 stays shelved.
    """

    conversation_id: str
    phone: str  # customer phone, as given by the transport
    track: str
    lang: str  # 'es-first' | 'bilingual'
    inbound_text: str
    history: list[dict] = field(default_factory=list)
    contact_context: dict = field(default_factory=dict)  # from get_contact_context
    pipeline_snapshot: dict = field(default_factory=dict)  # deal-desk context
    window_state: dict = field(default_factory=dict)  # 24h window, opt-out, rate
    metadata: dict = field(default_factory=dict)


_draft_counter = itertools.count(1)


def _new_draft(agent: SwarmAgent, context: AgentContext, text: str, kind: str,
               metadata: dict | None = None) -> Draft:
    return Draft(
        draft_id=f"draft-{next(_draft_counter):06d}",
        agent_id=agent.agent_id,
        role=agent.role,
        tier=agent.tier,
        track=context.track,
        lang=context.lang,
        text=text,
        kind=kind,
        metadata={"conversation_id": context.conversation_id,
                  **(metadata or {})},
    )


# ---------------------------------------------------------------------------
# 1. inbox-triage — READ
# ---------------------------------------------------------------------------


class InboxTriage(SwarmAgent):
    """Every inbound message classified: track, language, priority, intent;
    routes to the right specialist; spam/opt-out filtered."""

    agent_id = "inbox-triage"
    role = "Inbox triage"
    tier = AGENT_TIERS["READ"]
    allowed_reads = (
        "inbound event stream (signed Hermes event webhook consumer)",
        "recovery backlog (GET /whatsapp/recovery/backlog)",
    )
    allowed_writes = (
        "triage queue entry (track label, language, priority, intent)",
        "track label on conversation record",
    )

    def draft(self, context: AgentContext) -> Draft | None:
        track = classify_track(context.inbound_text)
        priority = self._priority(context.inbound_text, context.window_state)
        decision = {
            "track": track,
            "lang": track_language(track),
            "priority": priority,
            "intent": self._intent(context.inbound_text),
            "sanctions_hit": check_sanctions(context.inbound_text),
        }
        log_action("hermes", self.agent_id, {"triaged": decision,
                                             "conversation": context.conversation_id})
        return _new_draft(
            self, context,
            text=f"[triage] track={track} priority={priority} intent={decision['intent']}",
            kind="note",
            metadata={"decision": decision},
        )

    @staticmethod
    def _priority(text: str, window_state: dict) -> str:
        lowered = text.lower()
        if window_state.get("opted_out"):
            return "suppressed"
        if check_sanctions(text):
            return "urgent-sanctions"
        if any(w in lowered for w in ("urgente", "urgent", "ahora", "ya mismo")):
            return "high"
        return "normal"

    @staticmethod
    def _intent(text: str) -> str:
        lowered = text.lower()
        if any(w in lowered for w in ("precio", "price", "cuanto", "cotiz")):
            return "pricing"
        if any(w in lowered for w in ("hola", "buenos", "buenas", "hello", "hi")):
            return "greeting"
        if "stop" in lowered or "no me escriba" in lowered or "baja" in lowered:
            return "opt-out"
        return "general"


# ---------------------------------------------------------------------------
# 2. customer-care — DRAFT
# ---------------------------------------------------------------------------


class CustomerCare(SwarmAgent):
    """Drafts answers to customer questions from verified facts only.
    Spanish-first on cuba/cars/energy tracks. Sofia's voice, always."""

    agent_id = "customer-care"
    role = "Customer care"
    tier = AGENT_TIERS["DRAFT"]
    allowed_reads = (
        "conversation history",
        "get_contact_context (CRM bridge read: crm_contact_360)",
    )
    allowed_writes = (
        "reply drafts in Sofia voice (approval queue only — never the wire)",
    )

    def draft(self, context: AgentContext) -> Draft | None:
        if check_sanctions(context.inbound_text):
            # Never answer sanctions/customs/embargo questions.
            escalate("hermes", "sanctions",
                     {"agent": self.agent_id, "text": context.inbound_text,
                      "conversation": context.conversation_id})
            return None
        facts = self._verified_facts(context)
        if context.lang == "es-first":
            text = (
                "Hola, soy Sofia de SAHJONY. Gracias por escribirnos. "
                f"{facts} ¿En qué más le puedo ayudar?"
            )
        else:
            text = (
                "Hello, this is Sofia from SAHJONY. Thanks for reaching out. "
                f"{facts} How else can I help?"
            )
        return _new_draft(self, context, text=text, kind="reply",
                          metadata={"voice": "sofia", "facts_source": "verified-only"})

    @staticmethod
    def _verified_facts(context: AgentContext) -> str:
        # STUB: real facts come from get_contact_context + pipeline snapshot
        # at wiring time. The scaffold never invents facts.
        known = context.contact_context.get("known_facts") or []
        if not known:
            if context.lang == "es-first":
                return "Estoy revisando su caso con la información que tenemos registrada."
            return "I'm reviewing your case with the information we have on record."
        return " ".join(str(f) for f in known)


# ---------------------------------------------------------------------------
# 3. lead-qualification — DRAFT
# ---------------------------------------------------------------------------


class LeadQualification(SwarmAgent):
    """Scores/enriches new leads. Never invents contact data — only
    business-controlled sources (official website, official page) or Juan."""

    agent_id = "lead-qualification"
    role = "Lead qualification"
    tier = AGENT_TIERS["DRAFT"]
    allowed_reads = (
        "get_contact_context (CRM bridge read: crm_contact_360)",
        "lead records (per-track, no cross-track reads)",
    )
    allowed_writes = (
        "sync_contact (lead_sync scope only — never destructive)",
        "qualification score draft",
    )

    def draft(self, context: AgentContext) -> Draft | None:
        score = self._score(context)
        return _new_draft(
            self, context,
            text=f"[qualification] score={score}/100 track={context.track}",
            kind="note",
            metadata={"qualification_score": score,
                      "write_scope": "lead_sync (sync_contact)"},
        )

    @staticmethod
    def _score(context: AgentContext) -> int:
        score = 20  # baseline: real inbound contact
        contact = context.contact_context or {}
        if contact.get("has_business_profile"):
            score += 25
        if contact.get("prior_conversation"):
            score += 20
        if context.track != "unknown":
            score += 15
        text = context.inbound_text.lower()
        if any(w in text for w in ("comprar", "buy", "quiero", "necesito", "precio")):
            score += 20
        return min(score, 100)


# ---------------------------------------------------------------------------
# 4. follow-up — DRAFT
# ---------------------------------------------------------------------------


class FollowUp(SwarmAgent):
    """Drafts re-engagement inside the 24h session window. Respects
    opt-out and rate limits. Never blasts — one draft per conversation."""

    agent_id = "follow-up"
    role = "Follow-up"
    tier = AGENT_TIERS["DRAFT"]
    allowed_reads = (
        "dormant conversation list",
        "24h-window state (session/opt-out/rate)",
    )
    allowed_writes = (
        "follow-up drafts (approval queue only — never the wire)",
    )

    def draft(self, context: AgentContext) -> Draft | None:
        window = context.window_state or {}
        if window.get("opted_out"):
            return None  # suppressed, logged by triage
        if not window.get("within_24h_window", True):
            escalate("hermes", "window-expired",
                     {"agent": self.agent_id,
                      "conversation": context.conversation_id})
            return None
        if window.get("recently_contacted"):
            return None  # rate limit: one draft per conversation
        if context.lang == "es-first":
            text = (
                "Hola, le escribe Sofia de SAHJONY. Quería retomar nuestra "
                "conversación — ¿sigo ayudándole con su solicitud?"
            )
        else:
            text = (
                "Hello, Sofia from SAHJONY here. Just following up on our "
                "conversation — shall I keep helping with your request?"
            )
        return _new_draft(self, context, text=text, kind="followup",
                          metadata={"window": "24h", "blast": False})


# ---------------------------------------------------------------------------
# 5. deal-desk — READ
# ---------------------------------------------------------------------------


class DealDesk(SwarmAgent):
    """Pulls live per-track pipeline state (GEV module stores via shared
    API) so drafts reference real pipeline state — e.g. the rice/diesel
    inquiry status. Read-only: it writes deal briefs, never messages."""

    agent_id = "deal-desk"
    role = "Deal desk"
    tier = AGENT_TIERS["READ"]
    allowed_reads = (
        "per-track pipeline state (GEV module stores, shared API)",
    )
    allowed_writes = (
        "deal briefs (context for other agents' drafts)",
        "economics summaries (internal)",
    )

    def draft(self, context: AgentContext) -> Draft | None:
        snapshot = context.pipeline_snapshot or {}
        if not snapshot:
            return None  # no pipeline state -> nothing to brief
        lines = [f"[deal-brief] track={context.track}"]
        for key, value in snapshot.items():
            lines.append(f"  {key}: {value}")
        return _new_draft(self, context, text="\n".join(lines), kind="brief",
                          metadata={"snapshot_keys": sorted(snapshot)})


# ---------------------------------------------------------------------------
# 6. outreach-drafting — DRAFT
# ---------------------------------------------------------------------------


class OutreachDrafting(SwarmAgent):
    """Drafts proactive outreach from Juan-approved sources only. Every
    draft carries a cold-recipient ban-risk note. Drafts never send —
    they wait in the approval queue for Juan's per-message word."""

    agent_id = "outreach-drafting"
    role = "Outreach drafting"
    tier = AGENT_TIERS["DRAFT"]
    allowed_reads = (
        "lead/partner lists (Juan-approved sources only)",
    )
    allowed_writes = (
        "outreach drafts (approval queue only — never the wire)",
    )

    BAN_RISK_NOTE_ES = (
        "Nota de riesgo: envío a contacto frío — revisar ventana de 24h, "
        "opt-out y límites anti-bloqueo antes de aprobar."
    )
    BAN_RISK_NOTE_EN = (
        "Risk note: cold-recipient outreach — check 24h window, opt-out, "
        "and anti-ban limits before approving."
    )

    def draft(self, context: AgentContext) -> Draft | None:
        if not context.metadata.get("source_juan_approved"):
            # Only Juan-approved sources may seed outreach.
            return None
        if context.lang == "es-first":
            text = (
                "Hola, soy Sofia de SAHJONY. Trabajamos con importadores y "
                "MIPYMEs conectándolos con proveedores verificados. "
                "¿Le interesaría recibir una cotización sin compromiso?\n\n"
                f"{self.BAN_RISK_NOTE_ES}"
            )
        else:
            text = (
                "Hello, this is Sofia from SAHJONY. We connect importers "
                "with verified suppliers. Would you like a no-commitment quote?\n\n"
                f"{self.BAN_RISK_NOTE_EN}"
            )
        return _new_draft(self, context, text=text, kind="outreach",
                          metadata={"ban_risk_note": True,
                                    "source": "juan-approved"})


# ---------------------------------------------------------------------------
# 7. compliance-gate — READ + escalate
# ---------------------------------------------------------------------------


class GateVerdict:
    """Result of ComplianceGate.review()."""

    def __init__(self, status: str, flags: list, escalations: list) -> None:
        assert status in ("pass", "hold")
        self.status = status
        self.flags = flags
        self.escalations = escalations

    def to_dict(self) -> dict:
        return {"status": self.status, "flags": self.flags,
                "escalations": self.escalations}


class ComplianceGate(SwarmAgent):
    """Hard-stop gate. Reviews every draft with review_draft() plus
    session/opt-out/rate/sanctions checks. NOTHING advances past it
    without passing. Any red flag -> draft HELD + escalate to Juan
    immediately. The gate cannot be skipped, configured off, or
    overruled by another agent."""

    agent_id = "compliance-gate"
    role = "Compliance gate"
    tier = AGENT_TIERS["READ"]
    allowed_reads = (
        "draft queue",
        "session/opt-out/rate-limit state",
        "outbox status (read-only delivery tracking)",
    )
    allowed_writes = (
        "add_note (internal_note scope only — never destructive)",
        "escalations to Juan",
    )

    def draft(self, context: AgentContext) -> Draft | None:
        # The gate drafts nothing customer-facing; it only reviews.
        # It still implements the interface (returns None) so the
        # coordinator can treat every agent uniformly.
        return None

    def review(self, draft: Draft, checks: dict) -> GateVerdict:
        """review(draft, checks) -> GateVerdict.

        checks: { source_text, opted_out, within_24h_window, rate_ok }.
        Any red flag -> hold + escalate. Never answers, never overrides.
        """
        checks = checks or {}
        flags: list[dict] = []
        escalations: list[dict] = []

        def hold(code: str, es: str, en: str, escalate_reason: str) -> None:
            flags.append({"code": code, "es": es, "en": en})
            item = escalate(
                "hermes", escalate_reason,
                {"agent": "compliance-gate", "draft_id": draft.draft_id,
                 "flag": code, "track": draft.track})
            escalations.append(item)

        # 1. Invented-commitment review on the draft text.
        result = review_draft(draft)
        for flag in result.flags:
            hold(flag.code, flag.es, flag.en, "draft-flag")

        # 2. Sanctions hard stop — on source text AND draft text.
        for text in (checks.get("source_text") or "", draft.text or ""):
            if check_sanctions(text):
                hold("SANCTIONS_HARD_STOP",
                     "Tema de sanciones/aduanas/embargo: el agente NUNCA responde; escala a Juan siempre.",
                     "Sanctions/customs/embargo topic: the agent NEVER answers; always escalates to Juan.",
                     "sanctions")
                break

        # 3. Opt-out respect.
        if checks.get("opted_out"):
            hold("OPT_OUT",
                 "El contacto pidió no recibir mensajes: borrador retenido.",
                 "Contact opted out: draft held.",
                 "opt-out")

        # 4. 24h session window.
        if checks.get("within_24h_window") is False:
            hold("WINDOW_EXPIRED",
                 "Ventana de 24h vencida: el borrador no puede avanzar sin revisión de Juan.",
                 "24h window expired: draft cannot advance without Juan's review.",
                 "window-expired")

        # 5. Rate / anti-blast.
        if checks.get("rate_ok") is False:
            hold("RATE_LIMIT",
                 "Límite de frecuencia/anti-bloqueo: borrador retenido.",
                 "Rate/anti-blast limit: draft held.",
                 "rate-limit")

        status = "hold" if flags else "pass"
        log_action("hermes", self.agent_id,
                   {"reviewed": draft.draft_id, "verdict": status,
                    "flags": [f["code"] for f in flags]})
        return GateVerdict(status=status, flags=flags, escalations=escalations)


#: The full roster, in pipeline order.
AGENTS: tuple[type[SwarmAgent], ...] = (
    InboxTriage,
    CustomerCare,
    LeadQualification,
    FollowUp,
    DealDesk,
    OutreachDrafting,
    ComplianceGate,
)


def build_roster() -> list[SwarmAgent]:
    """Instantiate the 7 agents."""
    return [cls() for cls in AGENTS]
