# Hermes Agent Swarm — design scaffold

**Status: DESIGNED, not live.** The swarm goes live ONLY on Juan's explicit
word. This branch is structure + contracts + tests. Nothing here sends,
connects to live services, or activates.

## What this is

A Python port of the GEV workforce-core governance contract
(`workforceCore.js`: `AGENT_TIERS`, `registerWorkforce`, `logAction`,
`escalate`, `classifyTrack`, `SANCTIONS_HARD_STOP`, `checkSanctions`,
`LANG_POLICY`, `defaultRoster`, `reviewDraft`) plus the 7-agent swarm that
will serve SAHJONY's WhatsApp transport (Hermes) behind Sofia — the single
customer-facing voice.

Design doc: `~/workspace/goals/sahjony-trade-energy-platform/hidden_files/architecture.md`
("Hermes Agent Swarm" section). This scaffold follows it exactly.

## Layout

| File | Purpose |
|------|---------|
| `hermes_swarm/__init__.py` | Package exports |
| `hermes_swarm/governance.py` | The governance contract: tiers (READ/DRAFT/PROPOSE — **no execute tier, by design**), track classifier (7 tracks, ES/EN, trade-vs-Cuba desk distinction), sanctions hard stop, language policy, roster, draft review flags |
| `hermes_swarm/agents.py` | The 7 agents: `InboxTriage`, `CustomerCare`, `LeadQualification`, `FollowUp`, `DealDesk`, `OutreachDrafting`, `ComplianceGate`. Each declares role, tier, allowed reads (named API references only — no URLs, no secrets), scoped writes, and a `draft()` interface. **No send method may exist on any agent** — enforced structurally by `SwarmAgent.__init_subclass__` |
| `hermes_swarm/coordinator.py` | Event flow as a state machine: inbound → triage → route → draft → gate → approval queue → (Juan) → done. The approval queue never auto-advances; "Juan approves" is an explicit external input. Kill switch: stop = all drafting halts, drafts stay drafts |
| `hermes_swarm/audit.py` | Immutable append-only JSONL audit log with a SHA-256 hash chain (draft → gate verdict → approval → enqueue → delivery). No edit/delete API |
| `tests/test_swarm_governance.py` | pytest: tier validation, track classification (ES/EN, trade-vs-Cuba), sanctions gate escalates-and-holds, introspection proof that no send path exists, approval queue never auto-advances, draft-review flags, kill switch, audit chain |

## What is deliberately NOT built (and why)

- **No live transport client.** Agents reference Hermes APIs by *name* only
  (`get_contact_context`, `sync_contact`, …). No URLs, no credentials, no
  HTTP imports anywhere in the package. Wiring happens at go-live, on the
  VPS, after Juan's word.
- **No enqueue code path.** `POST /whatsapp/hermes/outbox/enqueue` is the
  governed send path and its sole caller is the existing Juan-dispatched
  direct-send workflow. `SwarmCoordinator.deliver_approved()` is a stub that
  raises `NotImplementedError` until go-live wiring replaces it.
- **No systemd unit, no GEV console.** Deployment shape (unit
  `sahjony-fallback-swarm`, console panel) is documented in the architecture
  doc; nothing is installed or activated here.
- **CRM write scopes are floors, not ceilings.** The transport already
  enforces `destructive_scope=false`, `external_commitment_scope=false`;
  the scaffold's agent `allowed_writes` stay inside `lead_sync`,
  `internal_note`, `trade_intake` and can never widen them.

## Review command (for Juan)

```bash
cd ~/workspace/repos/import-export-business
git worktree add /tmp/juan-swarm-review sahjony/hermes-swarm-scaffold
cd /tmp/juan-swarm-review
python3 -m pytest tests/test_swarm_governance.py -q
```

Expected: all tests green. The introspection tests prove no send path
exists; the approval-queue tests prove nothing advances without his word.

## What needs Juan's word to go further

1. **Go-live approval** — wiring the stubbed transport handlers, the systemd
   unit, and the GEV console panel.
2. **Per-message approvals** — every draft the swarm ever produces waits in
   his approval queue; silence is never consent.
3. **Merge to main** — this branch stays unmerged until he says so.
