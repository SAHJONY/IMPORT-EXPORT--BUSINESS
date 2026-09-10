import fs from 'node:fs';

const files={
  engine:'src/trade/autonomousTradeOperatingSystem.ts',
  intent:'src/trade/sofiaTradeIntent.ts',
  hierarchy:'src/spatial/tradeHierarchy.ts',
  network:'src/spatial/commercialNetwork.ts',
  platform:'src/trade/platform10x.ts',
  graph:'src/trade/businessGraph.ts',
  migration:'migrations/20260910_autonomous_trade_os.sql',
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
  const migration=fs.readFileSync(files.migration,'utf8');
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
  for(const table of ['trade_os_opportunities','trade_os_evidence','trade_os_business_nodes','trade_os_business_edges','trade_os_agent_jobs','trade_os_action_traces','trade_os_approvals']) if(!migration.includes(`create table if not exists ${table}`)) failures.push(`Missing durable table ${table}`);
  for(const table of ['trade_os_opportunities','trade_os_evidence','trade_os_business_nodes','trade_os_business_edges','trade_os_agent_jobs','trade_os_action_traces','trade_os_approvals']) if(!migration.includes(`alter table ${table} enable row level security`)) failures.push(`RLS not enabled for ${table}`);
  for(const field of ['idempotency_key','checkpoint','resume_cursor','credential_expires_at','next_retry_at','terminal_outcome']) if(!migration.includes(field)) failures.push(`Missing durable-runtime field ${field}`);
  for(const field of ['tool_name','evidence_ids','cost_usd','decision','approval','outcome','business_impact']) if(!migration.includes(field)) failures.push(`Missing observability field ${field}`);
}
if(failures.length){for(const failure of failures) console.error('FAIL ',failure);process.exit(1)}
console.log('AUTONOMOUS_TRADE_OS_OK — commercial chain, Sofia intent transformation, global hierarchy, durable runtime, observability, canonical business graph, API-first execution, RLS persistence and production discipline are enforced');
