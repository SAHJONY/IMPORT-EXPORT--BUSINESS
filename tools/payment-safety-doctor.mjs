import fs from 'node:fs';
import process from 'node:process';

const failures=[];
const read=p=>fs.readFileSync(p,'utf8');
const engine=read('payment_engine.py');
const api=read('payment_api.py');
const ownerPage=read('public/owner-payments.html');
const consumer=read('public/cuba-individual-consumers.html').toLowerCase();
const business=read('public/landing.html').toLowerCase();
const cfg=JSON.parse(read('vercel.json'));

const requiredEngine=[
  "currency: str = 'USD'",
  "All SAHJONY transactions must be denominated in USD",
  "automatic_supplier_payout: bool = False",
  "automatic_shipment_release: bool = False",
  "compliance_required_before_payment: bool = True",
  "owner_release_required: bool = True",
  "NO_AUTOMATIC_SUPPLIER_PAYOUT",
  "NO_AUTOMATIC_SHIPMENT_RELEASE"
];
for(const token of requiredEngine) if(!engine.includes(token)) failures.push(`Payment engine missing hard rule: ${token}`);

const requiredApi=[
  "x_role != 'owner'",
  "verify_owner_token",
  "currency: Literal['USD'] = 'USD'",
  "supplier_payout_allowed':False",
  "shipment_release_allowed':False",
  "Full customer funds confirmation is required for release",
  "Compliance clearance is required for release"
];
for(const token of requiredApi) if(!api.includes(token)) failures.push(`Payment API missing guard: ${token}`);

const requiredOwnerPage=[
  "sessionStorage.getItem('sahjony.owner.token')",
  "location.replace('/owner-login')",
  "Authorization':'Bearer '+token",
  "X-Role':'owner",
  "/owner-payments/cases",
  "currency='USD'"
];
for(const token of requiredOwnerPage) if(!ownerPage.includes(token)) failures.push(`Owner payments page missing protection: ${token}`);
if(!ownerPage.includes('/global-language.js')) failures.push('Owner payments page missing global language runtime');

for(const token of ['/owner/payments','/owner-payments']){
  if(consumer.includes(token)) failures.push(`Consumer UI exposes private payment control: ${token}`);
  if(business.includes(token)) failures.push(`Business UI exposes private payment control: ${token}`);
}

const routes=cfg.routes||[];
const route=routes.find(r=>r.src==='/owner-payments(.*)');
if(!route||route.dest!=='payment_api.py') failures.push('Owner payments API route missing or incorrect');
const pageRoute=routes.find(r=>r.src==='/owner/payments');
if(!pageRoute||pageRoute.dest!=='/owner-payments.html') failures.push('Private Owner payments page route missing or incorrect');
const build=(cfg.builds||[]).find(b=>b.src==='payment_api.py');
if(!build) failures.push('Payment API missing from Vercel builds');

if(failures.length){for(const f of failures)console.error('FAIL ',f);process.exit(1)}
console.log('PASS  USD-only payments are Owner-governed; supplier payout and shipment release remain fail-closed');
