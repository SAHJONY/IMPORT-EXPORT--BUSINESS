import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const INTERNAL_OUTPUT = /(?:↪️\s*Model Fallback|Model Fallback cleared|Missing API key|openai-codex\/|gateway number|messaging itself|OPENAI_API_KEY|NVIDIA_API_KEY|provider-transport-fetch|\brawError=|\bstack trace\b|Something went wrong while processing your request|Please try again,? or use \/new to start a fresh session|Ese mensaje de error es generado por el propio sistema de OpenClaw|no se puede desactivar desde aquí)/i;

function isWhatsApp(ctx = {}) {
  return ctx.channel === "whatsapp" || ctx.messageProvider === "whatsapp" || String(ctx.sessionKey || "").includes(":whatsapp:");
}

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

function inspectableEventText(event) {
  return [
    event?.content,
    event?.text,
    event?.message,
    event?.payload?.text,
    event?.payload?.content,
    event?.payload?.message,
    event?.payload
  ].map(normalizeText).filter(Boolean).join("\n");
}

export default definePluginEntry({
  id: "sahjony-whatsapp-output-guard",
  name: "SAHJONY WhatsApp Output Guard",
  description: "Prevents operational diagnostics and runtime failure notices from reaching WhatsApp.",
  register(api) {
    const block = (event, ctx, surface) => {
      if (!isWhatsApp(ctx)) return undefined;
      const text = inspectableEventText(event);
      if (!INTERNAL_OUTPUT.test(text)) return undefined;
      api.logger.warn(`SAHJONY_OUTPUT_GUARD blocked internal WhatsApp ${surface}`);
      return { cancel: true, cancelReason: "internal_runtime_output" };
    };

    api.on("reply_payload_sending", async (event, ctx) => block(event, ctx, "payload"));
    api.on("message_sending", async (event, ctx) => block(event, ctx, "message"));

    api.logger.info("SAHJONY WhatsApp output guard ready (runtime-error suppression active)");
  }
});
