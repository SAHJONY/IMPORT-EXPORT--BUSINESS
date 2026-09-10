import fs from 'node:fs/promises';
import path from 'node:path';

const ROOT = process.cwd();
const CONFIG_PATH = path.join(ROOT, 'config', 'cuba-vehicle-business-a-to-z.json');
const INPUT_PATH = process.argv[2] || path.join(ROOT, 'public', 'data', 'vehicles', 'candidates.json');
const OUT_DIR = path.join(ROOT, 'public', 'data', 'vehicles');
const LATEST_PATH = path.join(OUT_DIR, 'latest.json');
const HISTORY_PATH = path.join(OUT_DIR, 'history.json');
const MAX_HISTORY = 500;

async function readJson(file, fallback) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); } catch { return fallback; }
}

const config = JSON.parse(await fs.readFile(CONFIG_PATH, 'utf8'));
const input = await readJson(INPUT_PATH, { vehicles: [] });

function present(v) {
  if (typeof v === 'boolean') return v;
  if (typeof v === 'number') return Number.isFinite(v);
  if (Array.isArray(v)) return v.length > 0;
  return v !== null && v !== undefined && String(v).trim() !== '';
}

function get(obj, key) {
  if (key in obj) return obj[key];
  const aliases = {
    legal_name: ['customer_legal_name'], contact: ['contact_phone','contact_email'], payer_identity: ['payer_name'], Cuba_consignee_identity: ['consignee_id','consignee_name'],
    VIN: ['vin'], year: ['vehicle_year'], make: ['vehicle_make'], model: ['vehicle_model'], original_or_acceptable_title: ['title_verified','title_document'],
    title_state: ['title_state'], owner_name: ['title_owner'], lien_status: ['lien_status'], signed_owner_authorization_if_exporter_not_owner: ['owner_authorization'],
    AES_EEI: ['aes_eei_status'], ITN: ['aes_itn'], verified_bookable_US_origin_port: ['origin_port'], verified_Cuba_destination_port: ['destination_port'],
    carrier_or_FMC_authorized_OTI: ['carrier','oti'], firm_direct_or_wholesale_rate: ['ocean_freight'], eligible_importer_or_recipient: ['cuba_importer_basis'],
    authorized_release_role: ['release_provider'], delivery_address: ['final_delivery_address'], authorized_ground_provider: ['final_mile_provider'], final_mile_rate: ['cuba_final_mile']
  };
  for (const alias of aliases[key] || []) if (alias in obj) return obj[alias];
  return undefined;
}

function gateResult(vehicle, gate) {
  const missing = gate.required.filter(field => !present(get(vehicle, field)));
  return { gate: gate.id, pass: missing.length === 0, missing };
}

function money(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function calcEconomics(v) {
  const fields = ['vehicle_cost_if_sourced','US_pickup','US_port_charges','export_filing','ocean_freight','insurance','Cuba_government_charges','Cuba_terminal_charges','release_provider_cost','storage_contingency','Cuba_final_mile','payment_processing','FX_buffer'];
  const values = fields.map(f => money(v[f]));
  const complete = values.every(x => x !== null);
  const landedCost = complete ? values.reduce((a,b) => a + b, 0) : null;
  const customerPrice = money(v.customer_total ?? v.customer_price);
  const grossProfit = landedCost !== null && customerPrice !== null ? customerPrice - landedCost : null;
  const grossMarginPct = grossProfit !== null && customerPrice > 0 ? grossProfit / customerPrice * 100 : null;
  return { complete, landedCost, customerPrice, grossProfit, grossMarginPct, missingCostInputs: fields.filter((f,i) => values[i] === null) };
}

function decision(vehicle, gates, economics) {
  const failed = gates.filter(g => !g.pass).map(g => g.gate);
  if (failed.includes('CUSTOMER_KYB_KYC')) return 'INPUTS_REQUIRED';
  if (failed.includes('VEHICLE_IDENTITY')) return 'INPUTS_REQUIRED';
  if (failed.includes('TITLE_OWNERSHIP')) return 'BLOCKED_TITLE';
  if (failed.includes('US_EXPORT')) return 'BLOCKED_US_EXPORT';
  if (failed.includes('OCEAN_ROUTE')) return 'BLOCKED_ROUTE';
  if (failed.includes('CUBA_IMPORT')) return 'BLOCKED_CUBA_IMPORT';
  if (failed.includes('CUBA_RELEASE')) return 'BLOCKED_CUSTOMS';
  if (failed.includes('FINAL_MILE')) return 'INPUTS_REQUIRED';
  if (!economics.complete) return 'INPUTS_REQUIRED';
  return 'LANDED_COST_VERIFIED';
}

function quotePermission(status, vehicle, economics) {
  if (status !== 'LANDED_COST_VERIFIED') return { allowed: false, reason: 'ALL_MATERIAL_GATES_AND_LANDED_COST_MUST_BE_VERIFIED' };
  if (config.hardRules.vehicleTransport === 'MARITIME_ONLY' && String(vehicle.mode || '').toUpperCase().includes('AIR')) return { allowed: false, reason: 'VEHICLE_AIR_TRANSPORT_PROHIBITED_BY_SAHJONY_POLICY' };
  if (!economics.complete) return { allowed: false, reason: 'LANDED_COST_INCOMPLETE' };
  return { allowed: true, reason: 'VERIFIED_FOR_FORMAL_QUOTE_PREPARATION_SUBJECT_TO_REQUIRED_APPROVALS' };
}

const evaluated = (input.vehicles || []).map((vehicle, index) => {
  const gates = config.gates.map(g => gateResult(vehicle, g));
  const economics = calcEconomics(vehicle);
  const status = decision(vehicle, gates, economics);
  const quote = quotePermission(status, vehicle, economics);
  return {
    vehicleId: vehicle.vehicle_id || vehicle.lead_id || `vehicle-${index+1}`,
    evaluatedAt: new Date().toISOString(),
    operatingModel: vehicle.operating_model || 'customer_owned_vehicle_shipping',
    transportPolicy: config.hardRules.vehicleTransport,
    status,
    quotePermission: quote,
    gates,
    economics,
    vehicle,
    nextActions: gates.filter(g => !g.pass).flatMap(g => g.missing.map(field => `${g.gate}:${field}`)).slice(0,50)
  };
});

await fs.mkdir(OUT_DIR, { recursive: true });
const latest = {
  engine: config.engine,
  version: config.version,
  generatedAt: new Date().toISOString(),
  hardRules: config.hardRules,
  summary: {
    total: evaluated.length,
    landedCostVerified: evaluated.filter(x => x.status === 'LANDED_COST_VERIFIED').length,
    formalQuoteEligible: evaluated.filter(x => x.quotePermission.allowed).length,
    blocked: evaluated.filter(x => x.status.startsWith('BLOCKED_')).length,
    inputsRequired: evaluated.filter(x => x.status === 'INPUTS_REQUIRED').length
  },
  vehicles: evaluated
};
await fs.writeFile(LATEST_PATH, JSON.stringify(latest, null, 2) + '\n');
const history = await readJson(HISTORY_PATH, { runs: [] });
history.runs = [{ generatedAt: latest.generatedAt, summary: latest.summary, vehicles: evaluated.map(v => ({ vehicleId: v.vehicleId, status: v.status, quotePermission: v.quotePermission })) }, ...(history.runs || [])].slice(0, MAX_HISTORY);
await fs.writeFile(HISTORY_PATH, JSON.stringify(history, null, 2) + '\n');
console.log(JSON.stringify({ status: 'ok', ...latest.summary }));
