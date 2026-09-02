import fs from 'node:fs';
import process from 'node:process';

const cfg = JSON.parse(fs.readFileSync('vercel.json','utf8'));
const routes = Array.isArray(cfg.routes) ? cfg.routes : [];
const errors=[]; const passes=[];
const fail=(m)=>errors.push(m); const pass=(m)=>passes.push(m);

const publicPages={
  '/':'/index.html',
  '/business':'/index.html',
  '/cuba-private-sector':'/cuba-es.html',
  '/cuba-consumers':'/cuba-individual-consumers.html',
  '/individual-consumers':'/cuba-individual-consumers.html',
  '/cuba-individual-consumers':'/cuba-individual-consumers.html'
};

const ownerPages={
  '/owner/cuba-consumers':'/owner-cuba-consumers.html',
  '/owner/cuba-energy':'/owner-cuba-energy.html',
  '/owner/cuba-fuels':'/owner-cuba-fuels.html',
  '/owner/energy':'/owner-energy-hub.html'
};

function diskPath(dest){return dest==='/index.html' ? 'index.html' : (dest.startsWith('/') ? `public${dest}` : dest)}
function routeIndex(src,dest){return routes.findIndex(r=>r.src===src && (!dest || r.dest===dest))}

for(const [src,dest] of Object.entries({...publicPages,...ownerPages})){
  const idx=routeIndex(src,dest);
  if(idx<0) fail(`Missing exact route ${src} -> ${dest}`);
  else if(!fs.existsSync(diskPath(dest))) fail(`Route ${src} points to missing file ${diskPath(dest)}`);
  else pass(`Exact route ${src} -> ${dest}`);
}

// Broad Cuba matchers are prohibited because they can swallow current/future public Cuba pages.
const forbiddenBroad=['/cuba(.*)','/cuba-(.*)','/cuba/(.*)'];
for(const src of forbiddenBroad){
  if(routes.some(r=>r.src===src)) fail(`Forbidden broad Cuba matcher present: ${src}`);
}
if(!errors.some(e=>e.startsWith('Forbidden broad Cuba matcher'))) pass('No broad Cuba API matcher can swallow public pages');

// Known API namespaces must stay explicit.
const apiNamespaces=['/cuba-energy(.*)','/cuba-language(.*)','/cuba-private(.*)','/cuba-desk(.*)','/cuba-transition(.*)','/cuba-private-sector/(health|leads.*)'];
for(const src of apiNamespaces){
  routes.some(r=>r.src===src) ? pass(`Explicit API namespace ${src}`) : fail(`Missing explicit Cuba API namespace ${src}`);
}

// Public aliases must be before every explicit Cuba API route just as defense in depth.
const firstApi=Math.min(...apiNamespaces.map(s=>routeIndex(s)).filter(i=>i>=0));
for(const src of Object.keys(publicPages).filter(x=>x.includes('cuba')||x.includes('consumer'))){
  const idx=routeIndex(src,publicPages[src]);
  if(idx>=0 && Number.isFinite(firstApi) && idx>firstApi) fail(`Public route ${src} appears after Cuba API routes`);
}
if(!errors.some(e=>e.includes('appears after Cuba API'))) pass('Public consumer routes precede Cuba API namespaces');

// Catch-all must remain last.
const fsIdx=routes.findIndex(r=>r.handle==='filesystem');
const catchIdx=routes.findIndex(r=>r.src==='/(.*)' && r.dest==='/index.html');
if(fsIdx<0||catchIdx<0||fsIdx>catchIdx) fail('Filesystem/catch-all ordering is invalid'); else pass('Filesystem precedes SPA catch-all');
if(catchIdx!==routes.length-1) fail('SPA catch-all must be the last Vercel route'); else pass('SPA catch-all is last');

// Optional production smoke mode: --url=https://www.sahjony.com
const arg=process.argv.find(x=>x.startsWith('--url='));
if(arg){
  const base=arg.slice(6).replace(/\/$/,'');
  const checks=[
    ['/cuba-consumers','Consumidores'],
    ['/individual-consumers','Consumidores'],
    ['/cuba-individual-consumers','Consumidores'],
    ['/owner/cuba-consumers','CUBA INDIVIDUAL CONSUMERS']
  ];
  for(const [p,marker] of checks){
    try{
      const r=await fetch(base+p,{redirect:'follow',headers:{'user-agent':'SAHJONY-Route-Sentinel/1.0'}});
      const ct=r.headers.get('content-type')||''; const text=await r.text();
      if(!r.ok) fail(`Live ${p}: HTTP ${r.status}`);
      else if(!ct.includes('text/html')) fail(`Live ${p}: expected HTML, got ${ct||'unknown content-type'}`);
      else if(/\{"detail":"Not Found"\}|Workspace not found/i.test(text)) fail(`Live ${p}: wrong fallback/API response`);
      else if(!text.toLowerCase().includes(marker.toLowerCase())) fail(`Live ${p}: expected page marker not found`);
      else pass(`Live ${p}: correct HTML page`);
    }catch(e){fail(`Live ${p}: ${e.message}`)}
  }
}

console.log('\nSAHJONY Route Sentinel');
console.log('======================');
for(const p of passes) console.log(`PASS  ${p}`);
for(const e of errors) console.error(`FAIL  ${e}`);
console.log(`\nSummary: ${passes.length} passed, ${errors.length} failed`);
if(errors.length) process.exit(1);
