import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const ROOT = process.cwd();
const CONFIG = path.join(ROOT, 'config', 'cuba-customs-release-scanner.json');
const OUT_DIR = path.join(ROOT, 'public', 'data', 'cuba-customs-release');
const LATEST = path.join(OUT_DIR, 'latest.json');
const HISTORY = path.join(OUT_DIR, 'history.json');
const MAX_HISTORY = 500;
const USER_AGENT = 'SAHJONY-Cuba-Customs-Scanner/1.0 (+https://www.sahjony.com)';

function normalizeText(html) {
  return String(html || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&#39;/g, "'")
    .replace(/&quot;/gi, '"')
    .replace(/\s+/g, ' ')
    .trim();
}

function sha256(value) {
  return crypto.createHash('sha256').update(value).digest('hex');
}

function uniq(values) {
  return [...new Set(values.filter(Boolean))];
}

function extractSignals(text) {
  const lower = text.toLowerCase();
  const prices = uniq([
    ...text.matchAll(/(?:usd\s*)?\$\s?\d+(?:[.,]\d{1,2})?(?:\s*(?:\/|por|per)\s*(?:kg|lb|libra|container|contenedor|vehicle|vehiculo|auto|shipment|envio))?/gi),
    ...text.matchAll(/\b\d+(?:[.,]\d{1,2})?\s*(?:usd|cup|eur)\b/gi)
  ].map(m => m[0].replace(/\s+/g, ' ').trim())).slice(0, 40);

  const transit = uniq([
    ...text.matchAll(/\b\d+\s*(?:a|to|-)\s*\d+\s*(?:d[ií]as|days|horas|hours)\b/gi),
    ...text.matchAll(/\b\d+\s*(?:d[ií]as|days|horas|hours)\s*(?:h[aá]biles|business)?\b/gi)
  ].map(m => m[0].trim())).slice(0, 20);

  const capabilities = {
    customs: /aduana|customs/.test(lower),
    customsClearance: /despacho aduan|customs clearance|clearance service/.test(lower),
    cargoRelease: /liberaci[oó]n|release|levante|retiro de carga/.test(lower),
    port: /puerto|port|mariel|havana|habana|santiago de cuba|cienfuegos|nuevitas/.test(lower),
    airport: /aeropuerto|airport|jos[eé] mart[ií]|frank pa[ií]s|abel santamar[ií]a|antonio maceo/.test(lower),
    warehouse: /almac[eé]n|warehouse|dep[oó]sito/.test(lower),
    terminalHandling: /terminal|handling|manipulaci[oó]n/.test(lower),
    documents: /document|manifiesto|bill of lading|conocimiento de embarque|air waybill|awb|factura|invoice/.test(lower),
    inspection: /inspecci[oó]n|inspection/.test(lower),
    fees: /tarifa|fee|charge|cargo|arancel|derecho/.test(lower),
    finalMile: /puerta a puerta|door[- ]to[- ]door|entrega final|delivery/.test(lower),
    vehicle: /veh[ií]culo|vehicle|auto|carro/.test(lower),
    container: /contenedor|container|fcl|lcl/.test(lower),
    airCargo: /carga a[eé]rea|air cargo|air freight/.test(lower)
  };

  const locations = uniq([
    ...text.matchAll(/\b(?:Mariel|La Habana|Habana|Havana|Santiago de Cuba|Cienfuegos|Nuevitas|Jos[eé] Mart[ií]|Frank Pa[ií]s|Abel Santamar[ií]a|Antonio Maceo|Varadero)\b/gi)
  ].map(m => m[0].trim())).slice(0, 30);

  return { prices, transit, capabilities, locations };
}

async function readJson(file, fallback) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); } catch { return fallback; }
}

async function fetchPage(entry) {
  const fetchedAt = new Date().toISOString();
  try {
    const response = await fetch(entry.url, {
      headers: { 'user-agent': USER_AGENT, accept: 'text/html,application/xhtml+xml' },
      redirect: 'follow',
      signal: AbortSignal.timeout(20000)
    });
    const html = await response.text();
    const text = normalizeText(html).slice(0, 250000);
    return {
      id: entry.id,
      name: entry.name,
      type: entry.type,
      configuredStatus: entry.status || null,
      url: entry.url,
      fetchedAt,
      httpStatus: response.status,
      ok: response.ok,
      contentHash: sha256(text),
      signals: extractSignals(text),
      textSample: text.slice(0, 3000),
      evidenceNote: entry.evidenceNote || null,
      error: null
    };
  } catch (error) {
    return {
      id: entry.id,
      name: entry.name,
      type: entry.type,
      configuredStatus: entry.status || null,
      url: entry.url,
      fetchedAt,
      httpStatus: null,
      ok: false,
      contentHash: null,
      signals: { prices: [], transit: [], capabilities: {}, locations: [] },
      textSample: '',
      evidenceNote: entry.evidenceNote || null,
      error: String(error?.message || error)
    };
  }
}

function classify(entry) {
  if (entry.type === 'REGULATORY_SOURCE_ONLY') return 'REGULATORY_SOURCE_ONLY';
  const c = entry.signals?.capabilities || {};
  const hasReleaseFunction = c.customsClearance || c.cargoRelease || c.terminalHandling;
  const hasEntryPoint = c.port || c.airport;
  if (entry.ok && hasReleaseFunction && hasEntryPoint) return 'QUALIFYING_AUTHORIZED_FIRST_HAND';
  return entry.configuredStatus || 'UNVERIFIED_MIDDLEMAN';
}

function delta(previous, current) {
  if (!previous) return { material: true, reasons: ['FIRST_SNAPSHOT'] };
  const reasons = [];
  if (JSON.stringify(previous.signals?.prices || []) !== JSON.stringify(current.signals?.prices || [])) reasons.push('PRICE_OR_FEE_CHANGE');
  if (JSON.stringify(previous.signals?.locations || []) !== JSON.stringify(current.signals?.locations || [])) reasons.push('ENTRY_POINT_COVERAGE_CHANGE');
  if (JSON.stringify(previous.signals?.capabilities || {}) !== JSON.stringify(current.signals?.capabilities || {})) reasons.push('SERVICE_CAPABILITY_CHANGE');
  if (previous.contentHash !== current.contentHash && reasons.length === 0) reasons.push('CONTENT_CHANGE_NON_MATERIAL');
  return { material: reasons.some(r => r !== 'CONTENT_CHANGE_NON_MATERIAL'), reasons };
}

await fs.mkdir(OUT_DIR, { recursive: true });
const config = JSON.parse(await fs.readFile(CONFIG, 'utf8'));
const previous = await readJson(LATEST, { sources: [] });
const previousMap = new Map((previous.sources || []).map(x => [x.id, x]));
const seeds = [...(config.regulatorySources || []), ...(config.providerSeeds || [])];

const sources = [];
const events = [];
for (const seed of seeds) {
  const current = await fetchPage(seed);
  current.classification = classify(current);
  current.delta = delta(previousMap.get(seed.id), current);
  sources.push(current);
  if (current.delta.reasons.length) {
    events.push({
      eventId: `${seed.id}:${current.fetchedAt}`,
      sourceId: seed.id,
      sourceName: seed.name,
      detectedAt: current.fetchedAt,
      material: current.delta.material,
      reasons: current.delta.reasons,
      classification: current.classification,
      prices: current.signals.prices,
      entryPoints: current.signals.locations,
      capabilities: current.signals.capabilities,
      url: seed.url
    });
  }
}

const qualifyingProviders = sources.filter(x => x.classification === 'QUALIFYING_AUTHORIZED_FIRST_HAND' || x.classification === 'APPROVED_AUTHORIZED_FIRST_HAND');
const latest = {
  engine: config.engine,
  version: config.version,
  status: 'ACTIVE',
  scannedAt: new Date().toISOString(),
  market: config.market,
  scope: config.scope,
  supplierPolicy: config.supplierPolicy,
  rules: config.rules,
  summary: {
    monitoredSources: sources.length,
    successful: sources.filter(x => x.ok).length,
    failed: sources.filter(x => !x.ok).length,
    qualifyingProviders: qualifyingProviders.length,
    materialChanges: events.filter(x => x.material).length
  },
  sources,
  qualifyingProviders,
  materialEvents: events.filter(x => x.material)
};

const history = await readJson(HISTORY, { events: [] });
const nextHistory = {
  updatedAt: latest.scannedAt,
  events: [...events, ...(history.events || [])].slice(0, MAX_HISTORY)
};

await fs.writeFile(LATEST, JSON.stringify(latest, null, 2) + '\n');
await fs.writeFile(HISTORY, JSON.stringify(nextHistory, null, 2) + '\n');

console.log(JSON.stringify({
  status: 'ok',
  scannedAt: latest.scannedAt,
  monitoredSources: latest.summary.monitoredSources,
  successful: latest.summary.successful,
  qualifyingProviders: latest.summary.qualifyingProviders,
  materialChanges: latest.summary.materialChanges
}));
