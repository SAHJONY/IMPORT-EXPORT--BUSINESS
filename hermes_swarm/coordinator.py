"""Coordinator — the swarm event flow as an explicit state machine.

Flow:
  INBOUND -> TRIAGED -> ROUTED -> DRAFTED -> GATED -> QUEUED
      -> (Juan approves: explicit external input) -> APPROVED -> DONE

Key properties:
- The approval queue is a DATA STRUCTURE. "Juan approves" is an explicit
  external input (ApprovalInput); the queue NEVER auto-advances. Silence
  is never consent. No timers, no defaults, no bulk.
- Kill switch: while halted, all drafting raises SwarmHalted; in-flight
  drafts stay drafts; nothing sends. Fail-closed, never fail-open.
- The coordinator performs NO network I/O. Handlers that will talk to the
  transport at go-live are stubbed and clearly marked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from hermes_swarm import agents as agents_module
from hermes_swarm.agents import (
    AgentContext,
    ComplianceGate,
    SwarmAgent,
    SwarmHalted,
    build_roster,
)
from hermes_swarm.audit import AuditLog
from hermes_swarm.governance import Draft, check_sanctions, escalate, log_action


class Stage(Enum):
    INBOUND = "inbound"
    TRIAGED = "triaged"
    ROUTED = "routed"
    DRAFTED = "drafted"
    GATED = "gated"
    QUEUED = "queued"
    APPROVED = "approved"
    DONE = "done"


@dataclass
class QueuedDraft:
    draft: Draft
    gate_verdict: dict
    stage: Stage = Stage.QUEUED
    queued_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ApprovalInput:
    """Explicit external input from Juan. The ONLY thing that moves a
    queued draft to APPROVED. Must name the approver, the draft, and the
    decision — a missing or ambiguous input advances nothing."""

    approver: str
    draft_id: str
    decision: str  # 'approved' | 'rejected'
    note: str = ""

    def is_valid_approval(self) -> bool:
        return (
            bool(self.approver and self.approver.strip())
            and bool(self.draft_id and self.draft_id.strip())
            and self.decision == "approved"
        )


class ApprovalQueue:
    """Juan's approval inbox. Drafts enter only after the compliance gate
    passes. Drafts leave only via an explicit ApprovalInput from Juan.
    process() with no input is a no-op by design."""

    def __init__(self, audit: AuditLog | None = None) -> None:
        self._pending: dict[str, QueuedDraft] = {}
        self._audit = audit

    def submit(self, draft: Draft, gate_verdict: dict) -> QueuedDraft:
        if gate_verdict.get("status") != "pass":
            raise ValueError(
                "ApprovalQueue.submit: only gate-passed drafts may enter "
                f"the queue (draft {draft.draft_id} verdict "
                f"{gate_verdict.get('status')})."
            )
        queued = QueuedDraft(draft=draft, gate_verdict=gate_verdict)
        self._pending[draft.draft_id] = queued
        if self._audit:
            self._audit.append("queued_for_approval", {
                "draft_id": draft.draft_id, "agent": draft.agent_id,
                "track": draft.track})
        return queued

    def process(self, approval: ApprovalInput | None = None) -> list[QueuedDraft]:
        """Advance NOTHING unless a valid ApprovalInput is supplied.

        Returns the list of drafts that moved to APPROVED (0 or 1).
        Rejection removes the draft from the queue without approving it.
        """
        if approval is None:
            return []  # no input -> no movement, ever
        queued = self._pending.get(approval.draft_id)
        if queued is None:
            return []
        if approval.decision == "rejected" and approval.approver.strip():
            del self._pending[approval.draft_id]
            if self._audit:
                self._audit.append("approval_rejected", {
                    "draft_id": approval.draft_id, "by": approval.approver,
                    "note": approval.note})
            return []
        if not approval.is_valid_approval():
            return []
        del self._pending[approval.draft_id]
        queued.stage = Stage.APPROVED
        if self._audit:
            self._audit.append("approved", {
                "draft_id": approval.draft_id, "by": approval.approver,
                "note": approval.note})
        return [queued]

    def pending(self) -> list[QueuedDraft]:
        return list(self._pending.values())

    def __len__(self) -> int:
        return len(self._pending)


class KillSwitch:
    """Kill switch semantics: stop() halts ALL drafting immediately.
    In-flight drafts stay drafts. Nothing sends. resume() is a deliberate,
    logged act — and even after resume, queued drafts still need Juan's
    per-message approval; resume never approves anything."""

    def __init__(self, audit: AuditLog | None = None) -> None:
        self._halted = False
        self._audit = audit

    @property
    def halted(self) -> bool:
        return self._halted

    def stop(self, reason: str = "") -> None:
        self._halted = True
        log_action("hermes", "kill-switch", {"action": "stop", "reason": reason})
        if self._audit:
            self._audit.append("kill_switch_stop", {"reason": reason})

    def resume(self, reason: str = "") -> None:
        self._halted = False
        log_action("hermes", "kill-switch", {"action": "resume", "reason": reason})
        if self._audit:
            self._audit.append("kill_switch_resume", {"reason": reason})

    def check(self) -> None:
        if self._halted:
            raise SwarmHalted(
                "Kill switch engaged: all drafting halted. Drafts stay drafts."
            )


class SwarmCoordinator:
    """Runs the event flow. Constructed with an AuditLog; all stages are
    audit-logged. Transport I/O handlers are STUBBED (see _stub_*) — they
    will be wired only after Juan's go-live word."""

    MODULE = "hermes"

    def __init__(self, audit: AuditLog | None = None) -> None:
        self.audit = audit if audit is not None else AuditLog()
        self.queue = ApprovalQueue(audit=self.audit)
        self.kill_switch = KillSwitch(audit=self.audit)
        self.roster: list[SwarmAgent] = build_roster()
        self.gate: ComplianceGate = next(
            a for a in self.roster if isinstance(a, ComplianceGate))
        self._conversations: dict[str, AgentContext] = {}

    # -- pipeline --------------------------------------------------------

    def handle_inbound(self, event: dict) -> AgentContext:
        """INBOUND -> TRIAGED -> ROUTED. Returns the routed AgentContext.

        event: { conversation_id, phone, text, window_state?, history?,
                 contact_context?, pipeline_snapshot?, metadata? }
        """
        self.kill_switch.check()
        conversation_id = str(event.get("conversation_id") or "").strip()
        if not conversation_id:
            raise ValueError("handle_inbound requires event['conversation_id']")
        text = str(event.get("text") or "")

        # Hard stop FIRST, before any other processing.
        if check_sanctions(text):
            escalate(self.MODULE, "sanctions",
                     {"text": text, "conversation": conversation_id})
            self.audit.append("sanctions_hard_stop",
                             {"conversation": conversation_id})
            # Still build the context so the hold is fully traceable, but
            # mark the conversation so no specialist drafts an answer.
            context = self._build_context(event, track="unknown",
                                          sanctions_hold=True)
            self._conversations[conversation_id] = context
            return context

        triage = next(a for a in self.roster
                      if a.agent_id == "inbox-triage")
        context = self._build_context(event)
        triage_draft = triage.draft(context)
        assert triage_draft is not None
        decision = triage_draft.metadata["decision"]
        triage_draft.track = decision["track"]
        triage_draft.lang = decision["lang"]
        context.track = decision["track"]
        context.lang = decision["lang"]
        context.metadata["triage"] = decision
        self._conversations[conversation_id] = context

        self.audit.append("triaged", {
            "conversation": conversation_id, "track": context.track,
            "priority": decision["priority"], "intent": decision["intent"]})
        log_action(self.MODULE, "coordinator",
                   {"stage": Stage.ROUTED.value, "conversation": conversation_id,
                    "track": context.track})
        return context

    def draft_for(self, conversation_id: str,
                  agent_id: str = "customer-care") -> Draft | None:
        """ROUTED -> DRAFTED -> GATED. Runs one specialist's draft() through
        the compliance gate. Gate-passed drafts land in the approval queue;
        held drafts escalate and never reach the queue."""
        self.kill_switch.check()
        context = self._conversations.get(conversation_id)
        if context is None:
            raise KeyError(f"unknown conversation '{conversation_id}'")
        if context.metadata.get("sanctions_hold"):
            return None  # hard stop: no drafting on this conversation

        agent = next((a for a in self.roster if a.agent_id == agent_id), None)
        if agent is None:
            raise KeyError(f"unknown agent '{agent_id}'")
        draft = agent.draft(context)
        if draft is None:
            self.audit.append("draft_skipped", {
                "conversation": conversation_id, "agent": agent_id})
            return None

        self.audit.append("draft_created", {
            "draft_id": draft.draft_id, "agent": agent_id,
            "track": draft.track, "kind": draft.kind})
        log_action(self.MODULE, agent_id,
                   {"stage": Stage.DRAFTED.value, "draft": draft.draft_id})

        verdict = self.gate.review(draft, {
            "source_text": context.inbound_text,
            "opted_out": bool(context.window_state.get("opted_out")),
            "within_24h_window": context.window_state.get("within_24h_window", True),
            "rate_ok": context.window_state.get("rate_ok", True),
        })
        self.audit.append("gate_verdict", {
            "draft_id": draft.draft_id, "verdict": verdict.status,
            "flags": [f["code"] for f in verdict.flags]})
        if verdict.status == "hold":
            return None  # held + escalated by the gate; never queued
        self.queue.submit(draft, verdict.to_dict())
        return draft

    # -- go-live stubs (NOT wired) -----------------------------------------

    def deliver_approved(self, queued: QueuedDraft) -> dict:
        """STUB. At go-live this hands the approved draft to the governed
        outbox workflow (Juan-dispatched, dry-run first, one recipient).
        The coordinator NEVER calls the enqueue endpoint itself — the
        handoff is to the human-dispatched workflow, and this stub raises
        until the go-live wiring (on Juan's word) replaces it."""
        raise NotImplementedError(
            "deliver_approved is a go-live stub: the swarm is DESIGNED, not "
            "live. The only send path is the Juan-dispatched governed outbox "
            "workflow; this package will never call the enqueue endpoint."
        )

    # -- internals ----------------------------------------------------------

    def _build_context(self, event: dict, track: str = "unknown",
                       sanctions_hold: bool = False) -> AgentContext:
        # NOTE: no address/registration fields anywhere (Blocker #4 shelved).
        return AgentContext(
            conversation_id=str(event["conversation_id"]),
            phone=str(event.get("phone") or ""),
            track=track,
            lang="es-first",
            inbound_text=str(event.get("text") or ""),
            history=list(event.get("history") or []),
            contact_context=dict(event.get("contact_context") or {}),
            pipeline_snapshot=dict(event.get("pipeline_snapshot") or {}),
            window_state=dict(event.get("window_state") or {}),
            metadata={**(event.get("metadata") or {}),
                      **({"sanctions_hold": True} if sanctions_hold else {})},
        )
