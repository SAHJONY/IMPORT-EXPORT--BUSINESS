import fs from 'node:fs';
import process from 'node:process';

const failures=[];
const read=p=>fs.readFileSync(p,'utf8');
const consumer=read('public/cuba-individual-consumers.html');
const appSource=read('src/App.tsx');
const business=appSource.slice(appSource.indexOf('function PublicSite'),appSource.indexOf('function StatePage'));
const cfg=JSON.parse(read('vercel.json'));

const forbiddenInConsumer=[
  '/business','/cuba-private-sector','/start','Business','B2B','MIPYME','MIPYMES','empresa privada','empresas privadas'
];
const forbiddenInBusiness=[
  '/cuba-consumers','/individual-consumers','/cuba-individual-consumers','/consumer-marketplace','Individual Consumer','Individual Consumers','consumidor individual','consumidores individuales'
];

for(const x of forbiddenInConsumer) if(consumer.toLowerCase().includes(x.toLowerCase())) failures.push(`Consumer platform exposes business reference: ${x}`);
for(const x of forbiddenInBusiness) if(business.toLowerCase().includes(x.toLowerCase())) failures.push(`Business platform exposes consumer reference: ${x}`);

const routes=cfg.routes||[];
const consumerRoutes=['/cuba-consumers','/individual-consumers','/cuba-individual-consumers'];
for(const r of consumerRoutes){
  const hit=routes.find(x=>x.src===r);
  if(!hit||hit.dest!=='/cuba-individual-consumers.html') failures.push(`Consumer route ${r} must resolve only to consumer HTML`);
}
const businessRoute=routes.find(x=>x.src==='/business');
if(!businessRoute||businessRoute.dest!=='/index.html') failures.push('/business must resolve only to the cinematic business application');

const consumerApi=routes.find(x=>x.src==='/consumer-marketplace(.*)');
if(!consumerApi||consumerApi.dest!=='cuba_consumer_marketplace_api.py') failures.push('Consumer API must remain on its dedicated backend');

if(failures.length){for(const f of failures)console.error('FAIL ',f);process.exit(1)}
console.log('PASS  Business and Individual Consumer customer platforms are audience-isolated');
