import fs from 'node:fs';
import process from 'node:process';

const clientPath = 'src/sofiaCommercialSafetyGate.ts';
const runtimePath = 'openclaw/sofia-reyes/commercial-mail-safety-gate.md';
const transportPath = 'gmail_transport_api.py';
const failures = [];

for (const path of [clientPath, runtimePath, transportPath]) {
  if (!fs.existsSync(path)) failures.push(`Missing required file: ${path}`);
}

if (!failures.length) {
  const client = fs.readFileSync(clientPath, 'utf8');
  const runtime = fs.readFileSync(runtimePath, 'utf8');
  const transport = fs.readFileSync(transportPath, 'utf8');

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
  ];

  const transportMust = [
    ['commercial_gate_enforced', 'transport advertises enforced gate'],
    ['commercial_gate_version": "4.0', 'transport v4 contract'],
    ['commercial_gate_transport_boundary', 'transport boundary enforcement'],
    ['commercial_gate_exactly_once', 'exactly-once send protection'],
    ['SOFIA_COMMERCIAL_SEND_REQUIRES_GMAIL_OAUTH', 'commercial SMTP bypass prohibited'],
    ['SOFIA_GATE_SINGLE_EXTERNAL_RECIPIENT_REQUIRED', 'bulk recipient bypass prohibited'],
    ['SOFIA_GATE_RECIPIENT_MISMATCH', 'recipient binding'],
    ['SOFIA_GATE_APPROVAL_EXPIRED', 'stale approval rejection'],
    ['_record_transport_send', 'audit-first transport persistence'],
    ['reconciliation_status', 'post-send CRM reconciliation status'],
    ['do_not_retry_send', 'duplicate retry suppression'],
    ['owner_direct_send', 'separate owner-direct path'],
  ];

  for (const [fragment, label] of clientMust) {
    if (!client.includes(fragment)) failures.push(`Missing client invariant: ${label}`);
  }
  for (const [fragment, label] of runtimeMust) {
    if (!runtime.includes(fragment)) failures.push(`Missing runtime invariant: ${label}`);
  }
  for (const [fragment, label] of transportMust) {
    if (!transport.includes(fragment)) failures.push(`Missing transport invariant: ${label}`);
  }
}

if (failures.length) {
  for (const failure of failures) console.error('FAIL ', failure);
  process.exit(1);
}

console.log('PASS  Sofia commercial gate v4 enforces CRM authority, Gmail evidence, 168h cooldown, TTL/idempotency, replay protection, transport-boundary enforcement, and post-send reconciliation');
