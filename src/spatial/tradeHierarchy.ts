export const GLOBAL_TRADE_HIERARCHY = [
  'WORLD','COUNTRY','PORT','SUPPLIER','SHIPMENT','BUYER','RFQ','MARGIN','RISK','NEXT_ACTION'
] as const;

export type GlobalTradeLevel = (typeof GLOBAL_TRADE_HIERARCHY)[number];
export type GlobalTradeNode = {
  id:string;
  level:GlobalTradeLevel;
  label:string;
  parentId?:string;
  evidence:'VERIFIED'|'UNVERIFIED'|'REFERENCE';
  source?:string;
  confidence?:number;
  metadata?:Record<string,string|number|boolean|null>;
};

export function canPromoteSpatialNode(node:GlobalTradeNode){
  return node.evidence==='VERIFIED' && Boolean(node.source) && (node.confidence===undefined || node.confidence>=0.8);
}

export function nextHierarchyLevel(level:GlobalTradeLevel){
  const index=GLOBAL_TRADE_HIERARCHY.indexOf(level);
  return index>=0 && index<GLOBAL_TRADE_HIERARCHY.length-1 ? GLOBAL_TRADE_HIERARCHY[index+1] : null;
}

export const GLOBAL_OPERATIONS_PRINCIPLE =
  'World → Country → Port → Supplier → Shipment → Buyer → RFQ → Margin → Risk → Next Action';
