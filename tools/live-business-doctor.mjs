import fs from 'node:fs';
import process from 'node:process';

const errors=[]; const warnings=[]; const passes=[];
const pass=m=>passes.push(m); const fail=m=>errors.push(m); const warn=m=>warnings.push(m);
const read=p=>fs.readFileSync(p,'utf8'); const exists=p=>fs.existsSync(p);
const requireFile=p=>exists(p)?pass(`File present: ${p}`):fail(`Missing required file: ${p}`);

const required=[
  'vercel.json','requirements.txt','auth.py','physical_postgres.py','payment_api.py','cuba_partner_api.py',
  'cuba_consumer_marketplace_api.py','pricing_api.py','pricing_engine.py','payment_engine.py',
  'public/cuba-partners.html','public/cuba-individual-consumers.html','public/owner-cuba-partners.html',
  'public/owner-payments.html','public/owner-pricing.html','public/global-language.js'
];
required.forEach(requireFile);

function contains(file,needle,label){if(!exists(file))return;read(file).includes(needle)?pass(label):fail(label)}
function excludes(file,needle,label){if(!exists(file))return;!read(file).includes(needle)?pass(label):fail(label)}

if(exists('vercel.json')){
  const cfg=JSON.parse(read('vercel.json')); const routes=cfg.routes||[];
  const route=(src,dest)=>routes.some(r=>r.src===src&&(!dest||r.dest===dest));
  route('/cuba-partners','/cuba-partners.html')?pass('Partner public route configured'):fail('Partner public route missing');
  route('/cuba-partners-api(.*)','cuba_partner_api.py')?pass('Partner API route configured'):fail('Partner API route missing');
  route('/owner/cuba-partners','/owner-cuba-partners.html')?pass('Owner Partner route configured'):fail('Owner Partner route missing');
  route('/owner-payments(.*)','payment_api.py')?pass('Owner Payments API route configured'):fail('Owner Payments API route missing');
  route('/consumer-marketplace(.*)','cuba_consumer_marketplace_api.py')?pass('Consumer API route configured'):fail('Consumer API route missing');
  const dep=cfg.git?.deploymentEnabled;
  if(dep && dep.main===true && dep['*']===false) pass('Vercel auto-deployment restricted to main');
  else warn('Vercel branch deployment restriction is not explicitly main-only');
}

contains('physical_postgres.py','"trade_payment_ledger"','Physical payment ledger allow-listed');
contains('physical_postgres.py','"trade_payment_events"','Append-only payment event table allow-listed');
contains('physical_postgres.py','"cuba_partner_accounts"','Physical partner account table allow-listed');
contains('physical_postgres.py','"cuba_partner_referrals"','Physical partner referral table allow-listed');
contains('payment_api.py',"from physical_postgres import",'Payment API uses physical Postgres tables');
contains('cuba_partner_api.py',"from physical_postgres import",'Partner API uses physical Postgres tables');
contains('payment_api.py',"SUPPLIER_PAYOUT_AUTHORIZED",'Supplier payout audit event implemented');
contains('payment_api.py',"SHIPMENT_RELEASE_AUTHORIZED",'Shipment release audit event implemented');
contains('payment_api.py',"authorize-supplier-payout",'Supplier payout has independent endpoint');
contains('payment_api.py',"authorize-shipment-release",'Shipment release has independent endpoint');
contains('payment_api.py',"Combined release is disabled",'Combined payout/shipment release disabled');
contains('payment_api.py',"'currency':'USD'",'Payment API enforces canonical USD records');
contains('cuba_partner_api.py',"'currency':'USD'",'Partner API records commissions in USD');
contains('cuba_partner_api.py',"Commission payout must be recorded through the governed payment workflow",'Partner API blocks direct paid commission state');
contains('auth.py',"owner_mfa_required",'Owner MFA control exists');
contains('auth.py',"decode_neon_jwt",'Neon Auth JWT verification exists');

const consumer=exists('public/cuba-individual-consumers.html')?read('public/cuba-individual-consumers.html'):'';
const partner=exists('public/cuba-partners.html')?read('public/cuba-partners.html'):'';
for(const [name,text] of [['Consumer',consumer],['Partner',partner]]){
  if(/href=["']\/owner\b/i.test(text)) fail(`${name} public page exposes Owner navigation`); else pass(`${name} public page hides Owner navigation`);
}
if(/href=["']\/(business|cuba-private-sector)\b/i.test(consumer)) fail('Consumer page cross-links to Business'); else pass('Consumer page is isolated from Business navigation');
if(/href=["']\/(business|cuba-private-sector|cuba-consumers|individual-consumers)\b/i.test(partner)) fail('Partner page cross-links to customer platforms'); else pass('Partner page is isolated from customer platforms');

excludes('payment_api.py',"supplier_payout_allowed':True,\n        'shipment_release_allowed':True",'No code path jointly authorizes supplier payout and shipment release');

const liveArg=process.argv.find(v=>v.startsWith('--url='));
if(liveArg){
  const base=liveArg.slice(6).replace(/\/$/,'');
  const checks=[
    ['/cuba-partners','html'],['/cuba-partners-api/health','json'],['/owner/cuba-partners','html'],
    ['/owner/payments','html'],['/cuba-consumers','html'],['/owner-payments/health','json']
  ];
  for(const [path,kind] of checks){
    try{
      const r=await fetch(base+path,{redirect:'follow',headers:{'user-agent':'SAHJONY-Live-Business-Doctor/1.0'}});
      const text=await r.text();
      if(!r.ok) fail(`Live ${path}: HTTP ${r.status}`);
      else if(/\{\s*"detail"\s*:\s*"Not Found"/i.test(text)) fail(`Live ${path}: route Not Found`);
      else if(kind==='json'){try{JSON.parse(text);pass(`Live ${path}: JSON service healthy`)}catch{fail(`Live ${path}: invalid JSON`)}}
      else if(text.length<200) fail(`Live ${path}: response too small`); else pass(`Live ${path}: HTML workspace served`);
    }catch(e){fail(`Live ${path}: ${e.message}`)}
  }
}

console.log('\nSAHJONY Live Business Doctor');
console.log('============================');
for(const p of passes)console.log('PASS ',p);
for(const w of warnings)console.log('WARN ',w);
for(const e of errors)console.error('FAIL ',e);
console.log(`\nSummary: ${passes.length} passed, ${warnings.length} warnings, ${errors.length} failed`);
if(errors.length)process.exitCode=1;
