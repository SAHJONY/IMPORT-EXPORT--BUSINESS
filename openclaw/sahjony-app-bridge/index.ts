import crypto from "node:crypto";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

type BridgeConfig = {
  appUrl?: string;
  accountId?: string;
  businessNumber?: string;
  businessName?: string;
  pollIntervalMs?: number;
};

type OutboxCommand = {
  command_id: string;
  account_id: string;
  recipient: string;
  body: string;
  lease_token: string;
};

function compactMedia(media: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(media)) return [];
  return media.slice(0, 20).map((item) => {
    const fact = item && typeof item === "object" ? item as Record<string, unknown> : {};
    return {
      kind: typeof fact.kind === "string" ? fact.kind : undefined,
      contentType: typeof fact.contentType === "string" ? fact.contentType : undefined,
      transcribed: Boolean(fact.transcribed),
      messageId: typeof fact.messageId === "string" ? fact.messageId : undefined,
    };
  });
}

export default definePluginEntry({
  id: "sahjony-app-bridge",
  name: "SAHJONY Application Bridge",
  description: "Trusted WhatsApp-to-CRM bridge for SAHJONY LLC.",
  register(api) {
    const config = (api.pluginConfig ?? {}) as BridgeConfig;
    const appUrl = String(config.appUrl || process.env.SAHJONY_APP_URL || "https://www.sahjony.com").replace(/\/$/, "");
    const secret = String(process.env.SAHJONY_APP_BRIDGE_SECRET || "");
    const accountId = String(config.accountId || "default");
    const pollIntervalMs = Math.max(5_000, Math.min(300_000, Number(config.pollIntervalMs || 30_000)));
    let stopped = false;
    let polling = false;
    let pollTimer: ReturnType<typeof setInterval> | undefined;
    let heartbeatTimer: ReturnType<typeof setInterval> | undefined;

    if (secret.length < 24) {
      api.logger.error("SAHJONY_APP_BRIDGE_SECRET must contain at least 24 characters; bridge disabled");
      return;
    }

    async function signedRequest(path: string, method: "GET" | "POST", payload?: unknown): Promise<Response> {
      const body = payload === undefined ? "" : JSON.stringify(payload);
      const timestamp = String(Math.floor(Date.now() / 1000));
      const signature = "sha256=" + crypto.createHmac("sha256", secret).update(`${timestamp}.${body}`).digest("hex");
      const response = await fetch(`${appUrl}${path}`, {
        method,
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
          "X-SAHJONY-Timestamp": timestamp,
          "X-SAHJONY-Signature": signature,
        },
        body: method === "POST" ? body : undefined,
        signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) {
        throw new Error(`SAHJONY bridge HTTP ${response.status}`);
      }
      return response;
    }

    async function postEvent(payload: Record<string, unknown>): Promise<void> {
      try {
        await signedRequest("/whatsapp/openclaw/events", "POST", payload);
      } catch (error) {
        api.logger.warn(`SAHJONY event synchronization failed: ${error instanceof Error ? error.message : "unknown error"}`);
      }
    }

    async function heartbeat(): Promise<void> {
      let connected = false;
      let gatewayVersion: string | undefined;
      try {
        const probe = await api.runtime.system.runCommandWithTimeout(
          "openclaw",
          ["channels", "status", "--probe"],
          { timeoutMs: 20_000 },
        );
        const output = `${probe.stdout || ""}\n${probe.stderr || ""}`;
        connected = /whatsapp[\s\S]{0,240}\bconnected\b/i.test(output) || /\blinked,\s*running,\s*connected\b/i.test(output);
        const version = await api.runtime.system.runCommandWithTimeout("openclaw", ["--version"], { timeoutMs: 10_000 });
        gatewayVersion = String(version.stdout || "").trim().slice(0, 80) || undefined;
      } catch {
        connected = false;
      }
      try {
        await signedRequest("/whatsapp/openclaw/heartbeat", "POST", {
          gateway_id: "default",
          account_id: accountId,
          channel_connected: connected,
          business_number: config.businessNumber || "+12816628581",
          business_name: config.businessName || "SAHJONY LLC",
          model: api.runtime.agent.defaults.model,
          gateway_version: gatewayVersion,
        });
      } catch (error) {
        api.logger.warn(`SAHJONY heartbeat failed: ${error instanceof Error ? error.message : "unknown error"}`);
      }
    }

    async function acknowledge(command: OutboxCommand, status: "sent" | "failed", providerMessageId?: string, error?: string): Promise<void> {
      await signedRequest("/whatsapp/openclaw/outbox/ack", "POST", {
        command_id: command.command_id,
        lease_token: command.lease_token,
        status,
        provider_message_id: providerMessageId,
        error: error?.slice(0, 1000),
      });
    }

    async function pollOutbox(): Promise<void> {
      if (stopped || polling) return;
      polling = true;
      try {
        const response = await signedRequest("/whatsapp/openclaw/outbox?limit=10", "GET");
        const data = await response.json() as { commands?: OutboxCommand[] };
        for (const command of data.commands || []) {
          try {
            const sent = await api.runtime.system.runCommandWithTimeout(
              "openclaw",
              [
                "message", "send",
                "--channel", "whatsapp",
                "--account", command.account_id || accountId,
                "--target", command.recipient,
                "--message", command.body,
                "--json",
              ],
              { timeoutMs: 45_000 },
            );
            if (sent.code !== 0) {
              throw new Error(String(sent.stderr || `OpenClaw exited with ${sent.code}`).slice(0, 1000));
            }
            let messageId: string | undefined;
            try {
              const parsed = JSON.parse(String(sent.stdout || "{}")) as Record<string, unknown>;
              messageId = String(parsed.messageId || parsed.message_id || "") || undefined;
            } catch {
              messageId = undefined;
            }
            await acknowledge(command, "sent", messageId);
          } catch (error) {
            await acknowledge(command, "failed", undefined, error instanceof Error ? error.message : "OpenClaw send failed");
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
        contact_name: typeof event.metadata?.senderName === "string" ? event.metadata.senderName : undefined,
        content: String(event.content || "").slice(0, 4096),
        message_type: Array.isArray(event.media) && event.media.length ? "media" : "text",
        account_id: accountId,
        timestamp: new Date().toISOString(),
        media: compactMedia(event.media),
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
        timestamp: new Date().toISOString(),
      });
    });

    api.on("gateway_start", async () => {
      stopped = false;
      await heartbeat();
      await pollOutbox();
      heartbeatTimer = setInterval(() => { void heartbeat(); }, 120_000);
      pollTimer = setInterval(() => { void pollOutbox(); }, pollIntervalMs);
      api.logger.info("SAHJONY application bridge started");
    });

    api.on("gateway_stop", async () => {
      stopped = true;
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      if (pollTimer) clearInterval(pollTimer);
      api.logger.info("SAHJONY application bridge stopped");
    });
  },
});
