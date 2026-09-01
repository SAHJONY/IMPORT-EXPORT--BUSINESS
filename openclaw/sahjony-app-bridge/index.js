import crypto from "node:crypto";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

function compactMedia(media) {
  if (!Array.isArray(media)) return [];
  return media.slice(0, 20).map((item) => {
    const fact = item && typeof item === "object" ? item : {};
    return {
      kind: typeof fact.kind === "string" ? fact.kind : void 0,
      contentType: typeof fact.contentType === "string" ? fact.contentType : void 0,
      transcribed: Boolean(fact.transcribed),
      messageId: typeof fact.messageId === "string" ? fact.messageId : void 0
    };
  });
}

var index_default = definePluginEntry({
  id: "sahjony-app-bridge",
  name: "SAHJONY Application Bridge",
  description: "Trusted WhatsApp-to-CRM bridge for SAHJONY LLC.",
  register(api) {
    const config = api.pluginConfig ?? {};
    const appUrl = String(config.appUrl || process.env.SAHJONY_APP_URL || "https://www.sahjony.com").replace(/\/$/, "");
    const secret = String(process.env.SAHJONY_APP_BRIDGE_SECRET || "");
    const accountId = String(config.accountId || process.env.SAHJONY_WHATSAPP_ACCOUNT_ID || "default");
    const gatewayId = String(config.gatewayId || process.env.SAHJONY_GATEWAY_ID || "hostinger-vps");
    const businessNumber = String(config.businessNumber || process.env.SAHJONY_WHATSAPP_BUSINESS_NUMBER || "+12816628581");
    const businessName = String(config.businessName || process.env.SAHJONY_WHATSAPP_BUSINESS_NAME || "SAHJONY LLC");
    const pollIntervalMs = Math.max(5e3, Math.min(3e5, Number(config.pollIntervalMs || 3e4)));
    const openclawBin = String(
      process.env.OPENCLAW_BIN ||
      (process.env.HOME ? `${process.env.HOME}/.openclaw/bin/openclaw` : "openclaw")
    );
    let stopped = false;
    let polling = false;
    let pollTimer;
    let heartbeatTimer;
    if (secret.length < 24) {
      api.logger.error("SAHJONY_APP_BRIDGE_SECRET must contain at least 24 characters; bridge disabled");
      return;
    }

    async function signedRequest(path, method, payload) {
      const body = payload === void 0 ? "" : JSON.stringify(payload);
      const timestamp = String(Math.floor(Date.now() / 1e3));
      const signature = "sha256=" + crypto.createHmac("sha256", secret).update(`${timestamp}.${body}`).digest("hex");
      const response = await fetch(`${appUrl}${path}`, {
        method,
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
          "X-SAHJONY-Timestamp": timestamp,
          "X-SAHJONY-Signature": signature
        },
        body: method === "POST" ? body : void 0,
        signal: AbortSignal.timeout(15e3)
      });
      if (!response.ok) throw new Error(`SAHJONY bridge HTTP ${response.status}`);
      return response;
    }

    async function postEvent(payload) {
      try {
        await signedRequest("/whatsapp/openclaw/events", "POST", payload);
        return true;
      } catch (error) {
        api.logger.warn(`SAHJONY event synchronization failed: ${error instanceof Error ? error.message : "unknown error"}`);
        return false;
      }
    }

    async function heartbeat() {
      let connected = false;
      let gatewayVersion;
      try {
        const probe = await api.runtime.system.runCommandWithTimeout(openclawBin, ["channels", "status", "--probe"], { timeoutMs: 2e4 });
        const output = `${probe.stdout || ""}\n${probe.stderr || ""}`;
        if (probe.code !== 0 || !/whatsapp/i.test(output)) {
          throw new Error(`unusable WhatsApp status probe (code=${probe.code})`);
        }
        connected = /whatsapp[^\n]*\bconnected\b/i.test(output) || /\blinked,\s*running,\s*connected\b/i.test(output);
        const version = await api.runtime.system.runCommandWithTimeout(openclawBin, ["--version"], { timeoutMs: 1e4 });
        gatewayVersion = String(version.stdout || "").trim().slice(0, 80) || void 0;
        if (version.code !== 0 || !gatewayVersion) {
          throw new Error(`unusable OpenClaw version probe (code=${version.code})`);
        }
      } catch (error) {
        api.logger.warn(`SAHJONY gateway probe unavailable; heartbeat deferred to sidecar: ${error instanceof Error ? error.message : "unknown error"}`);
        return;
      }
      try {
        await signedRequest("/whatsapp/openclaw/heartbeat", "POST", {
          gateway_id: gatewayId,
          account_id: accountId,
          channel_connected: connected,
          business_number: businessNumber,
          business_name: businessName,
          model: api.runtime.agent.defaults.model,
          gateway_version: gatewayVersion
        });
      } catch (error) {
        api.logger.warn(`SAHJONY heartbeat failed: ${error instanceof Error ? error.message : "unknown error"}`);
      }
    }

    async function acknowledge(command, status, providerMessageId, error) {
      await signedRequest("/whatsapp/openclaw/outbox/ack", "POST", {
        command_id: command.command_id,
        lease_token: command.lease_token,
        status,
        provider_message_id: providerMessageId,
        error: error?.slice(0, 1e3)
      });
    }

    async function pollOutbox() {
      if (stopped || polling) return;
      polling = true;
      try {
        const response = await signedRequest("/whatsapp/openclaw/outbox?limit=10", "GET");
        const data = await response.json();
        for (const command of data.commands || []) {
          try {
            const sent = await api.runtime.system.runCommandWithTimeout(openclawBin, [
              "message", "send", "--channel", "whatsapp", "--account", command.account_id || accountId,
              "--target", command.recipient, "--message", command.body, "--json"
            ], { timeoutMs: 45e3 });
            if (sent.code !== 0) throw new Error(String(sent.stderr || `OpenClaw exited with ${sent.code}`).slice(0, 1e3));
            let messageId;
            try {
              const parsed = JSON.parse(String(sent.stdout || "{}"));
              messageId = String(parsed.messageId || parsed.message_id || "") || void 0;
            } catch {
              messageId = void 0;
            }
            await acknowledge(command, "sent", messageId);
          } catch (error) {
            await acknowledge(command, "failed", void 0, error instanceof Error ? error.message : "OpenClaw send failed");
          }
        }
      } catch (error) {
        api.logger.warn(`SAHJONY outbox poll failed: ${error instanceof Error ? error.message : "unknown error"}`);
      } finally {
        polling = false;
      }
    }

    api.on("message_received", async (event, ctx) => {
      if (ctx.channel !== "whatsapp" && ctx.messageProvider !== "whatsapp") return;
      await postEvent({
        event_id: String(event.messageId || ctx.messageId || crypto.randomUUID()),
        direction: "inbound",
        message_id: event.messageId || ctx.messageId,
        sender_id: event.senderId || ctx.senderId,
        thread_id: event.threadId,
        contact_name: typeof event.metadata?.senderName === "string" ? event.metadata.senderName : void 0,
        content: String(event.content || "").slice(0, 4096),
        message_type: Array.isArray(event.media) && event.media.length ? "media" : "text",
        account_id: accountId,
        timestamp: new Date().toISOString(),
        media: compactMedia(event.media)
      });
    });

    api.on("message_sent", async (event, ctx) => {
      if (ctx.channel !== "whatsapp" && ctx.messageProvider !== "whatsapp") return;
      await postEvent({
        event_id: `sent:${String(event.messageId || ctx.messageId || crypto.randomUUID())}`,
        direction: "outbound",
        message_id: event.messageId || ctx.messageId,
        recipient_id: event.to || ctx.channelId,
        thread_id: event.threadId,
        content: String(event.content || "").slice(0, 4096),
        message_type: "text",
        account_id: accountId,
        status: event.success === false ? "failed" : "sent",
        timestamp: new Date().toISOString()
      });
    });

    api.on("gateway_start", async () => {
      stopped = false;
      await heartbeat();
      await pollOutbox();
      heartbeatTimer = setInterval(() => { void heartbeat(); }, 12e4);
      pollTimer = setInterval(() => { void pollOutbox(); }, pollIntervalMs);
      api.logger.info(`SAHJONY application bridge started (gatewayId=${gatewayId}, openclawBin=${openclawBin})`);
    });

    api.on("gateway_stop", async () => {
      stopped = true;
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      if (pollTimer) clearInterval(pollTimer);
      api.logger.info("SAHJONY application bridge stopped");
    });
  }
});
export { index_default as default };
