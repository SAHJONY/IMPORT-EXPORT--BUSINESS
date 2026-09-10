export const TRADE_OS_10X_UPGRADES = [
  {
    id:'DURABLE_AGENT_RUNTIME',
    title:'Durable agent runtime',
    objective:'Jobs survive browser failures, deployments, authentication expiry, provider errors and API outages.',
    required:['durable job id','checkpointed state','idempotency key','retry policy','dead-letter state','credential-expiry state','resume cursor','terminal outcome'],
  },
  {
    id:'ENTERPRISE_OBSERVABILITY',
    title:'Enterprise observability',
    objective:'Every agent action is attributable, replayable and economically measurable.',
    required:['trace','tool','evidence','cost','decision','approval','outcome','business impact'],
  },
  {
    id:'CANONICAL_BUSINESS_GRAPH',
    title:'Canonical business graph',
    objective:'Buyer, supplier, RFQ, quote, shipment, product, port, payment, counterparty and evidence resolve to one relational truth.',
    required:['buyer','supplier','rfq','quote','shipment','product','port','payment','counterparty','evidence'],
  },
  {
    id:'RELIABLE_EXECUTION_LAYER',
    title:'Reliable execution layer',
    objective:'Use direct APIs/connectors first; browser automation is a governed fallback, not the system of record.',
    required:['api-first routing','provider health','browser fallback','approval policy','idempotency','evidence capture','fail-closed behavior'],
  },
  {
    id:'PRODUCTION_DISCIPLINE',
    title:'Production discipline',
    objective:'Minimize deployment churn while preserving strong CI/CD, one production branch, controlled previews and verified release promotion.',
    required:['main production branch','preview suppression policy','CI gates','release evidence','production verification','rollback path'],
  },
] as const;

export type PlatformUpgradeId=(typeof TRADE_OS_10X_UPGRADES)[number]['id'];

export type AgentActionTrace={
  traceId:string;
  jobId:string;
  actionId:string;
  agent:string;
  department:string;
  tool:string;
  provider?:string;
  goal:string;
  evidenceIds:string[];
  costUsd?:number;
  risk:'LOW'|'MEDIUM'|'HIGH'|'CRITICAL';
  decision:string;
  approval:'NOT_REQUIRED'|'PENDING'|'APPROVED'|'REJECTED';
  state:'QUEUED'|'RUNNING'|'WAITING'|'RETRYING'|'BLOCKED'|'SUCCEEDED'|'FAILED'|'CANCELLED';
  outcome?:string;
  businessImpact?:{
    revenuePotentialUsd?:number;
    grossProfitPotentialUsd?:number;
    cycleTimeMinutesSaved?:number;
    riskReduced?:string;
    stageAdvanced?:string;
  };
  startedAt?:string;
  completedAt?:string;
};

export type DurableAgentJob={
  id:string;
  goal:string;
  agent:string;
  department:string;
  idempotencyKey:string;
  state:'QUEUED'|'RUNNING'|'WAITING_AUTH'|'WAITING_PROVIDER'|'RETRYING'|'BLOCKED'|'SUCCEEDED'|'FAILED'|'CANCELLED';
  attempt:number;
  maxAttempts:number;
  checkpoint?:Record<string,unknown>;
  resumeCursor?:string;
  nextRetryAt?:string;
  credentialExpiresAt?:string;
  lastError?:string;
  terminalOutcome?:string;
};

export const EXECUTION_ROUTING_POLICY={
  priority:['DIRECT_API','CONNECTED_APP','OWNED_SERVICE','BROWSER_AUTOMATION'] as const,
  browserRole:'fallback/execution surface',
  tinyFishRole:'governed browser fallback; never canonical source of truth',
  failClosed:true,
  requireEvidence:true,
  requireIdempotency:true,
} as const;

export const PRODUCTION_POLICY={
  productionBranch:'main',
  deployOnlyVerifiedMain:true,
  suppressUnnecessaryPreviews:true,
  requireCIGates:true,
  requireProductionRouteVerification:true,
  requireRollbackPath:true,
  noBillingUpgradeWithoutChairmanApproval:true,
} as const;
