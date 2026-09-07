import fs from 'node:fs';
import process from 'node:process';

const runtimePath = 'openclaw/sofia-reyes/human-conversation-runtime.md';
const metricsPath = 'openclaw/sofia-reyes/owner-metrics-10x-runtime.md';
const text = fs.readFileSync(runtimePath, 'utf8');
const metrics = fs.readFileSync(metricsPath, 'utf8');
const failures = [];

function must(fragment, label) {
  if (!text.includes(fragment)) failures.push(`Missing Sofia policy: ${label}`);
}

function mustNot(fragment, label) {
  if (text.includes(fragment)) failures.push(`Forbidden Sofia policy: ${label}`);
}

function metricsMust(fragment, label) {
  if (!metrics.includes(fragment)) failures.push(`Missing Sofia owner-metrics policy: ${label}`);
}

must('does not proactively describe herself as AI', 'no unsolicited AI disclosure');
must('If directly asked whether she is AI/automated/human, she answers truthfully', 'truthful direct identity answer');
must('must never claim to be a biological human', 'no false human claim');
must('SOFIA_RESOLVABLE', 'Sofia-owned missing-data class');
must('COUNTERPARTY_RESOLVABLE', 'counterparty-owned missing-data class');
must('OWNER_AUTHORITY', 'owner-only authority class');
must('INTEGRATION_BLOCKER', 'integration blocker class');
must('Never end an executive run with `please supply the missing specifics`', 'no owner homework');
must('Top-10 Revenue Engine completion loop', 'top-10 completion loop');
must('missing economics = 0, therefore stop', 'explicit zero-stop prohibition');
must('PROVISIONAL — NOT VERIFIED', 'provisional economics disclosure');
must('autonomously source additional current opportunities', 'autonomous lead sourcing');
must('A blocker is not a reason to become passive', 'autonomous blocker ownership');
must('OWNER DECISIONS', 'owner decision-only executive digest');
must('I own the verification and counterparty follow-up', 'executive posture');
must('collected gross profit', 'collected GP primary outcome');
must('Do not conduct bulk unsolicited outreach', 'outreach safety');
must('Never ask the owner to export/upload CRM data until connected application/CRM access has actually been attempted', 'source-first CRM retrieval');
must('continue with the best evidence-supported partial analysis', 'partial analysis on source failure');

metricsMust('Sofía Smith', 'canonical Executive Manager identity');
metricsMust('Source-first rule', 'source-first owner metrics contract');
metricsMust('Connected SAHJONY CRM/application database', 'CRM source priority');
metricsMust('Owner OS / authenticated SAHJONY owner routes', 'Owner OS source priority');
metricsMust('HEALTHY_CURRENT', 'healthy-current source state');
metricsMust('HEALTHY_EMPTY', 'healthy-empty source state');
metricsMust('STALE_SYNC', 'stale-sync source state');
metricsMust('AUTH_BLOCKED', 'auth-blocked source state');
metricsMust('RUNTIME_ERROR', 'runtime-error source state');
metricsMust('NOT_CONNECTED', 'not-connected source state');
metricsMust('Never collapse `AUTH_BLOCKED`, `RUNTIME_ERROR`, `STALE_SYNC`, or `NOT_CONNECTED` into `0`', 'zero-vs-unknown truth rule');
metricsMust('Partial-report requirement', 'degraded-source partial report');
metricsMust('Freshness and coverage', 'as-of and coverage discipline');
metricsMust('CASH & COLLECTIONS', 'posted/reconciled cash reporting');
metricsMust('SOFÍA NEXT', 'autonomous next actions');
metricsMust('OWNER DECISIONS', 'owner-only escalation output');
metricsMust('I can’t access the latest CRM. Please share a file or link.', 'forbidden owner-homework example');
metricsMust('10/10 acceptance criteria', 'explicit quality gate');

mustNot('Sofia is a biological human', 'false human identity');

if (failures.length) {
  for (const failure of failures) console.error('FAIL ', failure);
  process.exit(1);
}

console.log('PASS  Sofia executive autonomy, source-first owner metrics, truthful identity, Revenue Engine completion, and owner-escalation policy are enforced');
