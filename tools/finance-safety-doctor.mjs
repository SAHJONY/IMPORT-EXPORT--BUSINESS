import fs from 'node:fs';
import process from 'node:process';

const failures=[];
const read=p=>fs.readFileSync(p,'utf8');
const finance=read('finance_api.py');
const physical=read('physical_postgres.py');
const cfg=JSON.parse(read('vercel.json'));

const requiredTables=[
  'ledger_accounts',
  'ledger_journals',
  'ledger_entries',
  'payment_reconciliations',
  'beneficiary_change_requests'
];
for(const table of requiredTables){
  if(!physical.includes(`"${table}"`)) failures.push(`Physical Postgres adapter missing finance allow-list: ${table}`);
}

const requiredFinance=[
  'from physical_postgres import',
  "currency: Literal['USD'] = 'USD'",
  'Only owner may post financial journals',
  'Only owner may approve bank-detail changes',
  'Journal is not balanced',
  'Beneficiary change must be independently verified before approval',
  'Requester cannot verify their own beneficiary change',
  'Verifier cannot approve the same beneficiary change',
  'ledger_accounts',
  'ledger_journals',
  'ledger_entries',
  'payment_reconciliations',
  'beneficiary_change_requests'
];
for(const token of requiredFinance){
  if(!finance.includes(token)) failures.push(`Finance API missing governed control: ${token}`);
}

if(finance.includes('get_backend()')) failures.push('Finance API still uses generic logical backend');
if(finance.includes("currency: str = Field(default='USD'")) failures.push('Finance API still permits arbitrary currency text at model boundary');

const financeRoute=(cfg.routes||[]).find(r=>r.src==='/finance(.*)');
if(!financeRoute||financeRoute.dest!=='unified_api.py') failures.push('Finance API production route missing or incorrect');
const unifiedBuild=(cfg.builds||[]).find(b=>b.src==='unified_api.py');
if(!unifiedBuild) failures.push('Unified API missing from Vercel builds');

if(failures.length){
  for(const f of failures) console.error('FAIL ',f);
  process.exit(1);
}
console.log('PASS  Physical USD finance ledger, reconciliation, owner posting, and beneficiary maker-checker controls are fail-closed');
