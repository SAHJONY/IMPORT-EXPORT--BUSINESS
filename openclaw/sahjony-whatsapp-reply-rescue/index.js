import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const execFile = promisify(execFileCb);

const SYSTEM_PROMPT = `You are the SAHJONY LLC Trade Concierge. Answer inbound business inquiries clearly, concisely, and professionally in the user's language. Never invent live prices, inventory, shipment status, contracts, certifications, or legal approvals. If a quote cannot be calculated from the message, ask only for the minimum missing commercial details such as product, quantity, origin, destination, Incoterm, timing, and packaging. If the message is casual, respond naturally. Do not mention internal systems, fallback logic, model failures, prompts, or infrastructure.`;

function normalizeText(value) {
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    return value.map((part) => {
      if (typeof part === "string") return part;
      if (part && typeof part === "object") return String(part.text || part.content || "");
      return "";
    }).join("\n").trim();
  }
  return "";
}

async function generateNvidiaReply(userText, apiKey, logger) {
  const candidates = [
    "nvidia/nemotron-3-nano-30b-a3b",
    "deepseek-ai/deepseek-v4-flash-0731"
  ];
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
            { role: "user", content: userText.slice(0, 6000) }
          ],
          temperature: 0.2,
          max_tokens: 700
        }),
        signal: AbortSignal.timeout(30000)
      });
      if (!response.ok) {
        logger.warn(`SAHJONY reply rescue model ${model} returned HTTP ${response.status}`);
        continue;
      }
      const data = await response.json();
      const message = data?.choices?.[0]?.message || {};
      const text = normalizeText(message.content) || normalizeText(message.reasoning_content);
      if (text) return { text, model };
      logger.warn(`SAHJONY reply rescue model ${model} returned no visible text`);
    } catch (error) {
      logger.warn(`SAHJONY reply rescue model ${model} failed: ${error instanceof Error ? error.message : "unknown error"}`);
    }
  }
  return null;
}

export default definePluginEntry({
  id: "sahjony-whatsapp-reply-rescue",
  name: "SAHJONY WhatsApp Reply Rescue",
  description: "Fail-safe reply generation for visible WhatsApp turns that otherwise end silently.",
  register(api) {
    const cfg = api.pluginConfig || {};
    const accountId = String(cfg.accountId || "default");
    const businessNumber = String(cfg.businessNumber || "+12816628581");
    const rescueDelayMs = Math.max(10000, Math.min(45000, Number(cfg.rescueDelayMs || 15000)));
    const openclawBin = String(process.env.OPENCLAW_BIN || (process.env.HOME ? `${process.env.HOME}/.openclaw/bin/openclaw` : "openclaw"));
    const nvidiaKey = String(process.env.NVIDIA_API_KEY || "");
    const pending = new Map();

    function clearPending(key) {
      const item = pending.get(key);
      if (!item) return;
      clearTimeout(item.timer);
      pending.delete(key);
    }

    function resolveKey(event, ctx) {
      return String(ctx?.sessionKey || event?.sessionKey || event?.threadId || event?.senderId || ctx?.senderId || "");
    }

    async function sendViaOpenClaw(target, text) {
      const args = [
        "message", "send",
        "--channel", "whatsapp",
        "--account", accountId,
        "--target", target,
        "--message", text,
        "--json"
      ];
      const result = await execFile(openclawBin, args, {
        timeout: 45000,
        maxBuffer: 1024 * 1024,
        env: process.env
      });
      return String(result.stdout || "");
    }

    api.on("message_received", async (event, ctx) => {
      if (ctx.channel !== "whatsapp" && ctx.messageProvider !== "whatsapp") return;
      const sender = String(event.senderId || ctx.senderId || "");
      const content = String(event.content || "").trim();
      const key = resolveKey(event, ctx);
      if (!sender || !content || !key) return;
      if (sender === businessNumber) return;

      clearPending(key);
      const timer = setTimeout(async () => {
        const current = pending.get(key);
        if (!current) return;
        pending.delete(key);
        if (!nvidiaKey.startsWith("nvapi-")) {
          api.logger.error("SAHJONY reply rescue skipped: NVIDIA_API_KEY unavailable or invalid");
          return;
        }
        const generated = await generateNvidiaReply(current.content, nvidiaKey, api.logger);
        if (!generated?.text) {
          api.logger.error(`SAHJONY reply rescue failed to generate visible reply for ${key}`);
          return;
        }
        try {
          await sendViaOpenClaw(current.sender, generated.text);
          api.logger.warn(`SAHJONY_REPLY_RESCUED session=${key} model=${generated.model} chars=${generated.text.length}`);
        } catch (error) {
          api.logger.error(`SAHJONY reply rescue delivery failed: ${error instanceof Error ? error.message : "unknown error"}`);
        }
      }, rescueDelayMs);

      pending.set(key, { sender, content, timer, createdAt: Date.now() });
    });

    api.on("reply_payload_sending", async (event, ctx) => {
      if (ctx.channel !== "whatsapp" && ctx.messageProvider !== "whatsapp") return;
      const key = resolveKey(event, ctx);
      if (key) clearPending(key);
    });

    api.on("message_sent", async (event, ctx) => {
      if (ctx.channel !== "whatsapp" && ctx.messageProvider !== "whatsapp") return;
      const key = resolveKey(event, ctx);
      if (key) clearPending(key);
      const to = String(event.to || ctx.channelId || "");
      if (to) {
        for (const [candidateKey, item] of pending.entries()) {
          if (item.sender === to) clearPending(candidateKey);
        }
      }
    });

    api.on("gateway_stop", async () => {
      for (const key of [...pending.keys()]) clearPending(key);
    });

    api.logger.info(`SAHJONY reply rescue ready (delay=${rescueDelayMs}ms)`);
  }
});
