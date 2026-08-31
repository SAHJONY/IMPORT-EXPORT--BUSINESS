# SAHJONY OpenClaw Application Bridge

This trusted plugin synchronizes the WhatsApp Business account connected to OpenClaw with the SAHJONY production application.

It provides:

- signed inbound and outbound event delivery to the CRM;
- a bounded owner-governed outbound queue;
- gateway heartbeats for truthful health reporting;
- no application, filesystem, shell, browser, or owner-route access for public WhatsApp users.

Required environment variables on the OpenClaw gateway host:

```bash
SAHJONY_APP_URL=https://www.sahjony.com
SAHJONY_APP_BRIDGE_SECRET=<same secret configured in Vercel>
```

## Recommended macOS installation

Run this from the repository on the Mac that hosts the OpenClaw gateway:

```bash
bash openclaw/sahjony-app-bridge/install-macos.sh
```

The installer generates a fresh bridge secret locally, stores it with mode `600`
in `~/.openclaw/.env`, saves the same value in Vercel as a sensitive Production
variable, installs the reviewed local plugin, enables the trusted WhatsApp event
hook, validates and restarts OpenClaw, and redeploys the current Production build.
It never prints the secret.

Required OpenClaw configuration:

```json5
{
  channels: {
    whatsapp: {
      accounts: {
        default: {
          pluginHooks: { messageReceived: true },
        },
      },
    },
  },
  plugins: {
    entries: {
      "sahjony-app-bridge": {
        enabled: true,
        config: {
          appUrl: "https://www.sahjony.com",
          accountId: "default",
          businessNumber: "+12816628581",
          businessName: "SAHJONY LLC",
          pollIntervalMs: 30000,
        },
      },
    },
  },
}
```

After installing the plugin on the gateway host, restart OpenClaw and verify both surfaces:

```bash
openclaw plugins inspect sahjony-app-bridge --runtime --json
openclaw gateway restart
openclaw channels status --probe
curl -sS https://www.sahjony.com/whatsapp/health
```
