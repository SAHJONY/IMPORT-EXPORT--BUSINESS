import fs from 'node:fs';
import process from 'node:process';

const runtimePath = 'openclaw/jarvis/personal-executive-runtime.md';
const text = fs.readFileSync(runtimePath, 'utf8');
const failures = [];

function must(fragment, label) {
  if (!text.includes(fragment)) failures.push(`Missing JARVIS policy: ${label}`);
}

function mustNot(fragment, label) {
  if (text.includes(fragment)) failures.push(`Forbidden JARVIS policy: ${label}`);
}

must('BUSINESS MODE', 'business context boundary');
must('PERSONAL MODE', 'personal context boundary');
must('never leak confidential business context into personal communications', 'cross-context privacy boundary');
must('Source-First Rule', 'source-first retrieval rule');
must('VERIFIED', 'verified state');
must('COMPLETED', 'completed state');
must('REQUIRES_APPROVAL', 'approval state');
must('Never represent intent, a draft, a queued operation, or an attempted action as COMPLETED', 'truthful completion semantics');
must('Owner Approval Gates', 'owner approval gates');
must('significant payments or transfers', 'payment approval gate');
must('irreversible deletion', 'deletion approval gate');
must('sensitive-data disclosure to third parties', 'privacy approval gate');
must('Calendar Intelligence', 'calendar capability');
must('Communication Intelligence', 'communications capability');
must('Travel Intelligence', 'travel capability');
must('Purchase Intelligence', 'purchase capability');
must('Daily Owner Brief', 'daily brief');
must('Weekly Review', 'weekly review');
must('Privacy and Least Privilege', 'least privilege');
must('Never fabricate messages, leads, customers, reservations, payments, approvals, transactions, tool results, integrations, prices, or completed actions', 'anti-fabrication rule');
must('Never mix Personal and Business contexts without owner authorization', 'strict context isolation');
must('Protect the owner\'s time, attention, money, privacy, reputation, and business interests', 'owner protection objective');

mustNot('silently bypass owner approval', 'no hidden approval bypass');

if (failures.length) {
  for (const failure of failures) console.error('FAIL ', failure);
  process.exit(1);
}

console.log('PASS  JARVIS personal/executive context isolation, truthful state, approval gates, source-first behavior, and owner protection are enforced');
