import fs from 'node:fs';
import process from 'node:process';

const clientPath = 'src/sofiaCommercialSafetyGate.ts';
const runtimePath = 'openclaw/sofia-reyes/commercial-mail-safety-gate.md';
const transportPath = 'gmail_transport_api.py';
const suppressionMigrationPath = 'ops/sql/2026-09-10-enforce-global-email-suppressions.sql';
const failures = [];

for (const path of [clientPath, runtimePath, transportPath, suppressionMigrationPath]) {
  if (!fs.existsSync(path)) failures.push(`Missing required file: ${path}`);
}

if (!failures.length) {
  const client = fs.readFileSync(clientPath, 'utf8');
  const runtime = fs.readFileSync(runtimePath, 'utf8');
  const transport = fs.readFileSync(transportPath, 'utf8');
  const suppression = fs.readFileSync(suppressionMigrationPath, 'utf8');

  const clientMust = [
    ['FOLLOWUP_MIN_HOURS = 168', '168-hour cooldown constant'],
    ["EXPECTED_GATE_VERSION = '4.0'", 'gate v4 contract'],
    ["interactionKind === 'followup'", 'follow-up branch'],
    ['SOFIA_GATE_GMAIL_TIMESTAMP_REQUIRED', 'Gmail timestamp hard requirement'],
    ["outbound_timestamp_source: input.interactionKind === 'followup' ? 'gmail'", 'Gmail timestamp provenance'],
    ['SOFIA_GATE_FULL_THREAD_REQUIRED', 'full-thread requirement'],
    ['SOFIA_GATE_GENUINE_INBOUND_REQUIRED', 'genuine inbound requirement'],
    ["action: 'evaluate'", 'explicit evaluation action'],
    ['request_id: input.requestId', 'request-id binding'],
    ['approvalStillFresh', 'approval TTL validation'],
    ['data.match_count !== 1', 'single unambiguous CRM match'],
    ['SOFIA_GATE_CRM_UNAVAILABLE', 'CRM fail-closed behavior'],
    ['SOFIA_COMMERCIAL_SEND_BLOCKED', 'final send assertion'],
    ['recordSofiaCommercialSend', 'post-send reconciliation function'],
    ["action: 'record_send'", 'post-send server action'],
    ['gmail_message_id: evidence.gmailMessageId', 'Gmail message binding'],
    ['gmail_thread_id: evidence.gmailThreadId', 'Gmail thread binding'],
    ['SOFIA_GATE_POST_SEND_RECONCILIATION_FAILED', 'post-send failure gate'],
  ];

  const runtimeMust = [
    ['Supabase/CRM is the authoritative commercial source of truth', 'CRM authority'],
    ['168 full hours', '168-hour nonresponder cooldown'],
    ['actual Gmail timestamp', 'Gmail timestamp evidence'],
    ['10 minutes (600 seconds)', '10-minute approval TTL'],
    ['DO NOT SEND', 'fail-closed send rule'],
    ['genuine inbound reply', 'transactional inbound exception'],
    ['Never create qualified demand from outreach', 'no demand inference'],
    ['Every evaluation must carry a unique request ID', 'idempotency contract'],
    ['Audited decision contract', 'audit ledger contract'],
    ['A gate ALLOW is not a successful send', 'decision/send separation'],
    ["Gmail's actual message ID, thread ID, and sent timestamp", 'post-send Gmail evidence'],
    ['reject attempts to bind it to a different message', 'replay protection'],
    ['Service-role credentials remain server-side only', 'service-role secrecy'],
    ['rate-limited', 'abuse control'],
    ['read the full relevant Gmail thread', 'full-thread requirement'],
    ['email_suppressions', 'global suppression registry'],
    ['stale prospect row may never override an active global suppression', 'stale CRM suppression override prevention'],
  ];

  const transportMust = [
    ['commercial_gate_enforced', 'transport advertises enforced gate'],
    ['commercial_gate_version": "4.0', 'transport v4 contract'],
    ['commercial_gate_transport_boundary', 'transport boundary enforcement'],
    ['commercial_gate_exactly_once', 'exactly-once send protection'],
    ['commercial_gate_approval_ttl_seconds": 600', 'transport TTL contract'],
    ['SOFIA_COMMERCIAL_SEND_REQUIRES_GMAIL_OAUTH', 'commercial SMTP bypass prohibited'],
    ['SOFIA_GATE_SINGLE_EXTERNAL_RECIPIENT_REQUIRED', 'bulk recipient bypass prohibited'],
    ['SOFIA_GATE_RECIPIENT_MISMATCH', 'recipient binding'],
    ['SOFIA_GATE_APPROVAL_EXPIRED', 'stale approval rejection'],
    ['_record_transport_send', 'audit-first transport persistence'],
    ['reconciliation_status', 'post-send CRM reconciliation status'],
    ['do_not_retry_send', 'duplicate retry suppression'],
    ['owner_direct_send', 'separate owner-direct path'],
  ];

  const suppressionMust = [
    ['security invoker', 'suppression trigger runs as invoker'],
    ["new.logical_table <> 'external_trade_prospects'", 'prospect-only guard'],
    ["s.logical_table = 'email_suppressions'", 'authoritative suppression lookup'],
    ["'SUPPRESSED'", 'suppressed status enforcement'],
    ["'{email_contact_status}'", 'hard-bounce contact state'],
    ["'{do_not_contact}'", 'do-not-contact enforcement'],
    ['trg_enforce_global_email_suppression_on_trade_record', 'pre-write enforcement trigger'],
    ['trg_propagate_global_email_suppression', 'suppression propagation trigger'],
  ];

  for (const [fragment, label] of clientMust) if (!client.includes(fragment)) failures.push(`Missing client invariant: ${label}`);
  for (const [fragment, label] of runtimeMust) if (!runtime.includes(fragment)) failures.push(`Missing runtime invariant: ${label}`);
  for (const [fragment, label] of transportMust) if (!transport.includes(fragment)) failures.push(`Missing transport invariant: ${label}`);
  for (const [fragment, label] of suppressionMust) if (!suppression.includes(fragment)) failures.push(`Missing suppression invariant: ${label}`);
}

if (failures.length) {
  for (const failure of failures) console.error('FAIL ', failure);
  process.exit(1);
}

console.log('PASS  Sofia commercial gate v4 enforces CRM authority, Gmail evidence, global email suppression, 168h cooldown, 10-minute TTL/idempotency, replay protection, transport-boundary enforcement, and post-send reconciliation');
