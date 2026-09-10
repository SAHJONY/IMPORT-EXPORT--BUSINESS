import fs from 'node:fs/promises';
import path from 'node:path';

const ROOT = process.cwd();
const CONFIG_PATH = path.join(ROOT, 'config', 'us-cuba-landed-logistics-engine.json');
const OUT_DIR = path.join(ROOT, 'public', 'data', 'us-cuba-landed-logistics');
const LATEST_PATH = path.join(OUT_DIR, 'latest.json');
const HISTORY_PATH = path.join(OUT_DIR, 'history.json');
const MAX_HISTORY = 500;

async function readJson(file, fallback = null) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); } catch { return fallback; }
}

function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function sumKnownCostComponents(components = {}) {
  let total = 0;
  const missing = [];
  const known = {};
  for (const [key, value] of Object.entries(components)) {
    const n = num(value);
    if (n === null) missing.push(key);
    else { known[key] = n; total += n; }
  }
  return { knownTotal: total, known, missing };
}

function normalizeEvidence(candidate = {}) {
  const ev = candidate.evidence || {};
  return {
    bookable_route: Boolean(ev.bookable_route),
    first_hand_supplier_or_direct_contract_rate: Boolean(ev.first_hand_supplier_or_direct_contract_rate),
    cargo_acceptance: Boolean(ev.cargo_acceptance),
    current_cuba_customs_rule_set: Boolean(ev.current_cuba_customs_rule_set),
    applicable_customs_regime: Boolean(ev.applicable_customs_regime),
    required_documents: Boolean(ev.required_documents),
    government_fees_or_explicit_not_applicable: Boolean(ev.government_fees_or_explicit_not_applicable),
    authorized_release_operator_or_explicit_self_clearance_rule: Boolean(ev.authorized_release_operator_or_explicit_self_clearance_rule),
    release_service_rate_or_explicit_no_commercial_fee: Boolean(ev.release_service_rate_or_explicit_no_commercial_fee),
    terminal_fees_or_explicit_inclusion: Boolean(ev.terminal_fees_or_explicit_inclusion),
    final_mile_rate_or_explicit_port_release_only_scope: Boolean(ev.final_mile_rate_or_explicit_port_release_only_scope),
    commercial_terms: Boolean(ev.commercial_terms)
  };
}

function determineStatus(candidate, requiredEvidence) {
  if (candidate.blockedCompliance) return 'BLOCKED_COMPLIANCE';
  if (candidate.notBookable) return 'NOT_BOOKABLE';
  const evidence = normalizeEvidence(candidate);
  const missingEvidence = requiredEvidence.filter(k => !evidence[k]);
  const costs = sumKnownCostComponents(candidate.costs || {});
  if (missingEvidence.length === 0 && costs.missing.length === 0) return 'VERIFIED_LANDED_COST';
  if (Object.values(evidence).some(Boolean) || Object.keys(costs.known).length > 0) return 'PARTIALLY_VERIFIED';
  return 'INPUTS_REQUIRED';
}

function scoreCandidate(candidate, config) {
  const ev = normalizeEvidence(candidate);
  const w = config.ranking || {};
  const compliance = candidate.blockedCompliance || candidate.notBookable ? 0 : (ev.bookable_route && ev.current_cuba_customs_rule_set ? 1 : 0.4);
  const verifiedTotalCost = candidate.status === 'VERIFIED_LANDED_COST' ? 1 : 0;
  const firstHand = ev.first_hand_supplier_or_direct_contract_rate ? 1 : 0;
  const release = ev.authorized_release_operator_or_explicit_self_clearance_rule && ev.release_service_rate_or_explicit_no_commercial_fee ? 1 : 0;
  const finalMile = ev.final_mile_rate_or_explicit_port_release_only_scope ? 1 : 0;
  const speed = num(candidate.speedScore) ?? 0;
  const capital = candidate.requiresSahjonyCapital ? 0 : 1;
  return Math.round(
    compliance * (w.complianceAndBookability || 0) +
    verifiedTotalCost * (w.verifiedTotalCost || 0) +
    firstHand * (w.firstHandEconomics || 0) +
    Math.max(0, Math.min(1, speed)) * (w.speed || 0) +
    release * (w.cubaReleaseConfidence || 0) +
    finalMile * (w.finalMileCoverage || 0) +
    capital * (w.minimalSahjonyCapitalExposure || 0)
  );
}

function decisionLabels(candidates) {
  const verified = candidates.filter(c => c.status === 'VERIFIED_LANDED_COST');
  if (!verified.length) return [];
  const byCost = [...verified].filter(c => c.knownTotal != null).sort((a,b) => a.knownTotal - b.knownTotal);
  const byScore = [...verified].sort((a,b) => b.score - a.score);
  const labels = [];
  if (byCost[0]) labels.push({ label: 'CHEAPEST_VERIFIED', candidateId: byCost[0].id });
  if (byScore[0]) labels.push({ label: 'BEST_VALUE_VERIFIED', candidateId: byScore[0].id });
  const fastest = [...verified].sort((a,b) => (b.speedScore || 0) - (a.speedScore || 0))[0];
  if (fastest) labels.push({ label: 'FASTEST_VERIFIED', candidateId: fastest.id });
  return labels;
}

await fs.mkdir(OUT_DIR, { recursive: true });
const config = JSON.parse(await fs.readFile(CONFIG_PATH, 'utf8'));

const inputFiles = Object.fromEntries(Object.entries(config.inputs || {}).map(([k,v]) => [k, path.join(ROOT, v)]));
const inputs = {};
for (const [key, file] of Object.entries(inputFiles)) inputs[key] = await readJson(file, null);

// The engine is conservative by design: it does not infer route candidates from incompatible scanner schemas.
// Candidates must be emitted explicitly by a route/supplier transaction adapter in `public/data/us-cuba-landed-logistics/candidates.json`.
const candidateInputPath = path.join(OUT_DIR, 'candidates.json');
const candidateInput = await readJson(candidateInputPath, { candidates: [] });
const requiredEvidence = config.mandatoryEvidenceForVerifiedLandedCost || [];

const candidates = (candidateInput.candidates || []).map(raw => {
  const costs = sumKnownCostComponents(raw.costs || {});
  const status = determineStatus(raw, requiredEvidence);
  const candidate = {
    ...raw,
    status,
    knownTotal: Object.keys(costs.known).length ? costs.knownTotal : null,
    knownCosts: costs.known,
    missingCostComponents: costs.missing,
    missingEvidence: requiredEvidence.filter(k => !normalizeEvidence(raw)[k])
  };
  candidate.score = scoreCandidate(candidate, config);
  candidate.quoteReady = status === 'VERIFIED_LANDED_COST';
  candidate.decision = candidate.quoteReady ? 'QUOTE_READY_FOR_REVIEW' : (status === 'BLOCKED_COMPLIANCE' || status === 'NOT_BOOKABLE' ? 'BLOCKED' : 'DO_NOT_QUOTE_YET');
  return candidate;
});

const labels = decisionLabels(candidates);
const latest = {
  engine: config.engine,
  version: config.version,
  status: 'ACTIVE',
  generatedAt: new Date().toISOString(),
  policy: config.commercialPolicy,
  vehiclePolicy: config.vehiclePolicy,
  inputAvailability: Object.fromEntries(Object.entries(inputs).map(([k,v]) => [k, Boolean(v)])),
  summary: {
    candidates: candidates.length,
    verifiedLandedCost: candidates.filter(c => c.status === 'VERIFIED_LANDED_COST').length,
    partiallyVerified: candidates.filter(c => c.status === 'PARTIALLY_VERIFIED').length,
    blocked: candidates.filter(c => c.status === 'BLOCKED_COMPLIANCE' || c.status === 'NOT_BOOKABLE').length,
    quoteReady: candidates.filter(c => c.quoteReady).length
  },
  labels,
  candidates: candidates.sort((a,b) => b.score - a.score)
};

const history = await readJson(HISTORY_PATH, { snapshots: [] });
const nextHistory = {
  updatedAt: latest.generatedAt,
  snapshots: [
    {
      generatedAt: latest.generatedAt,
      summary: latest.summary,
      labels: latest.labels,
      candidates: latest.candidates.map(c => ({ id: c.id, status: c.status, score: c.score, knownTotal: c.knownTotal, quoteReady: c.quoteReady }))
    },
    ...(history.snapshots || [])
  ].slice(0, MAX_HISTORY)
};

await fs.writeFile(LATEST_PATH, JSON.stringify(latest, null, 2) + '\n');
await fs.writeFile(HISTORY_PATH, JSON.stringify(nextHistory, null, 2) + '\n');
console.log(JSON.stringify({ status: 'ok', generatedAt: latest.generatedAt, summary: latest.summary, labels }));
