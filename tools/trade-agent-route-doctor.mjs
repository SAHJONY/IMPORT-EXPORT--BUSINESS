import fs from 'node:fs';
import process from 'node:process';

const cfg=JSON.parse(fs.readFileSync('vercel.json','utf8'));
const routes=Array.isArray(cfg.routes)?cfg.routes:[];
const apiIndex=routes.findIndex(r=>r.src==='/trade-agent(.*)'&&r.dest==='unified_api.py');
const fsIndex=routes.findIndex(r=>r.handle==='filesystem');
const catchAllIndex=routes.findIndex(r=>r.src==='/(.*)'&&r.dest==='/index.html');
const failures=[];
if(apiIndex<0)failures.push('Missing /trade-agent(.*) -> unified_api.py production route');
if(catchAllIndex<0)failures.push('Missing SPA catch-all route');
if(apiIndex>=0&&catchAllIndex>=0&&apiIndex>catchAllIndex)failures.push('Trade Agent route is shadowed by SPA catch-all');
if(fsIndex>=0&&apiIndex>=0&&apiIndex>fsIndex)failures.push('Trade Agent API route must be declared before filesystem/SPA fallback');
if(failures.length){for(const f of failures)console.error('FAIL ',f);process.exit(1)}
console.log('PASS  Trade Agent API route reaches unified_api.py before SPA fallback');
