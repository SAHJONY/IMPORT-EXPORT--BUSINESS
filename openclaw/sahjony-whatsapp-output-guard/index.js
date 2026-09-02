import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

const INTERNAL_OUTPUT = /(?:↪️\s*Model Fallback|Model Fallback cleared|Missing API key|openai-codex\/|gateway number|messaging itself|OPENAI_API_KEY|NVIDIA_API_KEY|provider-transport-fetch|\brawError=|\bstack trace\b)/i;

function isWhatsApp(ctx = {}) {
  return ctx.channel === "whatsapp" || ctx.messageProvider === "whatsapp" || String(ctx.sessionKey || "").includes(":whatsapp:");
}

export default definePluginEntry({
  id: "sahjony-whatsapp-output-guard",
  name: "SAHJONY WhatsApp Output Guard",
  description: "Prevents operational diagnostics from reaching WhatsApp.",
  register(api) {
    api.on("reply_payload_sending", async (event, ctx) => {
      if (!isWhatsApp(ctx)) return;
      const text = String(event?.payload?.text || "");
      if (INTERNAL_OUTPUT.test(text)) {
        api.logger.warn("SAHJONY_OUTPUT_GUARD blocked an internal WhatsApp payload");
        return { cancel: true, cancelReason: "internal_runtime_output" };
      }
      return undefined;
    });

    api.on("message_sending", async (event, ctx) => {
      if (!isWhatsApp(ctx)) return;
      const text = String(event?.content || "");
      if (INTERNAL_OUTPUT.test(text)) {
        api.logger.warn("SAHJONY_OUTPUT_GUARD blocked an internal WhatsApp message");
        return { cancel: true, cancelReason: "internal_runtime_output" };
      }
      return undefined;
    });

    api.logger.info("SAHJONY WhatsApp output guard ready");
  }
});
