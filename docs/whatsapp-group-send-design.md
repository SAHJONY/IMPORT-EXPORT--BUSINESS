# WhatsApp Group Send — Design & 24/7 Management

Branch: `feat/whatsapp-group-send` (prototype only — NOT merged, NOT deployed).
Owner request: let Sofia publish directly into WhatsApp groups she administers,
for ALL business groups (every sales agent, Cuba and worldwide), and manage
them 24/7 autonomously.

## 1. Feasibility verdict

**Feasible.** The full send path was traced read-only:

1. GitHub workflow `hostinger-hermes-whatsapp-send.yml` → `POST /whatsapp/hermes/outbox/enqueue`
   (`whatsapp_api.py::hermes_outbox_enqueue`) → row in `whatsapp_openclaw_outbox`
   → worker `sahjony-hermes-outbox.service` drains via `GET /whatsapp/hermes/outbox`
   → delivers through the Hermes bridge (127.0.0.1:3000).
2. **Group-JID support in the transport: confirmed by in-repo evidence.**
   `whatsapp_api.py::_bridge_sender_phone` explicitly handles bridge events whose
   `chatId` ends with `@g.us` — the bridge demonstrably observes group chats.
   Transports that surface `@g.us` chatIds send to them with the same primitive
   as 1:1 (different JID, same call).
3. **Blockers were all in code we own** (workflow digit-stripping, API
   digit-validation). The one part we could NOT inspect is the outbox worker
   itself (lives on the VPS in off-limits paths; SSH port 22 also timed out
   during investigation). The worker presumably formats `recipient` digits as
   `<digits>@c.us`/`@s.whatsapp.net`. It needs a one-line contract change
   (section 7) — deployed only with Juan's explicit approval.

## 2. Outbound design (implemented on branch)

### Addressing (`to=` input, workflow + API)
- 1:1 (unchanged, byte-for-byte): `5352985393`
- Group by raw JID: `group:120363041234567@g.us`
- Group by registry alias: `group:alias:rosmel-ventas-cuba`

The `group:` prefix makes a group address unmistakable — a group JID's numeric
part (often 15 digits) could otherwise collide with the phone-digit path
(`_normalize_phone` would accept 15 digits). Malformed group addresses fail
closed (HTTP 400 / workflow exit 2); they can never fall through to 1:1.

### Registry: `whatsapp_groups.json` (repo root)
Persistent, PR-governed record per group. Fields: `alias`, `jid` (null until
the real JID is discovered — **never invent one**), `name`, `purpose`, `agent`,
`agent_phone`, `region` (`cuba`/`worldwide`/…), `language`, `admin_status`
(`admin`/`member`/`unknown`), `admin_verified_at`, `admin_verified_by`, `notes`.
Juan approves every registry change. `GET /whatsapp/hermes/groups` (bridge-signed,
read-only, registered in `whatsapp_cloud_primary_api.py`) serves it.

### API changes (`whatsapp_api.py`)
- `_is_valid_group_jid`, `_resolve_group_target` (alias→JID), `_bridge_group_jid`.
- `HermesDirectSend.recipient` max length 20→64.
- `hermes_outbox_enqueue`: group rows store `recipient="group:<jid>"`,
  `recipient_type="group"`, `group_jid`, `group_alias`; 1:1 rows store exactly
  what they stored before plus `recipient_type="individual"`.
- New `GET /whatsapp/hermes/groups/activity` (bridge-signed, read-only):
  recent group messages, optional `?alias=` filter.

### Workflow changes
- Validation accepts the two group forms; group tokens pass through to the API
  un-mangled (1:1 still digit-normalized as before).
- Ban-risk notice extended: group messages are visible to EVERY member; any
  member can report.
- Unchanged governance: dry-run default, one group per dispatch, sequential
  dispatches, delivery tracked to `sent`/`failed`/`needs_review`.

### Worker contract (NOT implemented — needs Juan's deploy approval)
When draining the outbox, if `recipient_type == "group"` (or `recipient`
starts with `group:`), the worker MUST send to `group_jid` verbatim instead of
appending `@c.us`/`@s.whatsapp.net`. Everything else stays identical. This is
the single production change outside this branch.

## 3. Inbound design (implemented on branch)

### Visibility options considered
- **(a) Bridge poller (chosen, implemented).** `_handle_bridge_message` now
  detects `@g.us` chatIds and RECORDS the message (group JID, sender name +
  digits, body, timestamp) into `whatsapp_messages` via the existing
  `_register_inbound_message`. It returns immediately after — **Sofia never
  auto-replies inside groups.** Pure observation, no behavior change to 1:1.
- (b) Events-push path (`POST /whatsapp/hermes/events`): would record group
  messages too if the bridge pushes them — unverified (bridge code off-limits).
- (c) Bridge-native group-list API: unknown — not verified, not relied upon.

### Reading activity
`GET /whatsapp/hermes/groups/activity?alias=<alias>&limit=50` returns recent
group messages (sender, text, timestamp). The watch loop uses it; Sofia also
uses it ad hoc before drafting any group content.

### Finding a group's JID (to populate the registry)
1. Any inbound message in the group exposes its `chatId` (`...@g.us`) in bridge
   internals — once the poller records one message, the JID is known.
2. Ask the group admin / Juan to read it from a bridge diagnostic.
3. Future: extend the poller to maintain an auto-discovered
   `whatsapp_groups_seen` list (not implemented in this prototype).

### Admin-status verification
Programmatic verification is NOT possible with current bridge visibility —
`admin_status` in the registry is owner-attested (`admin_verified_by: juan`).
This is acceptable because every group send still requires Juan's per-message
approval (Tier 2 default), so a wrong attestation cannot cause an unauthorized
send.

## 4. 24/7 autonomous watch loop (spec for the scheduler)

Cron `whatsapp-group-watch`, suggested every 3 hours (tunable per group via
registry `watch_interval_hours` in future). Each run, per registered group with
`jid_ready`:

1. **Read**: `GET /whatsapp/hermes/groups` → `GET /groups/activity?alias=`
   (watermark: last processed `message_id`/`received_at` per group, kept in the
   cron's hidden state).
2. **Classify** new messages: question · buyer-interest (with quantity) ·
   complaint/dispute · spam/off-topic · routine.
3. **Draft** replies/posts as needed.
4. **Tier check** (section 5) → either post (Tier 1 only) or escalate.
5. **Escalate** to Juan in chat with the draft + context for everything Tier 2.
6. **Log** the run (watermark, actions, escalations) to the daily memory log.

Health duties: detect member spam/conflict, dead groups (no activity N days),
and JID changes; report, never act on membership.

## 5. Approval tiers — what autonomy may and may not do

- **Tier 0 — autonomous, no approval needed**: monitoring, logging, drafting,
  watermarking, digests.
- **Tier 1 — autonomous SEND, verbatim pre-approved templates only**:
  `whatsapp_group_templates.json` holds templates Juan approved word-for-word
  via PR. The loop posts the template text EXACTLY (only `allowed_fill`
  placeholders filled). One group per dispatch, same delivery tracking, all
  sends logged. Examples: "te respondo por privado" acknowledgements,
  approved restock notices.
- **Tier 2 — ALWAYS gated, draft + escalate to Juan**: price changes outside
  approved ranges, discounts, new terms/commitments, new products or offers,
  disputes/complaints, member add/remove, and ANY message that does not match
  a Tier-1 template verbatim. Silence is not approval.

This mirrors the standing rule already given to Rosmel (consult before
offering prices, discounts, or terms).

## 6. Safety guardrails (outbound, same as 1:1 plus group specifics)

- Juan's explicit per-message approval for anything not Tier-1-verbatim.
- One group per dispatch; dispatches sequential (the workflow cancels
  concurrent runs).
- Dry-run default; ban-risk notice on every live dispatch, extended for
  groups (every member sees it; any member can report).
- Delivery tracked to a terminal state; `failed`/`needs_review` escalate.
- Role-guard audit on every group draft before sending.
- 1–1000 chars; Spanish for Cuba groups; human 1:1 tone even in groups.
- Registry edits via PR (Juan approves); template edits via PR (Juan approves).

## 7. Production rollout (requires Juan's explicit approval per step)

1. **Review** this branch (`feat/whatsapp-group-send`); approve the PR.
   Merge to main ONLY on his explicit "merge" instruction.
2. **Deploy the API**: on the VPS, `sahjony-fallback-whatsapp` —
   `git fetch && git reset --hard origin/main`, restart service. (Standard
   deploy; Juan approves.)
3. **Update the outbox worker** with the section-2 contract (send
   `group:<jid>` rows to the JID verbatim); deploy it. (Juan approves —
   this touches the live delivery path.)
4. **Populate `whatsapp_groups.json`** with real JIDs (section 3 discovery);
   PR approved by Juan.
5. **Dry-run validation**: dispatch the workflow with
   `-f to=group:alias:<alias> -f dry_run=true`; confirm validation +
   enqueue shape. Then ONE live test post to a safe group, exact text
   approved by Juan, confirming delivery via the status poll.
6. **Enable the watch cron** (Tier 0+1 only); Tier 2 stays escalated.

## 8. Honest unknowns / limitations

- Outbox worker internals unverified (off-limits paths; SSH timed out) —
  the section-7 contract is specified but not tested against the real worker.
- Whether the bridge pushes group events to `/whatsapp/hermes/events`
  (option b) — unverified.
- No programmatic admin-status check — owner attestation only.
- `groups/activity` fetches a bounded recent window and sorts in memory
  (mirrors the existing outbox drain pattern); for very large histories a
  server-side ordered query should replace it later.
- Ban risk for group sends is real and higher than 1:1 (all members see
  every message); pacing and template discipline are the mitigations.
