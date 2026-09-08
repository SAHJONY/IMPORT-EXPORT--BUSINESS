import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const ROOT = process.cwd();
const CONFIG = path.join(ROOT, 'config', 'competition-monitor.json');
const OUT_DIR = path.join(ROOT, 'public', 'data', 'competition');
const LATEST = path.join(OUT_DIR, 'latest.json');
const HISTORY = path.join(OUT_DIR, 'history.json');

const USER_AGENT = 'SAHJONY-Competition-Scanner/1.0 (+https://www.sahjony.com)';
const MAX_HISTORY = 500;

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
    ...text.matchAll(/\$\s?\d+(?:\.\d{1,2})?(?:\s*(?:\/|x|por)\s*(?:lb|libra|lbs|pound))?/gi)
  ].map(m => m[0].replace(/\s+/g, ' ').trim())).slice(0, 30);

  const transit = uniq([
    ...text.matchAll(/\b\d+\s*(?:a|to|-)\s*\d+\s*(?:d[ií]as|days|horas|hours)\b/gi),
    ...text.matchAll(/\b\d+\s*(?:d[ií]as|days|horas|hours)\s*(?:h[aá]biles|business)?\b/gi)
  ].map(m => m[0].trim())).slice(0, 20);

  const keywords = {
    vehicle: /auto|autos|veh[ií]culo|vehicle|carro|camion|truck/.test(lower),
    maritime: /mar[ií]tim|ocean|barco|ship/.test(lower),
    air: /a[eé]reo|air cargo|air freight/.test(lower),
    cubaDelivery: /entrega (?:final )?en cuba|puerta a puerta|door[- ]to[- ]door|delivery.*cuba/.test(lower),
    pickup: /recogida|pickup|pick up/.test(lower),
    tracking: /tracking|rastreo|rastre/.test(lower),
    documents: /document|t[ií]tulo|title|bill of sale|power of attorney|poder notarial/.test(lower),
    promotion: /oferta|promoci[oó]n|special|discount|descuento/.test(lower),
    wholesale: /wholesale|mayorista|agency|agencia|partner/.test(lower)
  };

  return { prices, transit, keywords };
}

function materialDelta(previous, current) {
  if (!previous) return { material: true, reasons: ['FIRST_SNAPSHOT'] };
  const reasons = [];
  const prevPrices = JSON.stringify(previous.signals?.prices || []);
  const curPrices = JSON.stringify(current.signals?.prices || []);
  if (prevPrices !== curPrices) reasons.push('PRICE_OR_PROMOTION_CHANGE');

  const prevTransit = JSON.stringify(previous.signals?.transit || []);
  const curTransit = JSON.stringify(current.signals?.transit || []);
  if (prevTransit !== curTransit) reasons.push('TRANSIT_CHANGE');

  const watched = ['vehicle','maritime','air','cubaDelivery','pickup','tracking','documents','promotion','wholesale'];
  for (const key of watched) {
    if ((previous.signals?.keywords?.[key] ?? false) !== (current.signals?.keywords?.[key] ?? false)) {
      reasons.push(`CAPABILITY_${key.toUpperCase()}_CHANGE`);
    }
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
      textSample: text.slice(0, 2500),
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
      signals: { prices: [], transit: [], keywords: {} },
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
      prices: current.signals.prices,
      transit: current.signals.transit,
      capabilities: current.signals.keywords,
      url: c.url
    });
  }
}

const materialEvents = events.filter(e => e.material);
const latest = {
  engine: 'SAHJONY Competition Intelligence Scanner',
  version: config.version,
  status: 'ACTIVE',
  scannedAt: new Date().toISOString(),
  market: config.defaultMarket,
  rules: config.rules,
  summary: {
    monitored: competitors.length,
    successful: competitors.filter(x => x.ok).length,
    failed: competitors.filter(x => !x.ok).length,
    changesDetected: events.length,
    materialChanges: materialEvents.length
  },
  competitors,
  materialEvents
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
  monitored: latest.summary.monitored,
  successful: latest.summary.successful,
  materialChanges: latest.summary.materialChanges
}));
