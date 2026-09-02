import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const root = process.cwd();
const args = new Set(process.argv.slice(2));
const smokeUrlArg = process.argv.find((v) => v.startsWith('--url='));
const smokeBase = smokeUrlArg ? smokeUrlArg.slice('--url='.length).replace(/\/$/, '') : null;

const errors = [];
const warnings = [];
const passes = [];

const pass = (msg) => passes.push(msg);
const fail = (msg) => errors.push(msg);
const warn = (msg) => warnings.push(msg);
const exists = (p) => fs.existsSync(path.join(root, p));
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8');

function resolveRelativeImport(fromFile, spec) {
  const base = path.resolve(root, path.dirname(fromFile), spec);
  const candidates = [base,`${base}.ts`,`${base}.tsx`,`${base}.js`,`${base}.jsx`,`${base}.mjs`,`${base}.cjs`,`${base}.css`,`${base}.json`,path.join(base,'index.ts'),path.join(base,'index.tsx'),path.join(base,'index.js'),path.join(base,'index.jsx'),path.join(base,'index.css')];
  return candidates.find((p) => fs.existsSync(p));
}

function scanRelativeImports() {
  const srcDir = path.join(root, 'src');
  if (!fs.existsSync(srcDir)) return fail('src directory is missing');
  const files = [];
  const walk = (dir) => { for (const entry of fs.readdirSync(dir,{withFileTypes:true})) { const full=path.join(dir,entry.name); if(entry.isDirectory()) walk(full); else if(/\.(?:ts|tsx|js|jsx|mjs)$/.test(entry.name)) files.push(full); } };
  walk(srcDir);
  const importRe=/(?:import\s+(?:[^'\"]+?\s+from\s+)?|import\s*\()\s*['\"](\.[^'\"]+)['\"]/g;
  for(const abs of files){const rel=path.relative(root,abs);const text=fs.readFileSync(abs,'utf8');for(const match of text.matchAll(importRe)){const spec=match[1];if(!resolveRelativeImport(rel,spec))fail(`Missing relative import: ${rel} -> ${spec}`)}}
  if(!errors.some((e)=>e.startsWith('Missing relative import')))pass(`Relative imports resolved across ${files.length} source files`);
}

function checkRequiredFiles(){const required=['index.html','src/main.tsx','src/App.tsx','src/workflow.css','app/globals.css','public/landing.html','public/start.html','public/cuba-private-sector.html','public/cuba-es.html','public/cuba-us-desk-card.html','public/cuba-individual-consumers.html','public/global-language.js','vercel.json','unified_api.py'];for(const f of required)exists(f)?pass(`Required file present: ${f}`):fail(`Required file missing: ${f}`)}

function checkLanguageCoverage(){const htmlFiles=[];const rootIndex=path.join(root,'index.html');if(fs.existsSync(rootIndex))htmlFiles.push(rootIndex);const publicDir=path.join(root,'public');if(fs.existsSync(publicDir)){for(const entry of fs.readdirSync(publicDir,{withFileTypes:true}))if(entry.isFile()&&entry.name.toLowerCase().endsWith('.html'))htmlFiles.push(path.join(publicDir,entry.name))}const missing=[];for(const abs of htmlFiles){const rel=path.relative(root,abs);const text=fs.readFileSync(abs,'utf8');if(!/src=["']\/global-language\.js["']/i.test(text))missing.push(rel)}if(missing.length){for(const file of missing)fail(`Spanish localization layer missing: ${file}`)}else pass(`Spanish localization layer present across ${htmlFiles.length} HTML entry pages`)}

function checkVercelRoutes(){
  if(!exists('vercel.json'))return;let cfg;try{cfg=JSON.parse(read('vercel.json'))}catch(e){return fail(`vercel.json is invalid JSON: ${e.message}`)}const routes=Array.isArray(cfg.routes)?cfg.routes:[];if(!routes.length)return fail('vercel.json has no routes');
  const exact=(src)=>routes.findIndex((r)=>r.src===src);const cubaPublic=exact('/cuba-private-sector');const cubaConsumer=exact('/cuba-consumers');const cubaApi=routes.findIndex((r)=>r.src==='/cuba-private-sector/(health|leads.*)');const broadCuba=routes.findIndex((r)=>r.src==='/cuba(.*)');
  if(cubaPublic<0)fail('Missing exact public route /cuba-private-sector');else if(broadCuba>=0&&cubaPublic>broadCuba)fail('Route collision: /cuba-private-sector is shadowed by /cuba(.*)');else pass('Cuba public route is ordered before broad Cuba API matcher');
  if(cubaConsumer<0)fail('Missing exact public route /cuba-consumers');else if(broadCuba>=0&&cubaConsumer>broadCuba)fail('Route collision: /cuba-consumers is shadowed by /cuba(.*)');else pass('Cuba consumer route is ordered before broad Cuba API matcher');
  if(cubaApi<0)fail('Missing Cuba private-sector health/leads API route');else if(cubaPublic>=0&&cubaApi>cubaPublic)warn('Cuba API route appears after public exact route; exact matching is safe, but keep API route explicit');else pass('Cuba health/leads API route is explicit');
  const criticalStatic={'/':'/index.html','/business':'/index.html','/start':'/start.html','/cuba-private-sector':'/cuba-es.html','/cuba-consumers':'/cuba-individual-consumers.html','/us-desk-card':'/cuba-us-desk-card.html'};for(const [src,dest] of Object.entries(criticalStatic)){const idx=routes.findIndex((r)=>r.src===src&&r.dest===dest);if(idx<0)fail(`Critical route missing or wrong: ${src} -> ${dest}`);else{const disk=dest==='/index.html'?'index.html':`public${dest}`;exists(disk)?pass(`Critical static route verified: ${src} -> ${dest}`):fail(`Route ${src} points to missing static file ${disk}`)}}
  const ownerStatic={
    '/owner/energy':'/owner-energy-hub.html','/owner/energy/crude-oil':'/owner-energy-crude.html','/owner/energy/origination':'/owner-energy-origination.html','/owner/energy/intelligence':'/owner-energy-intelligence.html','/owner/energy/providers':'/owner-energy-providers.html','/owner/energy/compliance':'/owner-energy-compliance.html','/owner/energy/deal-flow':'/owner-energy-deal-flow.html','/owner/energy/revenue':'/owner-energy-revenue.html','/owner/energy/operations':'/owner-energy-operations.html','/owner/energy/closing':'/owner-energy-closing.html','/owner/cuba-energy':'/owner-cuba-energy.html','/owner/cuba-fuels':'/owner-cuba-fuels.html','/owner/cuba-consumers':'/owner-cuba-consumers.html','/owner/cuba-us-desk':'/cuba-us-desk.html'
  };
  for(const [src,dest] of Object.entries(ownerStatic)){const idx=routes.findIndex((r)=>r.src===src&&r.dest===dest);if(idx<0)fail(`Owner workspace route missing or wrong: ${src} -> ${dest}`);else{const disk=`public${dest}`;exists(disk)?pass(`Owner workspace route verified: ${src} -> ${dest}`):fail(`Owner route ${src} points to missing static file ${disk}`)}}
  const fsHandle=routes.findIndex((r)=>r.handle==='filesystem');const catchAll=routes.findIndex((r)=>r.src==='/(.*)'&&r.dest==='/index.html');if(fsHandle<0)fail('Missing filesystem route handle');if(catchAll<0)fail('Missing SPA catch-all route');if(fsHandle>=0&&catchAll>=0&&fsHandle<catchAll)pass('Filesystem handler precedes SPA catch-all');else if(fsHandle>=0&&catchAll>=0)fail('SPA catch-all must come after filesystem handler');
}

function checkPackageGuard(){if(!exists('package.json'))return fail('package.json is missing');const pkg=JSON.parse(read('package.json'));const prebuild=pkg.scripts?.prebuild||'';if(!prebuild.includes('deployment-guard.mjs'))fail('package.json prebuild does not invoke deployment guard');else pass('Deployment guard is wired into npm prebuild')}

async function smokeTest(base){const checks=[['/','html'],['/business','html'],['/start','html'],['/cuba-private-sector','html'],['/cuba-consumers','html'],['/us-desk-card','html'],['/owner/cuba-energy','html'],['/owner/cuba-fuels','html'],['/owner/cuba-consumers','html'],['/crm/health','json'],['/cuba-private-sector/health','json'],['/cuba-energy/health','json'],['/cuba-fuels/health','json'],['/api/connect/worldwide/health','json']];for(const [route,kind] of checks){try{const res=await fetch(`${base}${route}`,{redirect:'follow',headers:{'user-agent':'SAHJONY-Deployment-Doctor/2.3'}});const text=await res.text();if(!res.ok){fail(`Smoke ${route}: HTTP ${res.status}`);continue}if(/\{\s*"detail"\s*:\s*"Not Found"\s*\}/i.test(text)){fail(`Smoke ${route}: backend Not Found route collision`);continue}if(kind==='html'){if(!/<(?:html|main|section|div)[\s>]/i.test(text)||text.trim().length<200)fail(`Smoke ${route}: blank or invalid HTML response`);else if(/Workspace not found|requested SAHJONY workspace does not exist/i.test(text))fail(`Smoke ${route}: generic workspace-not-found fallback returned`);else pass(`Smoke ${route}: visible workspace HTML returned`)}else{try{JSON.parse(text);pass(`Smoke ${route}: JSON service responded`)}catch{fail(`Smoke ${route}: expected JSON service response`)}}}catch(e){fail(`Smoke ${route}: ${e.message}`)}}}

function report(){console.log('\nSAHJONY Deployment Doctor');console.log('=========================');for(const p of passes)console.log(`PASS  ${p}`);for(const w of warnings)console.log(`WARN  ${w}`);for(const e of errors)console.error(`FAIL  ${e}`);console.log(`\nSummary: ${passes.length} passed, ${warnings.length} warnings, ${errors.length} failed`);if(errors.length)process.exitCode=1}

checkRequiredFiles();scanRelativeImports();checkLanguageCoverage();checkVercelRoutes();if(!args.has('--bootstrap'))checkPackageGuard();if(smokeBase)await smokeTest(smokeBase);report();
