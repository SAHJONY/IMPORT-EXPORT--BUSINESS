import type {TradeOpportunity} from './autonomousTradeOperatingSystem';

export type ContainerSize = "20'" | "40'" | '40HC' | 'UNKNOWN';
export type TradeIntentInput = {
  rawText: string;
  buyer?: string;
  product?: string;
  containerCount?: number;
  containerSize?: ContainerSize;
  packageSizeLiters?: number;
  packaging?: string;
  destinationPort?: string;
  destinationCountry?: string;
  timing?: string;
  specification?: string;
  budget?: number;
  currency?: string;
  incoterm?: string;
};

export type RfqCompleteness = {
  complete: boolean;
  known: string[];
  missing: string[];
  questions: string[];
};

export type CommercialWorkstream = {
  id: 'BUYER_REQUIREMENT'|'RFQ_COMPLETENESS'|'SUPPLIER_SOURCING'|'CONTAINER_UTILIZATION'|'FREIGHT_LANE'|'LANDED_COST'|'SAHJONY_MARGIN'|'COMPLIANCE'|'FORMAL_QUOTE'|'NEGOTIATION'|'PO';
  status: 'READY'|'IN_PROGRESS'|'BLOCKED'|'OWNER_APPROVAL';
  objective: string;
  evidenceRequired: string[];
};

const value = (v:unknown)=>v!==undefined&&v!==null&&String(v).trim()!=='';

export function assessRfq(input:TradeIntentInput):RfqCompleteness{
  const known:string[]=[];
  const missing:string[]=[];
  if(value(input.product)) known.push('product'); else missing.push('product');
  if((input.containerCount||0)>0) known.push('container count'); else missing.push('container count or exact quantity');
  if(value(input.containerSize)&&input.containerSize!=='UNKNOWN') known.push('container size'); else missing.push("container size (20', 40', or 40HC)");
  if(value(input.packaging)||Number(input.packageSizeLiters)>0) known.push('commercial packaging'); else missing.push('commercial packaging / bulk format');
  if(value(input.destinationPort)) known.push('destination port'); else missing.push('destination port');
  if(value(input.timing)) known.push('required timing'); else missing.push('required shipment/delivery timing');
  if(value(input.specification)) known.push('product specification'); else missing.push('product specification / grade');
  if(value(input.incoterm)) known.push('requested incoterm'); else missing.push('requested incoterm or delivery basis');
  const questions=missing.slice(0,2).map(field=>`Confirm ${field}.`);
  return {complete:missing.length===0,known,missing,questions};
}

export function buildCommercialWorkstreams(input:TradeIntentInput):CommercialWorkstream[]{
  const rfq=assessRfq(input);
  const haveLane=value(input.destinationPort);
  const haveContainer=(input.containerCount||0)>0&&value(input.containerSize)&&input.containerSize!=='UNKNOWN';
  return [
    {id:'BUYER_REQUIREMENT',status:value(input.product)&&haveContainer&&haveLane?'READY':'IN_PROGRESS',objective:'Normalize the customer request into an executable buyer requirement.',evidenceRequired:['customer message or first-party demand evidence']},
    {id:'RFQ_COMPLETENESS',status:rfq.complete?'READY':'IN_PROGRESS',objective:'Close only the missing commercial fields required for sourcing and pricing.',evidenceRequired:rfq.missing},
    {id:'SUPPLIER_SOURCING',status:rfq.complete?'IN_PROGRESS':'BLOCKED',objective:'Source credible suppliers against the exact specification, packaging, quantity and timing.',evidenceRequired:['supplier identity','capacity','lead time','supplier-backed price','commercial terms']},
    {id:'CONTAINER_UTILIZATION',status:haveContainer?'IN_PROGRESS':'BLOCKED',objective:'Calculate packaging count, payload utilization, weight/volume constraints and container fit without confusing package size with container size.',evidenceRequired:['container size','net package dimensions/weight','carrier payload constraints']},
    {id:'FREIGHT_LANE',status:haveLane?'IN_PROGRESS':'BLOCKED',objective:'Build an origin-to-destination freight lane and compare viable port/carrier options.',evidenceRequired:['origin','destination port','carrier/freight evidence','transit/route constraints']},
    {id:'LANDED_COST',status:'BLOCKED',objective:'Calculate supplier cost + inland + ocean + insurance + duties/taxes/fees + inspection + banking + other execution costs.',evidenceRequired:['supplier-backed cost','freight quote','applicable duties/fees','insurance/inspection/banking inputs']},
    {id:'SAHJONY_MARGIN',status:'BLOCKED',objective:'Protect positive SAHJONY economics before customer quote release.',evidenceRequired:['landed cost','buyer price basis','approved margin/fee structure','capital-at-risk check']},
    {id:'COMPLIANCE',status:'IN_PROGRESS',objective:'Verify buyer/supplier KYB, sanctions/export controls and product/destination-specific requirements.',evidenceRequired:['buyer KYB','supplier KYB','sanctions screening','product/destination compliance']},
    {id:'FORMAL_QUOTE',status:'BLOCKED',objective:'Generate a formal quotation only from verified material commercial inputs.',evidenceRequired:['verified landed cost','protected margin','quote validity','payment terms','delivery basis','internal approval when binding']},
    {id:'NEGOTIATION',status:'BLOCKED',objective:'Negotiate price, terms, payment, delivery and risk within delegated authority.',evidenceRequired:['quote sent','buyer engagement','counteroffers/term changes']},
    {id:'PO',status:'BLOCKED',objective:'Convert buyer acceptance into documentary commitment and governed execution.',evidenceRequired:['buyer acceptance','PO or contract','binding owner approval','payment/security conditions']},
  ];
}

export function normalizeTradeIntent(input:TradeIntentInput):TradeOpportunity{
  const rfq=assessRfq(input);
  return {
    id:`INTENT-${Date.now()}`,
    stage:rfq.complete?'RFQ':'DEMAND',
    buyer:input.buyer,
    product:input.product,
    specification:input.specification,
    quantity:input.containerCount,
    quantityUnit:input.containerSize&&input.containerSize!=='UNKNOWN'?`${input.containerSize} container(s)`:undefined,
    destination:[input.destinationPort,input.destinationCountry].filter(Boolean).join(', ')||undefined,
    incoterm:input.incoterm,
    requiredBy:input.timing,
    economics:{currency:input.currency||'USD',quantity:input.containerCount,capitalAtRiskUsd:0},
    evidence:[{id:'buyer-intent',type:'demand',status:'UNVERIFIED',source:'customer conversation',note:input.rawText}],
  };
}

export const SOFIA_SOYBEAN_OIL_EXAMPLE:TradeIntentInput={
  rawText:"soybean oil / 2 × 40' containers / 20-L packaging / Mariel / required ASAP",
  product:'soybean oil',
  containerCount:2,
  containerSize:"40'",
  packageSizeLiters:20,
  packaging:'20-L containers',
  destinationPort:'Mariel',
  destinationCountry:'Cuba',
  timing:'ASAP',
};

export const SOFIA_TRADE_TRANSFORMATION = [
  'Buyer requirement','RFQ completeness','Supplier sourcing','Container utilization','Freight lane','Landed-cost calculation','SAHJONY margin','Compliance check','Formal quote','Negotiation','PO'
] as const;
