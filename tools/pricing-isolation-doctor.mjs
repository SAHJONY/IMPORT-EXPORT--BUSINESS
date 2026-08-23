import fs from 'node:fs';
import process from 'node:process';

const failures=[];
const read=p=>fs.readFileSync(p,'utf8');
const pricing=read('pricing_engine.py');
const pricingApi=read('pricing_api.py');
const consumer=read('cuba_consumer_marketplace_api.py');
const publicConsumer=read('public/cuba-individual-consumers.html').toLowerCase();
const business=read('public/landing.html').toLowerCase();
const cfg=JSON.parse(read('vercel.json'));

const requiredPricing=[
  "CONSUMER_POLICY",
  "BUSINESS_POLICY",
  "consumer_quote",
  "business_quote",
  "public_quote_view",
  "minimum_margin_pct",
  "quote_valid_hours",
  "customer_can_see_cost_basis: bool = False",
  "Discount would breach minimum margin floor",
  "TRANSACTION_CURRENCY = 'USD'",
  "ALL_CUSTOMER_TRANSACTIONS_QUOTES_INVOICES_DEPOSITS_AND_BALANCES_ARE_USD"
];
for(const token of requiredPricing) if(!pricing.includes(token)) failures.push(`Pricing engine missing protection: ${token}`);

if(!pricing.includes("volume_pricing=False")) failures.push('Consumer policy must disable volume pricing');
if(!pricing.includes("volume_pricing=True")) failures.push('Business policy must support independent volume pricing');
if(!pricing.includes("kwargs.pop('volume_discount_pct', None)")) failures.push('Consumer quote must strip volume discounts');
if(!pricing.includes("if k != 'internal'")) failures.push('Public quote view must remove pricing internals');

const forbiddenPublicPricing=['supplier_cost','landed_cost','gross_profit','realized_margin_pct','requested_margin_pct','volume_discount_pct','wholesale cost','internal margin','/owner/pricing','/owner-pricing'];
for(const token of forbiddenPublicPricing){
  if(publicConsumer.includes(token)) failures.push(`Consumer public UI leaks internal pricing data: ${token}`);
  if(business.includes(token)) failures.push(`Business public UI leaks internal pricing data: ${token}`);
}

if(consumer.includes('business_quote(')) failures.push('Consumer marketplace backend must not call business pricing');
if(!consumer.includes("Currency = Literal['USD']")) failures.push('Consumer marketplace must reject non-USD transaction currencies');
if(!consumer.includes("'transaction_currency':'USD'")) failures.push('Consumer marketplace health must declare USD transaction currency');
if(publicConsumer.includes('<option>eur</option>')||publicConsumer.includes('value="eur"')) failures.push('Consumer public UI must not offer EUR');
if(!publicConsumer.includes('name="budget_currency" value="usd" readonly')) failures.push('Consumer public UI must lock budget currency to USD');

if(!pricingApi.includes("x_role != 'owner'")) failures.push('Pricing API must enforce Owner role');
if(!pricingApi.includes('verify_owner_token')) failures.push('Pricing API must verify Owner credential');
if(!pricingApi.includes('TRANSACTION_CURRENCY')) failures.push('Owner pricing API must use canonical USD transaction currency');

const routes=cfg.routes||[];
const ownerPage=routes.find(r=>r.src==='/owner/pricing');
if(!ownerPage||ownerPage.dest!=='/owner-pricing.html') failures.push('Owner pricing page route missing or incorrect');
const ownerApi=routes.find(r=>r.src==='/owner-pricing(.*)');
if(!ownerApi||ownerApi.dest!=='pricing_api.py') failures.push('Owner pricing API route missing or incorrect');
const pricingBuild=(cfg.builds||[]).find(b=>b.src==='pricing_api.py');
if(!pricingBuild) failures.push('Owner pricing API is not included in Vercel builds');

if(failures.length){for(const f of failures)console.error('FAIL ',f);process.exit(1)}
console.log('PASS  Consumer and business pricing are isolated, Owner-only, and all transactions are USD');
