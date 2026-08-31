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
hook, installs OpenClaw as a macOS `launchd` service, validates and restarts the
gateway, and redeploys the current Production build. It also prevents system
sleep while the Mac is connected to power, while preserving normal battery
sleep and display locking. It never prints the secret.

The plugin intentionally reads its dedicated bridge secret and sends signed
events only to the configured SAHJONY application URL. The installer acknowledges
that reviewed install-policy warning for this plugin only; it does not weaken or
disable OpenClaw's global plugin security policy.

OpenClaw `2026.4.9` detects the reviewed pattern but does not support granular
CLI acknowledgement. When the existing Node runtime is supported, the installer
first uses the official `openclaw update` stable-channel flow. If the existing
runtime is too old (including Hermes Node `22.22.2`), it uses OpenClaw's official
rootless `install-cli.sh` flow to install a supported Node and CLI under
`~/.openclaw`. That installer verifies the downloaded Node archive with SHA-256.
The bridge installer then replaces the managed `launchd` service definition with
the new runtime while preserving the existing state and WhatsApp pairing.

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
