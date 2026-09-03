import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const GUARD_VERSION = "3.0.1";
const RECENT_DUPLICATE_MS = 30_000;
const MEMORY_TTL_MS = 10 * 60_000;

const INTERNAL_OUTPUT = /(?:↪️\s*Model Fallback|Model Fallback cleared|Missing API key|openai-codex\/|gateway number|messaging itself|OPENAI_API_KEY|NVIDIA_API_KEY|provider-transport-fetch|\brawError=|\bstack trace\b|non_deliverable_terminal_turn|Something went wrong while processing your request|Please try again,? or use \/new to start a fresh session|use \/new to start a fresh session|Agent couldn['’]t generate a response|The agent run failed before producing a reply|Ese mensaje de error es generado por el propio sistema de OpenClaw|no se puede desactivar desde aquí)/i;

const INTERNAL_COMMERCIAL_OUTPUT = /(?:\bQAEV\b|\bexpected\s+GP\b|\bprojected\s+GP\b|\bgross\s+profit\b|\beconomic\s+value\b|\bclose\s+probability\b|\binternal\s+margin\b|\bsupplier\s+cost\b|\bKYB\b|\bde[- ]?risk(?:ing)?\b|risk[- ]mitigation\s+workflow|mitigaci[oó]n\s+de\s+riesgos|protecci[oó]n\s+de\s+comisi[oó]n|commission\s+protection|fee\s+protection|non[- ]?circumvention|\bNCNDA\b|controlled\s+buyer\s+review|revisi[oó]n\s+controlada\s+del\s+comprador|commercial\s+exposure|exposici[oó]n\s+comercial|internal\s+risk\s+score|verification\s+protocols?|protocolos?\s+de\s+verificaci[oó]n|source[- ]owner\s+routing|owner\s+approval\s+logic)/i;

const OWNER_CONTEXT = `
SOFIA WHATSAPP CONTEXT: OWNER_COMMAND.
You are speaking directly with the SAHJONY Owner. Internal commercial metrics and risk analysis may be shown to the Owner, but do not turn routine source collection into an Owner task.
SOURCE OWNERSHIP IS MANDATORY:
- Buyer-owned facts (exact quantity, specifications/application, destination, timing, payment preference/acceptance, buyer corporate documents) must be obtained from the buyer conversation/CRM or requested from the buyer through an authorized workflow. Never ask the Owner to relay these when another source owns them.
- Supplier-owned facts (stock, photos/video, XRF/COA/quality evidence, loading capability, origin, Incoterms, export documents) must be obtained from the supplier/supplier record. Never ask the Owner to supply them.
- Public-verification facts (corporate existence, registry status, sanctions/watchlist and independent KYB evidence) must be researched from authoritative sources.
- Internal facts (QAEV, margin floor, prioritization, internal payment-risk structure, SAHJONY economic/commission protection, internal risk scoring) must be calculated or retrieved internally.
Ask the Owner only for a genuine Owner decision, exception, approval, confidential Owner-only context, capital/credit commitment, binding contract decision, unusual concession, compliance exception, or material pricing/margin exception.
If Owner input is not required, say OWNER DECISION REQUIRED: NO, identify the real source owner and next executable action, and continue to the next actionable QAEV opportunity if the top opportunity is waiting on an external party.
Never claim outreach, verification, negotiation, sending, requesting, confirming, completion, or work-in-progress unless execution evidence exists.
Owner report style: RESULT / MONEY IMPACT / BLOCKER / NEXT ACTION / OWNER DECISION REQUIRED: YES or NO.
Primary outcome: legitimate collected gross profit, not chat volume or QAEV itself.
`.trim();

const CUSTOMER_CONTEXT = `
SOFIA WHATSAPP CONTEXT: CUSTOMER_PARTNER.
You are speaking with an external customer, buyer, supplier, partner, or prospect. Produce a customer-safe commercial message, never an internal deal memo.
Never expose QAEV, expected/projected GP, gross profit, economic value, close probability, internal margin, supplier cost, KYB jargon, de-risking/risk-mitigation workflow, commission/fee protection, NCNDA/non-circumvention mechanics, controlled buyer review, commercial exposure, internal risk score, source-owner routing, verification protocols, or Owner approval logic.
Keep internal controls active internally. Translate only what the external party needs to know into normal commercial language such as validación comercial, verificación de contraparte, documentación del producto, condiciones comerciales, estructura bancaria aceptable, and preparación de la oferta.
Ask only genuinely missing facts owned by this external party and reuse facts already present in the conversation/CRM context. Never ask a buyer for supplier-owned evidence such as supplier stock photos, XRF/COA, loading proof, or supplier documentation.
A response should normally contain: concise confirmation of the known requirement when useful; only the minimum missing external-party facts; the next visible commercial stage; and one clear action.
Never claim outreach, verification, negotiation, sending, requesting, confirming, completion, or work-in-progress unless execution evidence exists.
`.trim();

function normalizeText(value) {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    return value.map((part) => {
      if (typeof part === "string") return part;
      if (part && typeof part === "object") return String(part.text || part.content || part.message || "");
      return "";
    }).join("\n").trim();
  }
  if (value && typeof value === "object") {
    try { return JSON.stringify(value); } catch { return ""; }
  }
  return "";
}

function normalizePeer(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) return "";
  const beforeAt = raw.split("@")[0];
  const digits = beforeAt.replace(/\D/g, "");
  return digits || beforeAt.replace(/[^a-z0-9]/g, "");
}

function channelEvidence(event = {}, ctx = {}) {
  return [
    ctx.channel,
    ctx.messageProvider,
    ctx.provider,
    ctx.channelId,
    ctx.accountId,
    ctx.sessionKey,
    event.channel,
    event.messageProvider,
    event.provider,
    event.channelId,
    event.accountId,
    event.sessionKey,
    event?.payload?.channel,
    event?.payload?.messageProvider,
    event?.payload?.provider,
    event?.payload?.sessionKey
  ].filter((value) => value !== undefined && value !== null && String(value).trim() !== "").map(String);
}

function isWhatsApp(event = {}, ctx = {}) {
  return channelEvidence(event, ctx).some((value) => /whatsapp/i.test(value));
}

function inspectableEventText(event) {
  const values = [event?.content, event?.text, event?.message, event?.payload?.text, event?.payload?.content, event?.payload?.message, event?.payload];
  try { values.push(JSON.stringify(event || {})); } catch {}
  return values.map(normalizeText).filter(Boolean).join("\n");
}

function visibleMessageText(event) {
  return [event?.content, event?.text, event?.message, event?.payload?.text, event?.payload?.content, event?.payload?.message].map(normalizeText).find(Boolean) || "";
}

function resolveTarget(event = {}, ctx = {}) {
  return String(event?.to || event?.recipientId || event?.target || event?.payload?.to || event?.payload?.recipientId || event?.payload?.target || ctx?.recipientId || ctx?.target || ctx?.chatId || ctx?.channelId || "").trim();
}

function resolveSender(event = {}, ctx = {}) {
  return String(ctx?.senderId || event?.senderId || event?.from || event?.payload?.senderId || event?.payload?.from || "").trim();
}

function fingerprint(target, text) {
  return createHash("sha256").update(`${target}\u0000${text}`).digest("hex");
}

function runtimeOwnerNumber(api, pluginConfig) {
  const cfg = api?.runtime?.config?.current?.() || api?.config || {};
  const entries = cfg?.plugins?.entries || {};
  return pluginConfig.ownerNumber || process.env.SAHJONY_OWNER_WHATSAPP_E164 || entries?.["sahjony-app-bridge"]?.config?.businessNumber || entries?.["sahjony-whatsapp-reply-rescue"]?.config?.businessNumber || "";
}

export default definePluginEntry({
  id: "sahjony-whatsapp-output-guard",
  name: "SAHJONY WhatsApp Output Guard",
  description: "Classifies SOFIA WhatsApp owner/customer context, blocks internal leakage, runtime diagnostics, and duplicate deliveries.",
  register(api) {
    const pluginConfig = (api.pluginConfig && typeof api.pluginConfig === "object") ? api.pluginConfig : {};
    const ownerPeer = normalizePeer(runtimeOwnerNumber(api, pluginConfig));
    const failClosedExternal = pluginConfig.failClosedExternal !== false;
    const recentSent = new Map();
    const stateRoot = String(process.env.OPENCLAW_STATE_DIR || process.env.OPENCLAW_HOME || "").trim();
    const ledgerDir = stateRoot ? join(stateRoot, "whatsapp-delivery-ledger") : "";

    if (!ownerPeer) api.logger.warn("SAHJONY_OUTPUT_GUARD owner identity unresolved; WhatsApp turns fail closed as CUSTOMER_PARTNER");

    if (ledgerDir) {
      try { mkdirSync(ledgerDir, { recursive: true, mode: 0o700 }); } catch (error) {
        api.logger.warn(`SAHJONY_OUTPUT_GUARD persistent ledger unavailable: ${error instanceof Error ? error.message : "unknown error"}`);
      }
    }

    function isOwnerPeer(value) {
      const peer = normalizePeer(value);
      return Boolean(ownerPeer && peer && peer === ownerPeer);
    }

    function pruneMemory(now = Date.now()) {
      const cutoff = now - MEMORY_TTL_MS;
      for (const [key, ts] of recentSent.entries()) if (ts < cutoff) recentSent.delete(key);
    }

    function readPersistentTimestamp(key) {
      if (!ledgerDir) return 0;
      try {
        const value = Number(readFileSync(join(ledgerDir, key), "utf8").trim());
        return Number.isFinite(value) ? value : 0;
      } catch { return 0; }
    }

    function recordSuccessfulSend(key, ts) {
      recentSent.set(key, ts);
      if (!ledgerDir) return;
      try { writeFileSync(join(ledgerDir, key), String(ts), { mode: 0o600 }); } catch {}
    }

    function blockInternalRuntime(event, ctx, surface) {
      if (!isWhatsApp(event, ctx)) return undefined;
      const text = inspectableEventText(event);
      if (!INTERNAL_OUTPUT.test(text)) return undefined;
      api.logger.warn(`SAHJONY_OUTPUT_GUARD blocked internal WhatsApp ${surface}`);
      return { cancel: true, cancelReason: "internal_runtime_output" };
    }

    api.on("before_prompt_build", async (event, ctx) => {
      if (ctx?.trigger && ctx.trigger !== "user") return undefined;
      if (!isWhatsApp(event, ctx)) return undefined;
      const owner = isOwnerPeer(resolveSender(event, ctx));
      const mode = owner ? "OWNER_COMMAND" : "CUSTOMER_PARTNER";
      api.logger.info(`SAHJONY_OUTPUT_GUARD prompt context=${mode} sender_class=${owner ? "owner" : "external_or_unknown"}`);
      return { prependContext: owner ? OWNER_CONTEXT : CUSTOMER_CONTEXT };
    });

    api.on("reply_payload_sending", async (event, ctx) => blockInternalRuntime(event, ctx, "payload"));

    api.on("message_sending", async (event, ctx) => {
      const internal = blockInternalRuntime(event, ctx, "message");
      if (internal) return internal;
      if (!isWhatsApp(event, ctx)) return undefined;
      const target = resolveTarget(event, ctx);
      const text = visibleMessageText(event);
      if (!target || !text) return undefined;
      const ownerTarget = isOwnerPeer(target);
      if (!ownerTarget && failClosedExternal && INTERNAL_COMMERCIAL_OUTPUT.test(text)) {
        api.logger.warn("SAHJONY_OUTPUT_GUARD blocked internal commercial mechanics from external WhatsApp delivery");
        return { cancel: true, cancelReason: "internal_commercial_output_external" };
      }
      const now = Date.now();
      pruneMemory(now);
      const key = fingerprint(target, text);
      const lastSuccessful = Math.max(recentSent.get(key) || 0, readPersistentTimestamp(key));
      if (lastSuccessful && now - lastSuccessful < RECENT_DUPLICATE_MS) {
        api.logger.warn(`SAHJONY_OUTPUT_GUARD duplicate successful delivery suppressed target_class=${ownerTarget ? "owner" : "external"} age_ms=${now - lastSuccessful}`);
        return { cancel: true, cancelReason: "recent_successful_duplicate" };
      }
      return undefined;
    });

    api.on("message_sent", async (event, ctx) => {
      if (!isWhatsApp(event, ctx)) return;
      const target = resolveTarget(event, ctx);
      const text = visibleMessageText(event);
      if (!target || !text || INTERNAL_OUTPUT.test(text)) return;
      const now = Date.now();
      recordSuccessfulSend(fingerprint(target, text), now);
      pruneMemory(now);
    });

    api.logger.info(`SAHJONY WhatsApp output guard ready (version=${GUARD_VERSION}, owner-identity=${ownerPeer ? "resolved" : "unresolved"}, recipient-context=active, source-ownership=active, external-commercial-leak-guard=${failClosedExternal ? "fail-closed" : "disabled"}, runtime-error-suppression=active, duplicate-suppression=${RECENT_DUPLICATE_MS}ms, persistent-ledger=${ledgerDir ? "enabled" : "memory-only"})`);
  }
});
