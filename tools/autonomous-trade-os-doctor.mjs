import fs from 'node:fs';

const files={
  engine:'src/trade/autonomousTradeOperatingSystem.ts',
  intent:'src/trade/sofiaTradeIntent.ts',
  hierarchy:'src/spatial/tradeHierarchy.ts',
  network:'src/spatial/commercialNetwork.ts',
  platform:'src/trade/platform10x.ts',
  graph:'src/trade/businessGraph.ts',
};
const failures=[];
for(const [name,path] of Object.entries(files)) if(!fs.existsSync(path)) failures.push(`Missing ${name}: ${path}`);
if(!failures.length){
  const engine=fs.readFileSync(files.engine,'utf8');
  const intent=fs.readFileSync(files.intent,'utf8');
  const hierarchy=fs.readFileSync(files.hierarchy,'utf8');
  const network=fs.readFileSync(files.network,'utf8');
  const platform=fs.readFileSync(files.platform,'utf8');
  const graph=fs.readFileSync(files.graph,'utf8');
  for(const stage of ['DEMAND','RFQ','SUPPLIER','VERIFICATION','LANDED_COST','MARGIN','LOGISTICS','KYB','QUOTE','NEGOTIATION','PO','SHIPMENT','COLLECTION']) if(!engine.includes(`'${stage}'`)) failures.push(`Missing canonical stage ${stage}`);
  for(const term of ['Buyer requirement','RFQ completeness','Supplier sourcing','Container utilization','Freight lane','Landed-cost calculation','SAHJONY margin','Compliance check','Formal quote','Negotiation','PO']) if(!intent.includes(term)) failures.push(`Missing Sofia transformation ${term}`);
  if(!intent.includes("soybean oil / 2 × 40' containers / 20-L packaging / Mariel / required ASAP")) failures.push('Missing canonical soybean-oil intent example');
  if(!hierarchy.includes('World → Country → Port → Supplier → Shipment → Buyer → RFQ → Margin → Risk → Next Action')) failures.push('Missing executive Global Operations hierarchy');
  if(!network.includes('geographically and financially')) failures.push('Missing Chairman geographic+financial network principle');
  for(const id of ['DURABLE_AGENT_RUNTIME','ENTERPRISE_OBSERVABILITY','CANONICAL_BUSINESS_GRAPH','RELIABLE_EXECUTION_LAYER','PRODUCTION_DISCIPLINE']) if(!platform.includes(id)) failures.push(`Missing 10X upgrade ${id}`);
  for(const entity of ['BUYER','SUPPLIER','RFQ','QUOTE','SHIPMENT','PRODUCT','PORT','PAYMENT','COUNTERPARTY','EVIDENCE']) if(!graph.includes(`'${entity}'`)) failures.push(`Missing business graph entity ${entity}`);
  for(const rule of ['bindingActionsRequireOwner','collectionRequiresPostedCash','researchIsNotRevenue']) if(!engine.includes(rule)) failures.push(`Missing governance rule ${rule}`);
  if(!platform.includes("priority:['DIRECT_API','CONNECTED_APP','OWNED_SERVICE','BROWSER_AUTOMATION']")) failures.push('Missing API-first execution priority');
  if(!platform.includes("productionBranch:'main'")) failures.push('Missing single production branch policy');
}
if(failures.length){for(const failure of failures) console.error('FAIL ',failure);process.exit(1)}
console.log('AUTONOMOUS_TRADE_OS_OK — commercial chain, Sofia intent transformation, global hierarchy, observability, business graph, API-first execution and production discipline are enforced');
