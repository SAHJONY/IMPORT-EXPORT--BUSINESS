import type {TradeStage} from '../trade/autonomousTradeOperatingSystem';
import type {GlobalTradeLevel} from './tradeHierarchy';

export type CommercialNetworkNode={
  id:string;
  level:GlobalTradeLevel;
  name:string;
  country?:string;
  port?:string;
  lat?:number;
  lon?:number;
  parentId?:string;
  stage?:TradeStage;
  currency?:string;
  dealValueUsd?:number;
  landedCostUsd?:number;
  projectedGrossProfitUsd?:number;
  marginPct?:number;
  capitalAtRiskUsd?:number;
  riskScore?:number;
  confidence?:number;
  evidence:'VERIFIED'|'UNVERIFIED'|'REFERENCE';
  nextAction?:string;
  blocker?:string;
  source?:string;
};

export function commercialValue(node:CommercialNetworkNode){
  const value=node.dealValueUsd??0;
  const gp=node.projectedGrossProfitUsd??0;
  const risk=Math.min(Math.max(node.riskScore??50,0),100);
  const confidence=Math.min(Math.max(node.confidence??0,0),1);
  const capital=node.capitalAtRiskUsd??0;
  return {
    riskAdjustedGrossProfitUsd:gp*confidence*(1-risk/100),
    returnOnCapital:capital>0?gp/capital:null,
    grossMarginPct:value>0?(gp/value)*100:(node.marginPct??null),
  };
}

export function chairmanPriority(node:CommercialNetworkNode){
  const c=commercialValue(node);
  const exposurePenalty=(node.capitalAtRiskUsd??0)*0.25;
  return c.riskAdjustedGrossProfitUsd-exposurePenalty;
}

export const CHAIRMAN_NETWORK_VIEW={
  geographic:['world','country','port','supplier','shipment','buyer'],
  financial:['deal value','landed cost','projected gross profit','margin','capital at risk'],
  control:['stage','risk','confidence','blocker','next action'],
  principle:'The Chairman sees the commercial network geographically and financially.',
} as const;
