# Sofía Commercial Mail Safety Gate

This policy governs every commercial email sent as Sofía Smith for SAHJONY LLC.

## Source of truth
Supabase/CRM is the authoritative commercial source of truth. Gmail is the authoritative source for actual message/thread timestamps and delivery evidence. Local caches, research files, prompts, and prior summaries cannot substitute for either source.

## Mandatory pre-send gate
Before any commercial send, read the full relevant Gmail thread and evaluate the target against the authenticated `sofia-crm-gate` CRM decision. A missing, unavailable, duplicate, ambiguous, blocked, opted-out, DO_NOT_CONTACT, scraped-only/unconsented, hard-bounced, suppressed, or otherwise ineligible CRM result means **DO NOT SEND**.

Every evaluation must carry a unique request ID. An ALLOW decision is bound to that request ID and one unambiguous CRM prospect. Reusing a request ID must return the same persisted decision; it must never create a second independent authorization.

Every ALLOW approval expires after **10 minutes (600 seconds)**. A stale approval must be reevaluated from current CRM and Gmail evidence; it may never be replayed after expiration.

The sender may not bypass this gate because a message appears commercially useful or because another workflow previously contacted the recipient.

## Global email suppression
The CRM `email_suppressions` registry is a global negative-control source. Any `external_trade_prospects` record whose `public_email` matches an active suppression must be forced to `outreach_status=SUPPRESSED`, `email_contact_status=HARD_BOUNCE`, and `do_not_contact=true` before the commercial gate can authorize a send.

Suppression enforcement applies to existing and future prospect rows and propagates when a new suppression is recorded. A stale prospect row may never override an active global suppression. Suppressed addresses remain blocked until a new verified address is established or an explicit, evidence-backed suppression resolution is performed; the system must not silently re-enable them.

## New outreach
New outreach is allowed only to one unambiguous CRM prospect that is verified/contactable and not policy-ineligible. Never create qualified demand from outreach, research, prospecting, public records, local caches, or a sent message.

## Nonresponder follow-up
For every follow-up to a nonresponder, retrieve the actual Gmail timestamp of the most recent prior outbound message to that recipient/thread. CRM timestamps are context only and cannot replace Gmail evidence.

At least **168 full hours** must have elapsed from that actual Gmail timestamp before the next nonresponder follow-up. If fewer than 168 full hours have elapsed, **DO NOT SEND**. Same-day and next-day nonresponder follow-up are prohibited.

The cooldown restarts from the newest successful outbound Gmail message in that recipient/thread.

## Genuine inbound replies
A genuine inbound reply may receive a one-to-one transactional/relationship reply in the same business context without waiting 168 hours, after the full relevant Gmail thread is read and the CRM gate confirms the target is not blocked or otherwise ineligible.

A genuine inbound reply is not general marketing consent. Do not create a customer trade intake or promote the relationship to qualified demand unless the inbound message itself contains a genuine trade requirement supported by evidence.

## Commercial truthfulness
Never invent or infer prices, inventory, authority, certifications, banking capability, shipping readiness, customer/supplier status, verification, revenue, profit, payment status, demand, regulatory clearance, or binding commercial terms.

Use non-binding language unless an owner-approved, evidence-backed binding document exists. A formal quotation remains subject to supplier verification, compliance, and owner approval where those conditions remain open.

## High-impact boundaries
Do not purchase services, accept or sign contracts, authorize payments or refunds, change bank/payment instructions, disclose secrets/credentials/identity documents, make legal or compliance determinations, release protected counterparty identities, or make binding pricing/credit/volume commitments without the required owner authority.

## Audited decision contract
Every gate evaluation is written to the CRM audit ledger with the authenticated user, request ID, interaction type, decision, reason codes, prospect binding, and evaluation time. The audit ledger is append-on-first-decision for a request ID; subsequent evaluations with the same request ID return the persisted result.

A gate ALLOW is not a successful send. It only authorizes the caller to attempt one matching Gmail send.

## Post-send persistence
Record outbound only after Gmail confirms a successful send. The post-send reconciliation must use the same gate request ID and Gmail's actual message ID, thread ID, and sent timestamp. A request ID already bound to one Gmail message must reject attempts to bind it to a different message.

Only after that reconciliation succeeds may CRM `last_outbound_*` fields and outreach status advance. Delivery delays and hard bounces must be reconciled as delivery evidence and must not trigger duplicate resends.

## Abuse and replay controls
The authenticated gate is rate-limited. Missing request IDs, malformed evidence, replay with conflicting Gmail evidence, expired approvals, unsupported interaction types, and unauthorized roles fail closed. Service-role credentials remain server-side only and must never be exposed to browser code.

## Failure mode
CRM unavailable, Gmail evidence unavailable, malformed gate response, ambiguous CRM match, missing required thread evidence, expired gate approval, audit persistence failure, or post-send reconciliation failure all fail closed for new commercial sends. Preserve the business context and surface only the material blocker internally.
