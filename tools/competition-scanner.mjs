import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const ROOT = process.cwd();
const CONFIG = path.join(ROOT, 'config', 'competition-monitor.json');
const OUT_DIR = path.join(ROOT, 'public', 'data', 'competition');
const LATEST = path.join(OUT_DIR, 'latest.json');
const HISTORY = path.join(OUT_DIR, 'history.json');
const PRICE_ROUTE_INDEX = path.join(OUT_DIR, 'price-route-index.json');

const USER_AGENT = 'SAHJONY-Competition-Scanner/1.1 (+https://www.sahjony.com)';
const MAX_HISTORY = 500;
const CITIES_PORTS = [
  'Miami','Houston','Tampa','Jacksonville','Fort Lauderdale','Port Everglades','New Orleans',
  'Havana','La Habana','Mariel','Santiago de Cuba','Matanzas','Cienfuegos','Holguin','Holguín',
  'Camaguey','Camagüey','Santa Clara','Villa Clara','Pinar del Rio','Pinar del Río','Playa'
];

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

function around(text, index, radius = 120) {
  return text.slice(Math.max(0, index - radius), Math.min(text.length, index + radius)).replace(/\s+/g, ' ').trim();
}

function extractPrices(text) {
  const rows = [];
  const rx = /(?:USD\s*)?\$\s?\d{1,6}(?:[.,]\d{1,2})?(?:\s*(?:\/|x|por|per)\s*(?:lb|lbs|libra|libras|pound|kg|kilogramo|caja|box|veh[ií]culo|vehicle|auto|carro|contenedor|container))?/gi;
  for (const m of text.matchAll(rx)) {
    const raw = m[0].replace(/\s+/g, ' ').trim();
    const valueMatch = raw.match(/\d{1,6}(?:[.,]\d{1,2})?/);
    const value = valueMatch ? Number(valueMatch[0].replace(',', '.')) : null;
    const unitMatch = raw.match(/(?:\/|x|por|per)\s*(.+)$/i);
    rows.push({ raw, value, currency: 'USD', unit: unitMatch ? unitMatch[1].trim() : null, context: around(text, m.index || 0) });
  }
  return rows.slice(0, 50);
}

function extractRoutes(text) {
  const routes = [];
  const cityPattern = CITIES_PORTS.map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|');
  const explicit = new RegExp(`\\b(${cityPattern})\\b\\s*(?:→|->|to|a|hasta|hacia|con destino a|destino)\\s*\\b(${cityPattern})\\b`, 'gi');
  for (const m of text.matchAll(explicit)) {
    routes.push({ origin: m[1], destination: m[2], raw: m[0], context: around(text, m.index || 0) });
  }

  const originDestination = /(?:desde|from|origen|origin)\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ .'-]{2,40}?)\s+(?:a|to|hasta|hacia|con destino a|destino)\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ .'-]{2,40}?)(?=[,.;]|\s(?:por|via|vía|en|con|desde|precio|tarifa|delivery|entrega|mar[ií]tim|a[eé]reo)\b|$)/gi;
  for (const m of text.matchAll(originDestination)) {
    routes.push({ origin: m[1].trim(), destination: m[2].trim(), raw: m[0], context: around(text, m.index || 0) });
  }

  return uniq(routes.map(r => JSON.stringify(r))).map(x => JSON.parse(x)).slice(0, 40);
}

function extractTransit(text) {
  return uniq([
    ...text.matchAll(/\b\d+\s*(?:a|to|-)\s*\d+\s*(?:d[ií]as|days|horas|hours)\b/gi),
    ...text.matchAll(/\b\d+\s*(?:d[ií]as|days|horas|hours)\s*(?:h[aá]biles|business)?\b/gi)
  ].map(m => m[0].trim())).slice(0, 30);
}

function extractSignals(text) {
  const lower = text.toLowerCase();
  const priceDetails = extractPrices(text);
  const routes = extractRoutes(text);
  const transit = extractTransit(text);
  const keywords = {
    vehicle: /auto|autos|veh[ií]culo|vehicle|carro|camion|truck/.test(lower),
    maritime: /mar[ií]tim|ocean|barco|ship|ro-ro|roro|contenedor|container/.test(lower),
    air: /a[eé]reo|air cargo|air freight/.test(lower),
    cubaDelivery: /entrega (?:final )?en cuba|puerta a puerta|door[- ]to[- ]door|delivery.*cuba/.test(lower),
    pickup: /recogida|pickup|pick up/.test(lower),
    tracking: /tracking|rastreo|rastre/.test(lower),
    documents: /document|t[ií]tulo|title|bill of sale|power of attorney|poder notarial/.test(lower),
    promotion: /oferta|promoci[oó]n|special|discount|descuento/.test(lower),
    wholesale: /wholesale|mayorista|agency|agencia|partner/.test(lower)
  };

  return {
    prices: priceDetails.map(x => x.raw),
    priceDetails,
    routes,
    transit,
    keywords
  };
}

function materialDelta(previous, current) {
  if (!previous) return { material: true, reasons: ['FIRST_SNAPSHOT'] };
  const reasons = [];
  if (JSON.stringify(previous.signals?.priceDetails || []) !== JSON.stringify(current.signals?.priceDetails || [])) reasons.push('PRICE_CHANGE');
  if (JSON.stringify(previous.signals?.routes || []) !== JSON.stringify(current.signals?.routes || [])) reasons.push('ROUTE_CHANGE');
  if (JSON.stringify(previous.signals?.transit || []) !== JSON.stringify(current.signals?.transit || [])) reasons.push('TRANSIT_CHANGE');

  const watched = ['vehicle','maritime','air','cubaDelivery','pickup','tracking','documents','promotion','wholesale'];
  for (const key of watched) {
    if ((previous.signals?.keywords?.[key] ?? false) !== (current.signals?.keywords?.[key] ?? false)) reasons.push(`CAPABILITY_${key.toUpperCase()}_CHANGE`);
  }
  if (previous.contentHash !== current.contentHash && reasons.length === 0) reasons.push('CONTENT_CHANGE_NON_MATERIAL');
  return { material: reasons.some(r => r !== 'CONTENT_CHANGE_NON_MATERIAL'), reasons };
}

async function readJson(file, fallback) {
  try { return JSON.parse(await fs.readFile(file, 'utf8')); } catch { return fallback; }
}

async function fetchCompetitor(c) {
  const started = new Date().toISOString();
  try {
    const response = await fetch(c.url, {
      headers: { 'user-agent': USER_AGENT, accept: 'text/html,application/xhtml+xml' },
      redirect: 'follow',
      signal: AbortSignal.timeout(20000)
    });
    const html = await response.text();
    const text = normalizeText(html).slice(0, 250000);
    return {
      id: c.id,
      name: c.name,
      tier: c.tier,
      url: c.url,
      fetchedAt: started,
      httpStatus: response.status,
      ok: response.ok,
      contentHash: sha256(text),
      signals: extractSignals(text),
      textSample: text.slice(0, 3000),
      error: null
    };
  } catch (error) {
    return {
      id: c.id,
      name: c.name,
      tier: c.tier,
      url: c.url,
      fetchedAt: started,
      httpStatus: null,
      ok: false,
      contentHash: null,
      signals: { prices: [], priceDetails: [], routes: [], transit: [], keywords: {} },
      textSample: '',
      error: String(error?.message || error)
    };
  }
}

await fs.mkdir(OUT_DIR, { recursive: true });
const config = JSON.parse(await fs.readFile(CONFIG, 'utf8'));
const previous = await readJson(LATEST, { competitors: [] });
const previousMap = new Map((previous.competitors || []).map(x => [x.id, x]));

const competitors = [];
const events = [];
for (const c of config.competitors) {
  const current = await fetchCompetitor(c);
  const delta = materialDelta(previousMap.get(c.id), current);
  current.delta = delta;
  competitors.push(current);
  if (delta.reasons.length) {
    events.push({
      eventId: `${c.id}:${current.fetchedAt}`,
      competitorId: c.id,
      competitorName: c.name,
      tier: c.tier,
      detectedAt: current.fetchedAt,
      material: delta.material,
      reasons: delta.reasons,
      prices: current.signals.priceDetails,
      routes: current.signals.routes,
      transit: current.signals.transit,
      capabilities: current.signals.keywords,
      url: c.url
    });
  }
}

const materialEvents = events.filter(e => e.material);
const latest = {
  engine: 'SAHJONY Competition Intelligence Scanner',
  version: '1.1',
  status: 'ACTIVE',
  scannedAt: new Date().toISOString(),
  market: config.defaultMarket,
  rules: config.rules,
  summary: {
    monitored: competitors.length,
    successful: competitors.filter(x => x.ok).length,
    failed: competitors.filter(x => !x.ok).length,
    changesDetected: events.length,
    materialChanges: materialEvents.length,
    pricesFound: competitors.reduce((n, x) => n + (x.signals?.priceDetails?.length || 0), 0),
    routesFound: competitors.reduce((n, x) => n + (x.signals?.routes?.length || 0), 0)
  },
  competitors,
  materialEvents
};

const priceRouteIndex = {
  generatedAt: latest.scannedAt,
  market: config.defaultMarket,
  evidenceRule: 'PUBLIC_SOURCE_ONLY_DO_NOT_INVENT',
  prices: competitors.flatMap(c => (c.signals?.priceDetails || []).map(p => ({ competitorId: c.id, competitorName: c.name, tier: c.tier, sourceUrl: c.url, ...p }))),
  routes: competitors.flatMap(c => (c.signals?.routes || []).map(r => ({ competitorId: c.id, competitorName: c.name, tier: c.tier, sourceUrl: c.url, ...r }))),
  transit: competitors.flatMap(c => (c.signals?.transit || []).map(t => ({ competitorId: c.id, competitorName: c.name, tier: c.tier, sourceUrl: c.url, value: t })))
};

const history = await readJson(HISTORY, { events: [] });
const nextHistory = { updatedAt: latest.scannedAt, events: [...events, ...(history.events || [])].slice(0, MAX_HISTORY) };

await fs.writeFile(LATEST, JSON.stringify(latest, null, 2) + '\n');
await fs.writeFile(HISTORY, JSON.stringify(nextHistory, null, 2) + '\n');
await fs.writeFile(PRICE_ROUTE_INDEX, JSON.stringify(priceRouteIndex, null, 2) + '\n');

console.log(JSON.stringify({
  status: 'ok',
  scannedAt: latest.scannedAt,
  monitored: latest.summary.monitored,
  successful: latest.summary.successful,
  materialChanges: latest.summary.materialChanges,
  pricesFound: latest.summary.pricesFound,
  routesFound: latest.summary.routesFound
}));
