import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const ROOT = process.cwd();
const CONFIG = path.join(ROOT, 'config', 'cuba-customs-intelligence-sources.json');
const OUT_DIR = path.join(ROOT, 'public', 'data', 'cuba-customs-intelligence');
const LATEST = path.join(OUT_DIR, 'latest.json');
const RECORDS = path.join(OUT_DIR, 'records.json');
const HISTORY = path.join(OUT_DIR, 'history.json');
const USER_AGENT = 'SAHJONY-Cuba-Customs-Intelligence/1.0 (+https://www.sahjony.com)';
const MAX_HISTORY = 1000;

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

function sha256(v) { return crypto.createHash('sha256').update(v).digest('hex'); }
function uniq(v) { return [...new Set(v.filter(Boolean))]; }
async function readJson(file, fallback) { try { return JSON.parse(await fs.readFile(file, 'utf8')); } catch { return fallback; } }

function extract(text) {
  const lower = text.toLowerCase();
  const legalRefs = uniq([
    ...text.matchAll(/\b(?:Decreto[- ]?Ley|Decreto|Resoluci[oó]n|Ley)\s+\d+(?:\/\d{4}|\s+de\s+\d{4})?/gi)
  ].map(m => m[0].trim())).slice(0, 100);

  const money = uniq([
    ...text.matchAll(/(?:USD|CUP|EUR)?\s*\$?\s*\d+(?:[.,]\d{1,2})?\s*(?:USD|CUP|EUR|%|por ciento)?/gi)
  ].map(m => m[0].replace(/\s+/g, ' ').trim())).slice(0, 100);

  const dates = uniq([
    ...text.matchAll(/\b(?:\d{1,2}[\/.-]\d{1,2}[\/.-]\d{2,4}|\d{1,2}\s+de\s+[A-Za-zÁÉÍÓÚáéíóúñÑ]+\s+de\s+\d{4}|\d{4}-\d{2}-\d{2})\b/g)
  ].map(m => m[0].trim())).slice(0, 60);

  const documents = uniq([
    ...text.matchAll(/\b(?:factura|invoice|conocimiento de embarque|bill of lading|BL|B\/L|air waybill|AWB|manifiesto|declaraci[oó]n de mercanc[ií]as|certificado|permiso|licencia|poder|autorizaci[oó]n)\b/gi)
  ].map(m => m[0].trim())).slice(0, 60);

  const entryPoints = uniq([
    ...text.matchAll(/\b(?:Mariel|La Habana|Habana|Havana|Santiago de Cuba|Cienfuegos|Nuevitas|Jos[eé] Mart[ií]|Frank Pa[ií]s|Abel Santamar[ií]a|Antonio Maceo|Varadero)\b/gi)
  ].map(m => m[0].trim())).slice(0, 60);

  const topics = {
    customsClearance: /desaduanamiento|despacho aduan|customs clearance/.test(lower),
    temporaryDeposit: /dep[oó]sito temporal/.test(lower),
    customsRegime: /r[eé]gimen(?:es)? aduaner/.test(lower),
    abandonment: /abandono de mercanc/.test(lower),
    authorizedEconomicOperator: /operador econ[oó]mico autorizado/.test(lower),
    customsAgent: /agencia de aduana|agente de aduana|apoderado/.test(lower),
    freightForwarder: /agencia transitaria|transitaria de carga|freight forward/.test(lower),
    inspection: /inspecci[oó]n|reconocimiento de mercanc/.test(lower),
    sanctions: /sanci[oó]n|infracci[oó]n|decomiso|retenci[oó]n/.test(lower),
    valuation: /valoraci[oó]n|valor en aduana|valor de referencia/.test(lower),
    duties: /arancel|impuesto aduanero|derechos de aduana/.test(lower),
    fees: /tarifa|servicios t[eé]cnico-productivos|fee|charge/.test(lower),
    vehicles: /veh[ií]culo|auto|motocicleta|triciclo|remolque/.test(lower),
    parcels: /env[ií]o|paqueter[ií]a|postal|mensajer[ií]a/.test(lower),
    commercial: /car[aá]cter comercial|comercio exterior|importaci[oó]n comercial/.test(lower),
    noncommercial: /sin car[aá]cter comercial|no comercial/.test(lower),
    prohibitedRestricted: /prohibid|restricci[oó]n|sujeto a permiso|regulaciones de otras autoridades/.test(lower)
  };

  return { legalRefs, money, dates, documents, entryPoints, topics };
}

async function fetchSource(source) {
  const capturedAt = new Date().toISOString();
  try {
    const response = await fetch(source.url, { headers: { 'user-agent': USER_AGENT, accept: 'text/html,application/xhtml+xml' }, redirect: 'follow', signal: AbortSignal.timeout(25000) });
    const html = await response.text();
    const text = normalizeText(html).slice(0, 500000);
    return {
      sourceId: source.id,
      name: source.name,
      type: source.type,
      authority: source.authority,
      sourceUrl: source.url,
      capturedAt,
      ok: response.ok,
      httpStatus: response.status,
      contentHash: sha256(text),
      configuredRecords: source.records || [],
      signals: extract(text),
      textSample: text.slice(0, 5000),
      error: null
    };
  } catch (error) {
    return { sourceId: source.id, name: source.name, type: source.type, authority: source.authority, sourceUrl: source.url, capturedAt, ok: false, httpStatus: null, contentHash: null, configuredRecords: source.records || [], signals: {}, textSample: '', error: String(error?.message || error) };
  }
}

function buildRecords(source) {
  const titles = source.configuredRecords?.length ? source.configuredRecords : (source.signals?.legalRefs || []);
  return titles.map((title, i) => ({
    recordId: `${source.sourceId}:${sha256(title).slice(0,16)}`,
    sourceId: source.sourceId,
    sourceUrl: source.sourceUrl,
    capturedAt: source.capturedAt,
    recordType: source.type,
    title,
    status: 'UNVERIFIED_CURRENT_STATUS',
    effectiveDate: null,
    subjects: Object.entries(source.signals?.topics || {}).filter(([,v]) => v).map(([k]) => k),
    entryPoints: source.signals?.entryPoints || [],
    cargoTypes: [],
    fees: source.signals?.money || [],
    documents: source.signals?.documents || [],
    restrictions: (source.signals?.topics?.prohibitedRestricted ? ['RESTRICTIONS_OR_PROHIBITIONS_MENTIONED_REVIEW_SOURCE'] : []),
    authorizationRules: (source.signals?.topics?.customsAgent || source.signals?.topics?.freightForwarder ? ['CUSTOMS_OR_FORWARDING_AUTHORIZATION_RULES_MENTIONED_REVIEW_SOURCE'] : []),
    supersedes: [],
    repeals: [],
    confidence: source.authority === 'PRIMARY' ? 'HIGH' : source.authority?.includes('PRIMARY') ? 'HIGH' : 'MEDIUM'
  }));
}

await fs.mkdir(OUT_DIR, { recursive: true });
const config = JSON.parse(await fs.readFile(CONFIG, 'utf8'));
const previous = await readJson(LATEST, { sources: [] });
const prevMap = new Map((previous.sources || []).map(s => [s.sourceId, s]));
const sources = [];
const events = [];
let records = [];

for (const cfg of config.sources || []) {
  const current = await fetchSource(cfg);
  sources.push(current);
  records.push(...buildRecords(current));
  const prev = prevMap.get(current.sourceId);
  const reasons = [];
  if (!prev) reasons.push('FIRST_SNAPSHOT');
  else {
    if (prev.contentHash !== current.contentHash) reasons.push('SOURCE_CONTENT_CHANGE');
    if (JSON.stringify(prev.signals?.legalRefs || []) !== JSON.stringify(current.signals?.legalRefs || [])) reasons.push('LEGAL_REFERENCE_CHANGE');
    if (JSON.stringify(prev.signals?.money || []) !== JSON.stringify(current.signals?.money || [])) reasons.push('FEE_OR_AMOUNT_CHANGE');
    if (JSON.stringify(prev.signals?.topics || {}) !== JSON.stringify(current.signals?.topics || {})) reasons.push('CUSTOMS_TOPIC_CHANGE');
  }
  if (reasons.length) events.push({ eventId: `${current.sourceId}:${current.capturedAt}`, sourceId: current.sourceId, sourceName: current.name, detectedAt: current.capturedAt, reasons, material: reasons.some(r => r !== 'SOURCE_CONTENT_CHANGE'), sourceUrl: current.sourceUrl });
}

const latest = {
  engine: config.engine,
  version: config.version,
  status: 'ACTIVE',
  scannedAt: new Date().toISOString(),
  scope: config.scope,
  rules: config.rules,
  summary: {
    monitoredSources: sources.length,
    successfulSources: sources.filter(s => s.ok).length,
    failedSources: sources.filter(s => !s.ok).length,
    extractedRecords: records.length,
    materialEvents: events.filter(e => e.material).length
  },
  sources,
  materialEvents: events.filter(e => e.material)
};

const history = await readJson(HISTORY, { events: [] });
await fs.writeFile(LATEST, JSON.stringify(latest, null, 2) + '\n');
await fs.writeFile(RECORDS, JSON.stringify({ updatedAt: latest.scannedAt, records }, null, 2) + '\n');
await fs.writeFile(HISTORY, JSON.stringify({ updatedAt: latest.scannedAt, events: [...events, ...(history.events || [])].slice(0, MAX_HISTORY) }, null, 2) + '\n');

console.log(JSON.stringify({ status: 'ok', scannedAt: latest.scannedAt, monitoredSources: latest.summary.monitoredSources, extractedRecords: latest.summary.extractedRecords, materialEvents: latest.summary.materialEvents }));
