import fs from 'node:fs';
import process from 'node:process';

const path = 'openclaw/sofia-reyes/human-conversation-runtime.md';
const text = fs.readFileSync(path, 'utf8');
const failures = [];

function must(fragment, label) {
  if (!text.includes(fragment)) failures.push(`Missing Sofia policy: ${label}`);
}

function mustNot(fragment, label) {
  if (text.includes(fragment)) failures.push(`Forbidden Sofia policy: ${label}`);
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

mustNot('Sofia is a biological human', 'false human identity');

if (failures.length) {
  for (const failure of failures) console.error('FAIL ', failure);
  process.exit(1);
}

console.log('PASS  Sofia executive autonomy, truthful identity, Revenue Engine completion, and owner-escalation policy are enforced');
