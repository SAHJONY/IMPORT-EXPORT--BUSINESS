export type BusinessEntityType='BUYER'|'SUPPLIER'|'RFQ'|'QUOTE'|'SHIPMENT'|'PRODUCT'|'PORT'|'PAYMENT'|'COUNTERPARTY'|'EVIDENCE';
export type BusinessGraphNode={id:string;type:BusinessEntityType;externalRef?:string;name?:string;status:string;sourceOfTruth:string;verifiedAt?:string;confidence?:number;metadata?:Record<string,unknown>};
export type BusinessGraphEdge={id:string;from:string;to:string;relation:string;evidenceIds:string[];verified:boolean;createdAt:string};

export type CanonicalBusinessGraph={nodes:BusinessGraphNode[];edges:BusinessGraphEdge[]};

export function validateBusinessGraph(graph:CanonicalBusinessGraph){
  const ids=new Set(graph.nodes.map(n=>n.id));
  const errors:string[]=[];
  const duplicateIds=graph.nodes.map(n=>n.id).filter((id,i,a)=>a.indexOf(id)!==i);
  if(duplicateIds.length) errors.push(`duplicate node ids: ${[...new Set(duplicateIds)].join(', ')}`);
  for(const edge of graph.edges){
    if(!ids.has(edge.from)) errors.push(`missing edge source ${edge.from}`);
    if(!ids.has(edge.to)) errors.push(`missing edge target ${edge.to}`);
    if(edge.verified&&edge.evidenceIds.length===0) errors.push(`verified edge ${edge.id} lacks evidence`);
  }
  return {ok:errors.length===0,errors};
}

export const CANONICAL_GRAPH_RULES={
  oneRelationalTruth:true,
  evidenceRequiredForVerifiedRelationships:true,
  sourceOfTruthRequired:true,
  crmRecordIsNotCommercialStage:true,
  researchSignalIsNotDemand:true,
  poIsNotCollection:true,
} as const;
