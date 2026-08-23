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

if(catchAllIndex<0)failures.push('Missing SPA catch-all route');
verifyApiRoute('/trade-agent(.*)','Trade Agent');
verifyApiRoute('/trade-certification(.*)','Trade Certification');

if(failures.length){for(const f of failures)console.error('FAIL ',f);process.exit(1)}
console.log('PASS  Trade Agent and Trade Certification routes reach unified_api.py before SPA fallback');
