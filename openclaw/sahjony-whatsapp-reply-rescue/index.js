import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const execFile = promisify(execFileCb);
const RESCUE_VERSION = "2.1.0";
const MEMORY_TTL_MS = 30 * 60 * 1000;
const MAX_HISTORY_MESSAGES = 12;
const MAX_HISTORY_CHARS = 9000;

const SYSTEM_PROMPT = `You are Sofia Reyes, Trade Concierge at SAHJONY LLC. Communicate like a skilled, attentive company representative: warm, concise, confident, natural, context-aware, and never robotic. Match the customer's language, vocabulary, formality, and message length. Use short paragraphs when appropriate. Do not over-format routine WhatsApp replies, do not repeat the customer's entire request, do not use canned AI-assistant phrases, and do not mention models, prompts, automation, fallback logic, internal systems, or infrastructure. Introduce yourself only when it is natural for a first-contact conversation; do not reintroduce yourself on every message. Never spontaneously say you are an AI or automated system. If directly asked whether you are AI or automated, answer truthfully and briefly that you are SAHJONY LLC's automated business assistant operating as Sofia Reyes, then continue helping without making the conversation awkward. Never claim to be a human being or invent personal history, credentials, physical experiences, or employment facts that are not verified. Answer inbound business inquiries clearly and professionally. Never invent live prices, inventory, shipment status, contracts, certifications, legal approvals, supplier offers, freight costs, or binding terms. Ask only for the minimum missing commercial details. Preserve exact names, companies, quantities, dates, currencies, specifications, ports, and reference numbers. You are receiving a bounded recovery transcript after an interrupted assistant turn. Continue from the transcript and answer the customer's latest request directly. Do not ask the customer to repeat information already present in the transcript. Never mention the interruption, OpenClaw, runtime errors, retry logic, /new, or session recovery. Never expose hidden reasoning or chain-of-thought.`;

const INTERNAL_OUTPUT = /(?:↪️\s*Model Fallback|Model Fallback cleared|Missing API key|Use\s+[`'“”]?openai-codex\/|\bfor OAuth\b|\bset\s+[`'“”]?(?:OPENAI|NVIDIA)_API_KEY|gateway number|messaging itself|OPENAI_API_KEY|NVIDIA_API_KEY|provider-transport-fetch|\brawError=|\bstack trace\b|non_deliverable_terminal_turn|Something went wrong while processing your request|Please try again,? or use \/new to start a fresh session|use \/new to start a fresh session|Agent couldn['’]t generate a response|The agent run failed before producing a reply|Ese mensaje de error es generado por el propio sistema de OpenClaw|no se puede desactivar desde aquí)/i;

function normalizeText(value) {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    return value.map((part) => {
      if (typeof part === "string") return part;
      if (part && typeof part === "object") return String(part.text || part.content || part.message || "");
      return "";
    }).join("\n").trim();
  }
  return "";
}

function inspectableEventText(event) {
  const values = [
    event?.content,
    event?.text,
    event?.message,
    event?.payload?.text,
    event?.payload?.content,
    event?.payload?.message
  ];
  try { values.push(JSON.stringify(event?.payload || {})); } catch {}
  try { values.push(JSON.stringify(event || {})); } catch {}
  return values.map(normalizeText).filter(Boolean).join("\n");
}

function channelEvidence(event, ctx) {
  return [
    ctx?.channel,
    ctx?.messageProvider,
    ctx?.provider,
    ctx?.channelId,
    ctx?.accountId,
    ctx?.sessionKey,
    event?.channel,
    event?.messageProvider,
    event?.provider,
    event?.channelId,
    event?.accountId,
    event?.sessionKey,
    event?.payload?.channel,
    event?.payload?.messageProvider,
    event?.payload?.provider,
    event?.payload?.sessionKey
  ].filter((value) => value !== undefined && value !== null && String(value).trim() !== "").map(String);
}

function isWhatsAppContext(event, ctx) {
  return channelEvidence(event, ctx).some((value) => /whatsapp/i.test(value));
}

function hasExplicitNonWhatsAppContext(event, ctx) {
  const evidence = channelEvidence(event, ctx);
  if (!evidence.length) return false;
  return !evidence.some((value) => /whatsapp/i.test(value));
}

function boundedHistory(history) {
  const sliced = history.slice(-MAX_HISTORY_MESSAGES);
  const out = [];
  let chars = 0;
  for (let i = sliced.length - 1; i >= 0; i -= 1) {
    const row = sliced[i];
    const text = normalizeText(row?.content).slice(0, 1800);
    if (!text || INTERNAL_OUTPUT.test(text)) continue;
    if (chars + text.length > MAX_HISTORY_CHARS && out.length > 0) break;
    out.unshift({ role: row.role === "assistant" ? "assistant" : "user", content: text });
    chars += text.length;
  }
  return out;
}

async function generateNvidiaReply(history, apiKey, logger) {
  const candidates = [
    "openai/gpt-oss-120b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3.5-lightning-30b-a3b"
  ];
  const transcript = boundedHistory(history);
  if (!transcript.length) return null;

  for (const model of candidates) {
    try {
      const response = await fetch("https://integrate.api.nvidia.com/v1/chat/completions", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${apiKey}`,
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        body: JSON.stringify({
          model,
          messages: [
            { role: "system", content: SYSTEM_PROMPT },
            ...transcript
          ],
          temperature: model === "openai/gpt-oss-120b" ? 1 : 0.35,
          top_p: 1,
          max_tokens: model === "openai/gpt-oss-120b" ? 1600 : 900
        }),
        signal: AbortSignal.timeout(45000)
      });
      if (!response.ok) {
        logger.warn(`SAHJONY reply rescue model ${model} returned HTTP ${response.status}`);
        continue;
      }
      const data = await response.json();
      const message = data?.choices?.[0]?.message || {};
      // Only customer-visible model content is eligible for delivery. Never surface reasoning_content.
      const text = normalizeText(message.content);
      if (text && !INTERNAL_OUTPUT.test(text)) return { text, model };
      logger.warn(`SAHJONY reply rescue model ${model} returned no safe visible content`);
    } catch (error) {
      logger.warn(`SAHJONY reply rescue model ${model} failed: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  }
  return null;
}

export default definePluginEntry({
  id: "sahjony-whatsapp-reply-rescue",
  name: "SAHJONY WhatsApp Reply Rescue",
  description: "Context-preserving fail-safe reply generation for WhatsApp turns that otherwise end silently or leak runtime errors.",
  register(api) {
    const cfg = api.pluginConfig || {};
    const accountId = String(cfg.accountId || "default");
    const businessNumber = String(cfg.businessNumber || "+12816628581");
    const rescueDelayMs = Math.max(10000, Math.min(45000, Number(cfg.rescueDelayMs || 15000)));
    const openclawBin = String(process.env.OPENCLAW_BIN || (process.env.HOME ? `${process.env.HOME}/.openclaw/bin/openclaw` : "openclaw"));
    const nvidiaKey = String(process.env.NVIDIA_API_KEY || "");
    const pending = new Map();
    const conversation = new Map();
    const rescuedTurns = new Map();

    function now() { return Date.now(); }

    function pruneState() {
      const cutoff = now() - MEMORY_TTL_MS;
      for (const [key, state] of conversation.entries()) {
        if ((state.updatedAt || 0) < cutoff) conversation.delete(key);
      }
      for (const [turnId, ts] of rescuedTurns.entries()) {
        if (ts < cutoff) rescuedTurns.delete(turnId);
      }
    }

    function clearPending(key) {
      const item = pending.get(key);
      if (!item) return;
      clearTimeout(item.timer);
      pending.delete(key);
    }

    function resolveKey(event, ctx) {
      return String(ctx?.sessionKey || event?.sessionKey || event?.threadId || event?.senderId || ctx?.senderId || "");
    }

    function resolveTurnId(event, ctx, key) {
      return String(event?.messageId || ctx?.messageId || `${key}:${now()}`);
    }

    function resolveTarget(event, ctx) {
      return String(
        event?.to || event?.recipientId || event?.target || event?.payload?.to || event?.payload?.recipientId ||
        ctx?.recipientId || ctx?.target || ""
      );
    }

    function remember(key, role, text) {
      const clean = normalizeText(text).slice(0, 2400);
      if (!key || !clean || INTERNAL_OUTPUT.test(clean)) return;
      const state = conversation.get(key) || { messages: [], updatedAt: 0 };
      state.messages.push({ role, content: clean });
      state.messages = state.messages.slice(-MAX_HISTORY_MESSAGES);
      state.updatedAt = now();
      conversation.set(key, state);
    }

    function historyFor(key, latestUserText) {
      const state = conversation.get(key);
      const rows = Array.isArray(state?.messages) ? [...state.messages] : [];
      const last = rows[rows.length - 1];
      if (!last || last.role !== "user" || normalizeText(last.content) !== normalizeText(latestUserText)) {
        rows.push({ role: "user", content: latestUserText });
      }
      return rows;
    }

    function keysForTarget(target) {
      const keys = [];
      for (const [key, item] of pending.entries()) {
        if (item.sender === target) keys.push(key);
      }
      return keys;
    }

    function findPending(event, ctx) {
      const key = resolveKey(event, ctx);
      if (key && pending.has(key)) return { key, item: pending.get(key) };

      const target = resolveTarget(event, ctx);
      if (target) {
        const matches = keysForTarget(target);
        if (matches.length === 1) return { key: matches[0], item: pending.get(matches[0]) };
      }

      // Some terminal OpenClaw runtime failures arrive without channel/session
      // metadata. If exactly one WhatsApp turn is pending, it is safe to bind the
      // terminal failure to that turn instead of leaking the generic /new notice.
      if (pending.size === 1 && !hasExplicitNonWhatsAppContext(event, ctx)) {
        const [onlyKey, onlyItem] = pending.entries().next().value;
        return { key: onlyKey, item: onlyItem };
      }
      return { key: "", item: null };
    }

    function shouldHandleWhatsAppRuntimeOutput(event, ctx) {
      if (isWhatsAppContext(event, ctx)) return true;
      if (hasExplicitNonWhatsAppContext(event, ctx)) return false;
      return pending.size > 0;
    }

    async function sendViaOpenClaw(target, text) {
      const result = await execFile(openclawBin, [
        "message", "send", "--channel", "whatsapp", "--account", accountId,
        "--target", target, "--message", text, "--json"
      ], {
        timeout: 45000,
        maxBuffer: 1024 * 1024,
        env: process.env
      });
      return String(result.stdout || "");
    }

    async function rescueNow(item, key, reason) {
      if (!item || item.rescuing || rescuedTurns.has(item.turnId)) return;
      if (pending.get(key) !== item) return;
      item.rescuing = true;
      if (!nvidiaKey.startsWith("nvapi-")) {
        api.logger.error("SAHJONY reply rescue skipped: NVIDIA_API_KEY unavailable or invalid");
        item.rescuing = false;
        return;
      }

      const generated = await generateNvidiaReply(item.history, nvidiaKey, api.logger);
      if (!generated?.text) {
        api.logger.error(`SAHJONY reply rescue failed to generate visible reply for ${key}`);
        item.rescuing = false;
        return;
      }
      if (pending.get(key) !== item || rescuedTurns.has(item.turnId)) return;

      try {
        rescuedTurns.set(item.turnId, now());
        await sendViaOpenClaw(item.sender, generated.text);
        remember(key, "assistant", generated.text);
        clearPending(key);
        api.logger.warn(`SAHJONY_REPLY_RESCUED version=${RESCUE_VERSION} session=${key} reason=${reason} model=${generated.model} chars=${generated.text.length}`);
      } catch (error) {
        rescuedTurns.delete(item.turnId);
        item.rescuing = false;
        api.logger.error(`SAHJONY reply rescue delivery failed: ${error instanceof Error ? error.message : "unknown error"}`);
      }
    }

    api.on("message_received", async (event, ctx) => {
      if (!isWhatsAppContext(event, ctx)) return;
      pruneState();
      const sender = String(event.senderId || ctx.senderId || "");
      const content = String(event.content || "").trim();
      const key = resolveKey(event, ctx);
      if (!sender || !content || !key || sender === businessNumber) return;

      clearPending(key);
      remember(key, "user", content);
      const turnId = resolveTurnId(event, ctx, key);
      const item = {
        sender,
        content,
        history: historyFor(key, content),
        turnId,
        timer: null,
        createdAt: now(),
        rescuing: false
      };
      item.timer = setTimeout(async () => {
        const current = pending.get(key);
        if (!current || current.turnId !== turnId) return;
        await rescueNow(current, key, "timeout");
      }, rescueDelayMs);
      pending.set(key, item);
    });

    api.on("reply_payload_sending", async (event, ctx) => {
      if (!INTERNAL_OUTPUT.test(inspectableEventText(event))) return undefined;
      if (!shouldHandleWhatsAppRuntimeOutput(event, ctx)) return undefined;
      api.logger.warn("SAHJONY_REPLY_RESCUE blocked internal WhatsApp output");
      const found = findPending(event, ctx);
      if (found.item) queueMicrotask(() => { void rescueNow(found.item, found.key, "blocked_runtime_error"); });
      return { cancel: true, cancelReason: "internal_runtime_output" };
    });

    api.on("message_sending", async (event, ctx) => {
      if (!INTERNAL_OUTPUT.test(inspectableEventText(event))) return undefined;
      if (!shouldHandleWhatsAppRuntimeOutput(event, ctx)) return undefined;
      api.logger.warn("SAHJONY_REPLY_RESCUE blocked internal WhatsApp message");
      const found = findPending(event, ctx);
      if (found.item) queueMicrotask(() => { void rescueNow(found.item, found.key, "blocked_runtime_error"); });
      return { cancel: true, cancelReason: "internal_runtime_output" };
    });

    api.on("message_sent", async (event, ctx) => {
      const found = findPending(event, ctx);
      if (!isWhatsAppContext(event, ctx) && !found.item) return;
      const visibleText = inspectableEventText(event);
      if (INTERNAL_OUTPUT.test(visibleText)) {
        api.logger.error("SAHJONY_REPLY_RESCUE observed an internal runtime message after send stage; keeping rescue pending");
        if (found.item) queueMicrotask(() => { void rescueNow(found.item, found.key, "post_send_runtime_error"); });
        return;
      }

      const key = found.key || resolveKey(event, ctx);
      const to = String(event.to || ctx.channelId || event.recipientId || "");
      if (key && visibleText) remember(key, "assistant", visibleText);
      if (key) clearPending(key);
      if (to) {
        for (const candidateKey of keysForTarget(to)) {
          if (visibleText) remember(candidateKey, "assistant", visibleText);
          clearPending(candidateKey);
        }
      }
    });

    api.on("gateway_stop", async () => {
      for (const key of [...pending.keys()]) clearPending(key);
    });

    api.logger.info(`SAHJONY reply rescue ready (version=${RESCUE_VERSION}, delay=${rescueDelayMs}ms, context_window=${MAX_HISTORY_MESSAGES}, primary-rescue=openai/gpt-oss-120b, reasoning-output=blocked, metadata-less-terminal-recovery=active)`);
  }
});
