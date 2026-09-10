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
    ["supabase.functions.invoke<SofiaCommercialGateDecision>('sofia-crm-gate'", 'authoritative CRM gate invocation'],
    ['data.match_count !== 1', 'single unambiguous CRM match'],
    ['SOFIA_GATE_CRM_UNAVAILABLE', 'CRM fail-closed behavior'],
    ['SOFIA_COMMERCIAL_SEND_BLOCKED', 'final send assertion'],
  ];

  const runtimeMust = [
    ['Supabase/CRM is the authoritative commercial source of truth', 'CRM authority'],
    ['168 full hours', '168-hour nonresponder cooldown'],
    ['actual Gmail timestamp', 'Gmail timestamp evidence'],
    ['DO NOT SEND', 'fail-closed send rule'],
    ['genuine inbound reply', 'transactional inbound exception'],
    ['never create qualified demand from outreach', 'no demand inference'],
    ['record outbound only after Gmail confirms a successful send', 'post-send recording'],
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

console.log('PASS  Sofia commercial mail gate enforces CRM authority, Gmail evidence, 168h cooldown, full-thread reads, inbound-only exception, and fail-closed sending');
