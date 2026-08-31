import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

function safe(value, max = 500) {
  try {
    const text = typeof value === "string" ? value : JSON.stringify(value);
    return String(text ?? "").replace(/\s+/g, " ").slice(0, max);
  } catch {
    return "[unserializable]";
  }
}

function whatsappSession(value) {
  return String(value || "").includes(":whatsapp:");
}

export default definePluginEntry({
  id: "sahjony-agent-diagnostics",
  name: "SAHJONY Agent Diagnostics",
  description: "Passive diagnostics for model execution and WhatsApp reply delivery.",
  register(api) {
    const log = (stage, fields = {}) => {
      api.logger.info(`[SAHJONY_DIAG] ${stage} ${safe(fields, 1800)}`);
    };

    api.on("model_call_started", async (event) => {
      if (event.sessionKey && !whatsappSession(event.sessionKey)) return;
      log("MODEL_START", {
        runId: event.runId,
        callId: event.callId,
        sessionKey: event.sessionKey,
        provider: event.provider,
        model: event.model,
        api: event.api,
        transport: event.transport,
        contextTokenBudget: event.contextTokenBudget,
      });
    });

    api.on("model_call_ended", async (event) => {
      if (event.sessionKey && !whatsappSession(event.sessionKey)) return;
      log("MODEL_END", {
        runId: event.runId,
        callId: event.callId,
        sessionKey: event.sessionKey,
        provider: event.provider,
        model: event.model,
        durationMs: event.durationMs,
        outcome: event.outcome,
        errorCategory: event.errorCategory,
        failureKind: event.failureKind,
        timeToFirstByteMs: event.timeToFirstByteMs,
        responseStreamBytes: event.responseStreamBytes,
      });
    });

    api.on("agent_end", async (event, ctx) => {
      const sessionKey = String(ctx.sessionKey || "");
      if (sessionKey && !whatsappSession(sessionKey)) return;
      log("AGENT_END", {
        runId: event.runId,
        sessionKey,
        success: event.success,
        error: event.error,
        durationMs: event.durationMs,
        messageCount: Array.isArray(event.messages) ? event.messages.length : undefined,
      });
    });

    api.on("reply_payload_sending", async (event, ctx) => {
      const sessionKey = String(event.sessionKey || ctx.sessionKey || "");
      const channel = String(ctx.channel || ctx.messageProvider || event.channel || "");
      if (channel && channel !== "whatsapp" && !whatsappSession(sessionKey)) return;
      log("REPLY_PAYLOAD", {
        runId: event.runId,
        sessionKey,
        channel,
        kind: event.kind,
        textLength: String(event.payload?.text || "").length,
        hasMedia: Boolean(event.payload?.mediaUrl || event.payload?.mediaUrls?.length),
      });
      return undefined;
    });

    api.on("message_sending", async (event, ctx) => {
      const channel = String(ctx.channel || ctx.messageProvider || "");
      if (channel !== "whatsapp") return;
      log("MESSAGE_SENDING", {
        channel,
        to: event.to,
        messageId: event.messageId || ctx.messageId,
        textLength: String(event.content || "").length,
      });
      return undefined;
    });

    api.on("message_sent", async (event, ctx) => {
      const channel = String(ctx.channel || ctx.messageProvider || "");
      if (channel !== "whatsapp") return;
      log("MESSAGE_SENT", {
        channel,
        to: event.to,
        messageId: event.messageId || ctx.messageId,
        success: event.success,
        textLength: String(event.content || "").length,
      });
    });

    api.on("gateway_start", async () => {
      log("DIAGNOSTICS_READY", { version: "1.0.0" });
    });
  },
});
