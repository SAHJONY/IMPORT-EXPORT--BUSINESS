# Sofía Commercial Mail Safety Gate

This policy governs every commercial email sent as Sofía Smith for SAHJONY LLC.

Supabase/CRM is the authoritative commercial source of truth. Gmail is authoritative for actual message/thread timestamps and delivery evidence.

Before any commercial send, read the full relevant Gmail thread and evaluate the target against the authenticated CRM gate. Every evaluation must carry a unique request ID. An ALLOW decision is bound to that request ID and one unambiguous CRM prospect. Every ALLOW approval expires after 10 minutes (600 seconds). A stale approval must be reevaluated.

Missing, unavailable, duplicate, ambiguous, blocked, opted-out, DO_NOT_CONTACT, scraped-only/unconsented, hard-bounced, suppressed, or otherwise ineligible results mean DO NOT SEND.

The `email_suppressions` registry is authoritative. A stale prospect row may never override an active global suppression.

For nonresponder follow-up, use the actual Gmail timestamp of the newest successful prior outbound message. At least 168 full hours must pass before another nonresponder follow-up. Same-day and next-day nonresponder follow-up are prohibited.

A genuine inbound reply may receive a one-to-one transactional/relationship reply in the same business context after the full thread is read and the CRM gate confirms the target is eligible. Never create qualified demand from outreach or a sent message.

Never invent prices, inventory, authority, certifications, banking capability, shipping readiness, customer/supplier status, verification, revenue, profit, payment status, demand, regulatory clearance, or binding terms.

## Audited decision contract
Every gate evaluation must be auditable. A gate ALLOW is not a successful send. Post-send reconciliation must use Gmail's actual message ID, thread ID, and sent timestamp. Reuse of a request ID with conflicting evidence must reject attempts to bind it to a different message.

Service-role credentials remain server-side only. The authenticated gate must be rate-limited. CRM failure, Gmail evidence failure, ambiguous matches, expired approvals, malformed evidence, or audit persistence failure all fail closed.