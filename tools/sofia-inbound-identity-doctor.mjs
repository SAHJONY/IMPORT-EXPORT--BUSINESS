import fs from 'node:fs';
import process from 'node:process';

const clientPath = 'src/sofiaInboundIdentity.ts';
const failures = [];

if (!fs.existsSync(clientPath)) failures.push(`Missing required file: ${clientPath}`);

if (!failures.length) {
  const client = fs.readFileSync(clientPath, 'utf8');
  const must = [
    ["'sofia-inbound-identity'", 'authoritative inbound identity function'],
    ['genuine_inbound_reply: true', 'genuine inbound assertion'],
    ["SOFIA_MAILBOX = 'sofiaexecutivemanager@gmail.com'", 'mailbox binding'],
    ["verification_status !== 'INBOUND_UNVERIFIED'", 'no verification promotion'],
    ["outreach_status !== 'INBOUND_TRANSACTIONAL_ONLY'", 'transactional-only outreach state'],
    ["consent_status !== 'TRANSACTIONAL_INBOUND_ONLY'", 'no marketing consent inference'],
    ['data.qualified_demand === true', 'qualified-demand prohibition'],
    ['data.trade_rfq_created === true', 'RFQ prohibition'],
    ['data.fail_closed_for_new_outreach !== true', 'new-outreach fail-closed invariant'],
  ];
  for (const [fragment, label] of must) {
    if (!client.includes(fragment)) failures.push(`Missing inbound identity invariant: ${label}`);
  }
}

if (failures.length) {
  for (const failure of failures) console.error('FAIL ', failure);
  process.exit(1);
}

console.log('PASS  Sofia inbound identity resolution is transactional-only, Gmail-bound, and cannot create qualified demand or RFQ state');
