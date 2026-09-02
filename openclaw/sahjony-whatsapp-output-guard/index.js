import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const GUARD_VERSION = "2.0.0";
const RECENT_DUPLICATE_MS = 30_000;
const MEMORY_TTL_MS = 10 * 60_000;
const INTERNAL_OUTPUT = /(?:↪️\s*Model Fallback|Model Fallback cleared|Missing API key|openai-codex\/|gateway number|messaging itself|OPENAI_API_KEY|NVIDIA_API_KEY|provider-transport-fetch|\brawError=|\bstack trace\b|non_deliverable_terminal_turn|Something went wrong while processing your request|Please try again,? or use \/new to start a fresh session|use \/new to start a fresh session|Agent couldn['’]t generate a response|The agent run failed before producing a reply|Ese mensaje de error es generado por el propio sistema de OpenClaw|no se puede desactivar desde aquí)/i;

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
  const values = [
    event?.content,
    event?.text,
    event?.message,
    event?.payload?.text,
    event?.payload?.content,
    event?.payload?.message,
    event?.payload
  ];
  try { values.push(JSON.stringify(event || {})); } catch {}
  return values.map(normalizeText).filter(Boolean).join("\n");
}

function visibleMessageText(event) {
  return [
    event?.content,
    event?.text,
    event?.message,
    event?.payload?.text,
    event?.payload?.content,
    event?.payload?.message
  ].map(normalizeText).find(Boolean) || "";
}

function resolveTarget(event = {}, ctx = {}) {
  return String(
    event?.to || event?.recipientId || event?.target ||
    event?.payload?.to || event?.payload?.recipientId || event?.payload?.target ||
    ctx?.recipientId || ctx?.target || ctx?.channelId || ""
  ).trim();
}

function fingerprint(target, text) {
  return createHash("sha256").update(`${target}\u0000${text}`).digest("hex");
}

export default definePluginEntry({
  id: "sahjony-whatsapp-output-guard",
  name: "SAHJONY WhatsApp Output Guard",
  description: "Blocks operational diagnostics and suppresses recently successful duplicate WhatsApp deliveries.",
  register(api) {
    const recentSent = new Map();
    const stateRoot = String(process.env.OPENCLAW_STATE_DIR || process.env.OPENCLAW_HOME || "").trim();
    const ledgerDir = stateRoot ? join(stateRoot, "whatsapp-delivery-ledger") : "";
    if (ledgerDir) {
      try { mkdirSync(ledgerDir, { recursive: true, mode: 0o700 }); } catch (error) {
        api.logger.warn(`SAHJONY_OUTPUT_GUARD persistent ledger unavailable: ${error instanceof Error ? error.message : "unknown error"}`);
      }
    }

    function pruneMemory(now = Date.now()) {
      const cutoff = now - MEMORY_TTL_MS;
      for (const [key, ts] of recentSent.entries()) {
        if (ts < cutoff) recentSent.delete(key);
      }
    }

    function readPersistentTimestamp(key) {
      if (!ledgerDir) return 0;
      try {
        const value = Number(readFileSync(join(ledgerDir, key), "utf8").trim());
        return Number.isFinite(value) ? value : 0;
      } catch {
        return 0;
      }
    }

    function recordSuccessfulSend(key, ts) {
      recentSent.set(key, ts);
      if (!ledgerDir) return;
      try { writeFileSync(join(ledgerDir, key), String(ts), { mode: 0o600 }); } catch {}
    }

    function blockInternal(event, ctx, surface) {
      if (!isWhatsApp(event, ctx)) return undefined;
      const text = inspectableEventText(event);
      if (!INTERNAL_OUTPUT.test(text)) return undefined;
      api.logger.warn(`SAHJONY_OUTPUT_GUARD blocked internal WhatsApp ${surface}`);
      return { cancel: true, cancelReason: "internal_runtime_output" };
    }

    api.on("reply_payload_sending", async (event, ctx) => blockInternal(event, ctx, "payload"));

    api.on("message_sending", async (event, ctx) => {
      const internal = blockInternal(event, ctx, "message");
      if (internal) return internal;
      if (!isWhatsApp(event, ctx)) return undefined;

      const target = resolveTarget(event, ctx);
      const text = visibleMessageText(event);
      if (!target || !text) return undefined;

      const now = Date.now();
      pruneMemory(now);
      const key = fingerprint(target, text);
      const lastSuccessful = Math.max(recentSent.get(key) || 0, readPersistentTimestamp(key));
      if (lastSuccessful && now - lastSuccessful < RECENT_DUPLICATE_MS) {
        api.logger.warn(`SAHJONY_OUTPUT_GUARD duplicate successful delivery suppressed target=${target} age_ms=${now - lastSuccessful}`);
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

    api.logger.info(`SAHJONY WhatsApp output guard ready (version=${GUARD_VERSION}, runtime-error suppression=active, successful-send duplicate suppression=${RECENT_DUPLICATE_MS}ms, persistent-ledger=${ledgerDir ? "enabled" : "memory-only"})`);
  }
});
