import fs from 'node:fs/promises';
import path from 'node:path';

const ROOT = process.cwd();
const POLICY_FILE = path.join(ROOT, 'config', 'wholesale-supplier-monitor.json');

const FIRST_HAND_TERMS = [
  /ocean carrier/i,
  /air carrier/i,
  /nvocc/i,
  /freight forwarder/i,
  /licensed/i,
  /terminal operator/i,
  /customs broker/i,
  /warehouse operator/i,
  /manufacturer/i,
  /master distributor/i,
  /authorized distributor/i,
  /wholesale/i,
  /mayorista/i
];

const RETAIL_TERMS = [
  /retail/i,
  /minorista/i,
  /consumer/i,
  /env[ií]os personales/i,
  /paqueter[ií]a personal/i
];

function hasAny(text, patterns) {
  return patterns.some((p) => p.test(text || ''));
}

function classify(candidate, policy) {
  const text = [
    candidate.name,
    candidate.description,
    candidate.licenses,
    candidate.authority,
    candidate.wholesaleTerms,
    candidate.sourceEvidence
  ].filter(Boolean).join(' ');

  if (policy.supplierPolicy.excludeDirectCompetitorsFromSupplierPool.includes(candidate.name)) {
    return { classification: 'COMPETITOR_ONLY', score: 0, reasons: ['DIRECT_COMPETITOR_EXCLUDED'] };
  }

  if (hasAny(text, RETAIL_TERMS) && !hasAny(text, FIRST_HAND_TERMS)) {
    return { classification: 'RETAIL_ONLY', score: 0, reasons: ['NO_FIRST_HAND_WHOLESALE_EVIDENCE'] };
  }

  const required = policy.supplierPolicy.requiredEvidenceBeforeApproved;
  const evidence = candidate.evidence || {};
  const missing = required.filter((key) => !evidence[key]);
  const firstHand = Boolean(evidence.first_hand_or_master_wholesale_role);
  const wholesaleRate = Boolean(evidence.direct_rate_or_wholesale_rate);
  const authority = Boolean(evidence.operating_authority_or_license_when_applicable);

  let score = 0;
  if (firstHand) score += policy.rankingWeights.firstHandEvidence;
  if (wholesaleRate) score += policy.rankingWeights.wholesaleRateAdvantage;
  if (evidence.route_or_capacity_evidence) score += policy.rankingWeights.routeCoverage;
  if (evidence.cuba_final_mile) score += policy.rankingWeights.cubaFinalMile;
  if (authority && evidence.kyb_and_compliance_review) score += policy.rankingWeights.complianceAndAuthority;
  if (evidence.capacity_and_reliability) score += policy.rankingWeights.capacityAndReliability;
  if (evidence.commercial_terms) score += policy.rankingWeights.paymentAndCommercialTerms;

  if (!firstHand) {
    return { classification: 'UNVERIFIED_MIDDLEMAN', score, reasons: ['FIRST_HAND_ROLE_NOT_VERIFIED', ...missing.map(x => `MISSING_${x.toUpperCase()}`)] };
  }

  if (missing.length === 0) {
    return { classification: 'APPROVED_FIRST_HAND', score, reasons: ['ALL_REQUIRED_EVIDENCE_PRESENT'] };
  }

  return { classification: 'QUALIFYING_FIRST_HAND', score, reasons: missing.map(x => `MISSING_${x.toUpperCase()}`) };
}

const policy = JSON.parse(await fs.readFile(POLICY_FILE, 'utf8'));
const inputPath = process.argv[2];
if (!inputPath) {
  console.error('Usage: node tools/wholesale-supplier-qualifier.mjs <candidates.json>');
  process.exit(2);
}

const raw = JSON.parse(await fs.readFile(path.resolve(inputPath), 'utf8'));
const candidates = Array.isArray(raw) ? raw : (raw.candidates || []);
const ranked = candidates
  .map((candidate) => ({ ...candidate, qualification: classify(candidate, policy) }))
  .sort((a, b) => b.qualification.score - a.qualification.score);

const output = {
  engine: 'SAHJONY First-Hand Wholesale Supplier Qualifier',
  generatedAt: new Date().toISOString(),
  policyVersion: policy.version,
  approved: ranked.filter(x => x.qualification.classification === 'APPROVED_FIRST_HAND'),
  qualifying: ranked.filter(x => x.qualification.classification === 'QUALIFYING_FIRST_HAND'),
  excluded: ranked.filter(x => !['APPROVED_FIRST_HAND','QUALIFYING_FIRST_HAND'].includes(x.qualification.classification)),
  all: ranked
};

process.stdout.write(JSON.stringify(output, null, 2) + '\n');
