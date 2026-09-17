# Sofia 360° AI Agentic Salesperson

Branch: `build/sofia-360-salesperson` (from main). **Not merged. Not live.**
Activation needs Juan's explicit approval.

## What this is

Sofia stops being a smart responder and becomes a full salesperson that runs
the whole funnel: she knows each customer per business, works a playbook of
stages, follows up on her own schedule (drafts only), and escalates to Juan
with a one-screen brief when she hits her limits.

## Architecture in words

```
Inbound WhatsApp turn
        │
        ▼
┌─ PERCEIVE ─────────────────────────────────────────────┐
│ text from transcript                                    │
│ + voice note → sofia_voice_inbox.transcribe_audio       │
│ + photo/video → runtime _evaluate_turn_media            │
│   (sofia_media_evaluator, already merged on main)       │
└────────────────────────┬───────────────────────────────┘
                         ▼
┌─ REASON ───────────────────────────────────────────────┐
│ sofia_customer_360: one profile PER BUSINESS            │
│   (history, language, stage, interests, commitments,    │
│    objections, last touch — every field cites a source) │
│ sofia_sales_playbooks: stage → next step for the track  │
│ existing sales brain + agentic sales OS: deal scoring   │
└────────────────────────┬───────────────────────────────┘
                         ▼
┌─ ACT (exactly one) ────────────────────────────────────┐
│ reply ......... existing runtime pipeline, then         │
│                 negotiation guardrails validate it      │
│ draft ......... follow-up draft → approval queue       │
│ tool call ..... RECORDED ONLY, never executed alone    │
│ escalate ...... owner brief → Juan, customer untouched  │
└────────────────────────┬───────────────────────────────┘
                         ▼
┌─ REFLECT ──────────────────────────────────────────────┐
│ record_lesson from evidence only (no PII)              │
└────────────────────────────────────────────────────────┘
```

## New modules (all extend; none duplicate)

| Module | What it adds |
|---|---|
| `sofia_sales_playbooks.py` | Full-funnel playbooks per track with equal rigor: per-field qualification questions (ES/EN), track-specific minimum viable qualification, matching rules, day 1/3/7/14 cadence, dormant-revival triggers, exact escalation triggers. import_export mirrors `sofia_agentic_sales_os.py` (RFQ bar = product/specification/quantity/destination/delivery_timeline; authority lanes; broker positioning). my_cuba_cash mirrors `sofia_my_cuba_cash_track.py` (Tier 1/2/3 autonomy, published fee schedule imported from the track block so it can never drift, zero-custody line, beta framing, topic boundaries). Car playbook mirrors `agent/car_sales_agent.py` (ai-car-sales-machine, branch `build/car-sales-v1`). |
| `sofia_customer_360.py` | One unified profile per contact **per business**, built from whatsapp_messages + whatsapp_leads + business_events. Every field cites its source turn. Businesses never cross-file (see below). |
| `sofia_negotiation_guards.py` | Deterministic outbound validation: no below-floor quotes, no invented amounts, no purchase commitments, no legal/customs determinations, no fake action claims, broker disclosure on first car reply. Fail → escalate, never send. |
| `sofia_escalation.py` | One-screen owner briefs (who / what they want / deal value / what Sofia tried / exactly what she needs). Recorded to the owner-visible queue; never messaged to the customer. |
| `sofia_followup_engine.py` | Scheduled scan → follow-up **drafts** to the approval queue. There is no send path in this module by construction. |
| `sofia_sales_loop.py` | The perceive→reason→act→reflect orchestrator, behind `SOFIA_360_SALESPERSON` (default OFF). |

Changed (minimal): `sofia_whatsapp_runtime.py` — `generate_sofia_reply` checks the
flag first and routes through the loop; flag off = pipeline byte-for-byte unchanged.

## Business separation (hard rule)

- Every helper takes an explicit `business`; unknown businesses raise `ValueError`.
- Turns are tagged per business via the live classifier + continuity. Strong
  car-signal turns with the flag **off** are quarantined as `unclassified_car`:
  kept aside, never inherited into another business's profile.
- `separation_audit()` verifies a profile contains no foreign-business sources.

## What she can do alone vs what waits for Juan

**Alone (autonomous):** answer in the customer's language · qualify per the
playbook (max 2 questions/turn) · match against verified inventory/listings only ·
draft follow-ups (day 1/3/7/14) and dormant revivals · evaluate photos/video/voice
notes · record lessons · keep per-business memory.

**Waits for Juan:** any external send of a draft · publishing a listing · quoting
below a seller's floor · accepting a price / signing / paying · any legal or
customs determination (Cuba especially) · fee amounts (never invented) ·
cross-border shipping quotes · activating the 360 loop itself (`SOFIA_360_SALESPERSON=1`).

## car_sales track status

The playbook, signals (`CAR_SALES_PHRASES/WORDS`, `car_signal_score`), and
qualification mirror the car machine. They are **definitions only**: the live
classifier (`sofia_track_classifier.py`) and live runtime are untouched, and
the loop's car routing exists solely behind the feature flag. Wiring
`car_sales` into live Sofia needs Juan's explicit approval (pending).

## Merge order with sibling branches

1. `build/sofia-media-vision` — MERGED (eyes)
2. `build/sofia-voice` — MERGED (voice)
3. `build/car-arms` — car machine arms (other repo, in flight)
4. `build/sofia-360-salesperson` — this branch (consumes 1–3; arms via recorded
   tool-call intents only, no cross-repo imports)

## How to test

```bash
cd ~/workspace/repos/import-export-business
python3 -m pytest tests/test_sofia_360_salesperson.py -q   # 43 tests
python3 -m pytest tests/test_sofia_reply_language.py tests/test_native_spanish_start.py -q  # regression
```

To dry-run the loop without touching live traffic:

```python
import asyncio, os
os.environ["SOFIA_360_SALESPERSON"] = "1"
from sofia_sales_loop import resolve_loop_track, should_use_360
assert should_use_360()
print(resolve_loop_track("busco un carro toyota corolla"))
# {'track': 'car_sales', 'source': 'car_signals_flag_gated', ...}
```

## Negotiation guardrails per business

`sofia_negotiation_guards.py::validate_outbound` runs track-scoped checks:

- **import_export** — no invented suppliers/prices/freight/availability/compliance clearance (definitive trade claims fail without verified evidence); broker positioning (never the end buyer, no buyer-LOI language); binding actions (quotes, price acceptance, contracts, WON) need Juan.
- **my_cuba_cash** — only the published fee schedule may be quoted; concierge tier not offered/mentioned until first real sends validate demand; 1.75% business tier never framed as an outbound-payment solution; no invented providers/rates; zero custody always; beta framing (no launched/full-service claims).
- **car_sales** — never below seller floor; broker disclosure in the first substantive reply; never commit Juan to buy/pay/sign.
- **All tracks** — no legal/customs determinations; no invented amounts; no claims that an external action already happened.

Guard failures escalate with the violation mapped to the right playbook
trigger (below-floor → `below_floor_offer`, custody offer → `custody_request`,
legal determination → `cuba_legality`/`legality_question`).

## Live-track escalation wiring

The loop escalates on inbound signals for the live tracks, same as cars:
import_export → `cuba_legality` (Cuba-specific legality questions),
`compliance_flag` (sanctions/customs/restricted-goods signals);
my_cuba_cash → `fraud_signal`, `custody_request`, `sanctions_question`
(US corridor). Follow-up drafts are drafts-only for all three tracks and
never re-ask facts already in the 360 profile.

## Open decisions for Juan

1. Activate the 360 loop live (`SOFIA_360_SALESPERSON=1` on the VPS services).
2. Wire the `car_sales` track into the live classifier (separate approval).
3. Run the follow-up engine on a schedule (drafts queue for his approval).
