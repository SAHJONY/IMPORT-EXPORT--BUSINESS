export const TRADE_STAGES = [
  'DEMAND',
  'RFQ',
  'SUPPLIER',
  'VERIFICATION',
  'LANDED_COST',
  'MARGIN',
  'LOGISTICS',
  'KYB',
  'QUOTE',
  'NEGOTIATION',
  'PO',
  'SHIPMENT',
  'COLLECTION',
] as const;

export type TradeStage = (typeof TRADE_STAGES)[number];
export type EvidenceStatus = 'VERIFIED' | 'UNVERIFIED' | 'REFERENCE' | 'MISSING';
export type GateState = 'READY' | 'BLOCKED' | 'OWNER_APPROVAL';

export type EvidenceItem = {
  id: string;
  type: string;
  status: EvidenceStatus;
  source?: string;
  observedAt?: string;
  expiresAt?: string;
  confidence?: number;
  note?: string;
};

export type TradeEconomics = {
  currency: string;
  quantity?: number;
  unit?: string;
  supplierUnitCost?: number;
  freight?: number;
  duties?: number;
  insurance?: number;
  inspection?: number;
  banking?: number;
  otherCosts?: number;
  buyerUnitPrice?: number;
  targetMarginPct?: number;
  protectedFeeUsd?: number;
  capitalAtRiskUsd?: number;
};

export type TradeOpportunity = {
  id: string;
  stage: TradeStage;
  buyer?: string;
  supplier?: string;
  product?: string;
  specification?: string;
  quantity?: number;
  quantityUnit?: string;
  destination?: string;
  incoterm?: string;
  requiredBy?: string;
  paymentTerms?: string;
  economics: TradeEconomics;
  evidence: EvidenceItem[];
  ownerApprovals?: string[];
};

export type StageEvaluation = {
  stage: TradeStage;
  state: GateState;
  missing: string[];
  warnings: string[];
  nextActions: string[];
};

const verified = (o: TradeOpportunity, type: string) =>
  o.evidence.some(e => e.type === type && e.status === 'VERIFIED');
const present = (value: unknown) => value !== undefined && value !== null && String(value).trim() !== '';
const positive = (value?: number) => Number.isFinite(value) && Number(value) > 0;

export function landedCost(o: TradeOpportunity) {
  const e = o.economics;
  const qty = e.quantity ?? o.quantity ?? 0;
  const unitCost = e.supplierUnitCost ?? 0;
  const variable = qty > 0 ? unitCost * qty : 0;
  const fixed = [e.freight,e.duties,e.insurance,e.inspection,e.banking,e.otherCosts]
    .reduce((sum,n)=>sum + (Number.isFinite(n) ? Number(n) : 0),0);
  return {
    total: variable + fixed,
    perUnit: qty > 0 ? (variable + fixed) / qty : 0,
    currency: e.currency || 'USD',
  };
}

export function projectedGrossProfit(o: TradeOpportunity) {
  const e = o.economics;
  const qty = e.quantity ?? o.quantity ?? 0;
  const sell = (e.buyerUnitPrice ?? 0) * qty;
  const cost = landedCost(o).total;
  const fee = e.protectedFeeUsd ?? 0;
  const gross = sell > 0 ? sell - cost + fee : fee;
  return { revenue: sell, cost, fee, gross, marginPct: sell > 0 ? (gross / sell) * 100 : 0 };
}

const ownerApproved = (o: TradeOpportunity, key: string) => (o.ownerApprovals || []).includes(key);

export function evaluateStage(o: TradeOpportunity, stage: TradeStage): StageEvaluation {
  const missing: string[] = [];
  const warnings: string[] = [];
  const nextActions: string[] = [];
  let ownerGate = false;

  switch(stage){
    case 'DEMAND':
      if(!present(o.buyer)) missing.push('buyer identity');
      if(!present(o.product)) missing.push('product');
      if(!positive(o.quantity)) missing.push('quantity');
      if(!present(o.destination)) missing.push('destination');
      if(!present(o.requiredBy)) missing.push('required timing');
      break;
    case 'RFQ':
      if(!verified(o,'demand')) missing.push('verified demand evidence');
      if(!present(o.specification)) missing.push('commercial specification');
      if(!present(o.quantityUnit)) missing.push('quantity unit');
      if(!present(o.incoterm)) missing.push('requested incoterm');
      break;
    case 'SUPPLIER':
      if(!verified(o,'rfq')) missing.push('RFQ complete evidence');
      if(!present(o.supplier)) missing.push('supplier candidate');
      if(!verified(o,'supplier_quote')) missing.push('supplier-backed price');
      break;
    case 'VERIFICATION':
      for(const key of ['supplier_identity','supplier_capacity','supplier_compliance']) if(!verified(o,key)) missing.push(key.replaceAll('_',' '));
      break;
    case 'LANDED_COST':
      if(!positive(o.economics.supplierUnitCost)) missing.push('supplier unit cost');
      if(!verified(o,'freight')) missing.push('freight evidence');
      if(landedCost(o).total <= 0) missing.push('computable landed cost');
      break;
    case 'MARGIN': {
      const gp = projectedGrossProfit(o);
      if(gp.gross <= 0) missing.push('positive protected gross profit');
      if((o.economics.capitalAtRiskUsd ?? 0) > 0) { warnings.push('positive SAHJONY capital exposure'); ownerGate = true; }
      if(!verified(o,'economics')) missing.push('evidenced economics');
      break;
    }
    case 'LOGISTICS':
      for(const key of ['route','capacity','documents']) if(!verified(o,key)) missing.push(`verified logistics ${key}`);
      break;
    case 'KYB':
      for(const key of ['buyer_kyb','supplier_kyb','sanctions']) if(!verified(o,key)) missing.push(key.replaceAll('_',' '));
      break;
    case 'QUOTE':
      if(!verified(o,'margin_protection')) missing.push('margin protection evidence');
      if(!verified(o,'quote_basis')) missing.push('quote basis');
      if(!ownerApproved(o,'binding_quote')) ownerGate = true;
      break;
    case 'NEGOTIATION':
      if(!verified(o,'quote_sent')) missing.push('quote delivery evidence');
      if(!verified(o,'buyer_engagement')) missing.push('buyer negotiation engagement');
      break;
    case 'PO':
      if(!verified(o,'buyer_acceptance')) missing.push('buyer acceptance');
      if(!verified(o,'purchase_order')) missing.push('purchase order / contract evidence');
      if(!ownerApproved(o,'binding_contract')) ownerGate = true;
      break;
    case 'SHIPMENT':
      for(const key of ['payment_security','shipment_booking','shipping_documents']) if(!verified(o,key)) missing.push(key.replaceAll('_',' '));
      if(!ownerApproved(o,'shipment_release')) ownerGate = true;
      break;
    case 'COLLECTION':
      if(!verified(o,'delivery')) missing.push('delivery evidence');
      if(!verified(o,'cash_received')) missing.push('posted/reconciled cash receipt');
      if(!verified(o,'profit_reconciled')) missing.push('reconciled SAHJONY gross profit');
      break;
  }

  if(missing.length) nextActions.push(...missing.map(item=>`Obtain ${item}`));
  if(ownerGate) nextActions.push('Request Chairman approval for binding or capital-impacting action');
  return {stage,state:missing.length?'BLOCKED':ownerGate?'OWNER_APPROVAL':'READY',missing,warnings,nextActions};
}

export function operatingPicture(o: TradeOpportunity) {
  const stages = TRADE_STAGES.map(stage=>evaluateStage(o,stage));
  const currentIndex = TRADE_STAGES.indexOf(o.stage);
  const current = evaluateStage(o,o.stage);
  const firstBlocked = stages.find((gate,index)=>index >= currentIndex && gate.state !== 'READY');
  return {
    opportunityId:o.id,
    current,
    stages,
    nextGate:firstBlocked || null,
    economics:{...landedCost(o),...projectedGrossProfit(o)},
    verifiedEvidence:o.evidence.filter(e=>e.status==='VERIFIED').length,
    totalEvidence:o.evidence.length,
    autonomous: current.state === 'READY' && (o.economics.capitalAtRiskUsd ?? 0) <= 0,
  };
}

export const TRADE_OPERATING_RULES = {
  stageOrder: TRADE_STAGES,
  evidenceFirst: true,
  zeroCapitalDefault: true,
  bindingActionsRequireOwner: true,
  collectionRequiresPostedCash: true,
  researchIsNotRevenue: true,
  supplierIdentityProtectedUntilCommerciallyRequired: true,
} as const;
