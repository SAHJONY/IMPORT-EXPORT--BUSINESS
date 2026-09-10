export type SpatialLayerId='trade_nodes'|'ports'|'rfqs'|'suppliers'|'buyers'|'shipments'|'risk';
export type SpatialEntityKind='port'|'trade_node'|'rfq'|'supplier'|'buyer'|'shipment'|'risk';
export type EvidenceState='reference'|'verified'|'unverified';

export type SpatialEntity={
  id:string;
  kind:SpatialEntityKind;
  name:string;
  lat:number;
  lon:number;
  layer:SpatialLayerId;
  evidence:EvidenceState;
  source:string;
  updatedAt?:string;
  metadata?:Record<string,string|number|boolean|null>;
};

export type SpatialLayer={
  id:SpatialLayerId;
  label:string;
  description:string;
  commercial:boolean;
  enabledByDefault:boolean;
};

export const spatialLayers:SpatialLayer[]=[
  {id:'trade_nodes',label:'Trade Nodes',description:'Strategic reference nodes used for route and market planning.',commercial:true,enabledByDefault:true},
  {id:'ports',label:'Ports',description:'Ports and terminals from approved commercial/public sources.',commercial:true,enabledByDefault:true},
  {id:'rfqs',label:'RFQs',description:'Qualified buyer demand with verified destination coordinates.',commercial:true,enabledByDefault:true},
  {id:'suppliers',label:'Suppliers',description:'Verified supplier locations only.',commercial:true,enabledByDefault:true},
  {id:'buyers',label:'Buyers',description:'Qualified buyer locations only.',commercial:true,enabledByDefault:true},
  {id:'shipments',label:'Shipments',description:'Authorized shipment positions and route milestones.',commercial:true,enabledByDefault:true},
  {id:'risk',label:'Risk',description:'Sanctions, disruption, weather and operational risk overlays from approved sources.',commercial:true,enabledByDefault:false},
];

// Reference geography only. These are not active SAHJONY deals, customers, suppliers or shipments.
export const referenceTradeNodes:SpatialEntity[]=[
  {id:'ref-mariel',kind:'port',name:'Mariel, Cuba',lat:23.0066,lon:-82.7539,layer:'trade_nodes',evidence:'reference',source:'SAHJONY reference geography'},
  {id:'ref-miami',kind:'trade_node',name:'Miami, USA',lat:25.7617,lon:-80.1918,layer:'trade_nodes',evidence:'reference',source:'SAHJONY reference geography'},
  {id:'ref-savannah',kind:'port',name:'Savannah, USA',lat:32.0809,lon:-81.0912,layer:'trade_nodes',evidence:'reference',source:'SAHJONY reference geography'},
  {id:'ref-cartagena',kind:'port',name:'Cartagena, Colombia',lat:10.3910,lon:-75.4794,layer:'trade_nodes',evidence:'reference',source:'SAHJONY reference geography'},
  {id:'ref-panama',kind:'trade_node',name:'Panama Canal',lat:9.0800,lon:-79.6800,layer:'trade_nodes',evidence:'reference',source:'SAHJONY reference geography'},
];

export function projectEquirectangular(lat:number,lon:number){
  return {x:((lon+180)/360)*100,y:((90-lat)/180)*100};
}

export function evidenceLabel(state:EvidenceState){
  return state==='verified'?'VERIFIED':state==='reference'?'REFERENCE':'UNVERIFIED';
}
