import fs from 'node:fs';
import process from 'node:process';

const cfg=JSON.parse(fs.readFileSync('vercel.json','utf8'));
const routes=Array.isArray(cfg.routes)?cfg.routes:[];
const fsIndex=routes.findIndex(r=>r.handle==='filesystem');
const catchAllIndex=routes.findIndex(r=>r.src==='/(.*)'&&r.dest==='/index.html');
const failures=[];

function verifyApiRoute(src,label){
  const apiIndex=routes.findIndex(r=>r.src===src&&r.dest==='unified_api.py');
  if(apiIndex<0)failures.push(`Missing ${src} -> unified_api.py production route`);
  if(catchAllIndex>=0&&apiIndex>=0&&apiIndex>catchAllIndex)failures.push(`${label} route is shadowed by SPA catch-all`);
  if(fsIndex>=0&&apiIndex>=0&&apiIndex>fsIndex)failures.push(`${label} API route must be declared before filesystem/SPA fallback`);
}
function verifyOwnerRoute(src,dest,label){
  const i=routes.findIndex(r=>r.src===src&&r.dest===dest);
  if(i<0)failures.push(`Missing ${label} owner route`);
  if(catchAllIndex>=0&&i>=0&&i>catchAllIndex)failures.push(`${label} owner route is shadowed by SPA catch-all`);
}

if(catchAllIndex<0)failures.push('Missing SPA catch-all route');
verifyApiRoute('/trade-agent(.*)','Trade Agent');
verifyApiRoute('/trade-certification(.*)','Trade Certification');
verifyApiRoute('/country-crm(.*)','Country CRM');
verifyApiRoute('/lead-search(.*)','Global Lead Search');
verifyApiRoute('/energy(.*)','SAHJONY Energy');
verifyOwnerRoute('/owner/energy/crude-oil','/owner-energy-crude.html','Crude Oil Command Center');
verifyOwnerRoute('/owner/energy/origination','/owner-energy-origination.html','Energy Origination');
verifyOwnerRoute('/owner/energy/deal-flow','/owner-energy-deal-flow.html','Energy Deal Flow');
verifyOwnerRoute('/owner/energy/revenue','/owner-energy-revenue.html','Energy Revenue');
verifyOwnerRoute('/owner/energy/operations','/owner-energy-operations.html','Energy Operations');
verifyOwnerRoute('/owner/energy/closing','/owner-energy-closing.html','Energy Transaction Room');
verifyOwnerRoute('/owner/energy/intelligence','/owner-energy-intelligence.html','Energy Intelligence');
verifyOwnerRoute('/owner/energy/providers','/owner-energy-providers.html','Energy Data Providers');
verifyOwnerRoute('/owner/energy/compliance','/owner-energy-compliance.html','Energy Compliance');

if(failures.length){for(const f of failures)console.error('FAIL ',f);process.exit(1)}
console.log('PASS  Trade, CRM, Lead Search, and all SAHJONY Energy routes reach production safely');
