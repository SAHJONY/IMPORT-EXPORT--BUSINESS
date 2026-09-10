import fs from 'node:fs';
import process from 'node:process';

const clientPath = 'src/sofiaCommercialSafetyGate.ts';
const runtimePath = 'openclaw/sofia-reyes/commercial-mail-safety-gate.md';
const failures = [];

for (const path of [clientPath, runtimePath]) {
  if (!fs.existsSync(path)) failures.push(`Missing required file: ${path}`);
}

if (!failures.length) {
  const client = fs.readFileSync(clientPath, 'utf8');
  const runtime = fs.readFileSync(runtimePath, 'utf8');

  const clientMust = [
    ['FOLLOWUP_MIN_HOURS = 168', '168-hour cooldown constant'],
    ["interactionKind === 'followup'", 'follow-up branch'],
    ['SOFIA_GATE_GMAIL_TIMESTAMP_REQUIRED', 'Gmail timestamp hard requirement'],
    ["outbound_timestamp_source: input.interactionKind === 'followup' ? 'gmail'", 'Gmail timestamp provenance'],
    ['SOFIA_GATE_FULL_THREAD_REQUIRED', 'full-thread requirement'],
    ['SOFIA_GATE_GENUINE_INBOUND_REQUIRED', 'genuine inbound requirement'],
    ["action: 'evaluate'", 'explicit evaluation action'],
    ['request_id: input.requestId', 'request-id binding'],
    ["data.gate_version !== '3.0'", 'server v3 contract'],
    ["data.request_id !== input.requestId", 'decision/request binding'],
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

  for (const [fragment, label] of clientMust) {
    if (!client.includes(fragment)) failures.push(`Missing client invariant: ${label}`);
  }
  for (const [fragment, label] of runtimeMust) {
    if (!runtime.includes(fragment)) failures.push(`Missing runtime invariant: ${label}`);
  }
}

if (failures.length) {
  for (const failure of failures) console.error('FAIL ', failure);
  process.exit(1);
}

console.log('PASS  Sofia commercial gate v3 enforces CRM authority, Gmail evidence, 168h cooldown, audit/idempotency, replay protection, and post-send reconciliation');
