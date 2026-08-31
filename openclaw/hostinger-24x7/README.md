# SAHJONY OpenClaw — Hostinger 24/7 Production Host

This directory converts an **existing Hostinger OpenClaw installation** into the always-on SAHJONY gateway without replacing the instance that is already running.

## Target architecture

```text
iPhone / Owner
      |
      v
HTTPS OpenClaw Dashboard (Hostinger)
      |
      v
OpenClaw Gateway 24/7
  |       |       |
  |       |       +--> model providers / skills
  |       +----------> WhatsApp fallback / channels
  +------------------> SAHJONY signed application bridge
                         |
                         v
                    Vercel app
                         |
                         v
                    Supabase CRM
```

Vercel remains the web/API layer. Supabase remains the durable business data layer. Hostinger becomes the persistent OpenClaw runtime. The iMac is no longer required for uptime.

## Supported Hostinger modes

### A. Existing Hostinger VPS + Docker OpenClaw — preferred for maximum control

Hostinger documents OpenClaw deployment through VPS → Docker Manager → Catalog. The bootstrap in this directory detects the existing OpenClaw container and does **not** install a second copy.

Run on the VPS:

```bash
sudo bash openclaw/hostinger-24x7/bootstrap-existing-openclaw.sh
```

It performs the following safe operations:

- discovers the existing OpenClaw container by name/image;
- preserves the existing OpenClaw state and pairing;
- pulls the current SAHJONY repository into `/opt/sahjony-openclaw/repo`;
- installs/enables the reviewed `sahjony-app-bridge` plugin when the OpenClaw CLI is available;
- writes the dedicated bridge environment into the OpenClaw state directory with restrictive permissions;
- sets Docker restart policy to `unless-stopped`;
- installs a two-minute systemd watchdog;
- restarts a locally unhealthy OpenClaw container with a five-minute anti-loop cooldown;
- checks the SAHJONY production health endpoint without restarting a healthy local gateway merely because cloud configuration is degraded;
- creates a daily durable-state backup and keeps 14 days of backups;
- optionally synchronizes the bridge secret to Vercel when a valid `VERCEL_TOKEN` is supplied at runtime;
- restarts OpenClaw and reports local/cloud health.

The bootstrap never prints the bridge secret.

### B. Hostinger Managed OpenClaw

Do not install a second Docker OpenClaw. Hostinger Managed OpenClaw is already an always-on hosted runtime. In OpenClaw Settings, connect the **Hostinger Connector**. Hostinger documents that this registers its API MCP server and allows OpenClaw to work with Hostinger resources. The SAHJONY bridge still needs to be installed/configured through the capabilities exposed by that managed runtime.

## HTTPS for iPhone access

After DNS for a hostname points to the VPS:

```bash
sudo OPENCLAW_DOMAIN=openclaw.example.com \
     LETSENCRYPT_EMAIL=admin@example.com \
     bash openclaw/hostinger-24x7/configure-https.sh
```

This installs Nginx + Let's Encrypt, enables WebSocket proxying, redirects HTTP to HTTPS, and keeps OpenClaw's gateway token as the authentication layer.

Do not expose the gateway token in GitHub, screenshots, chat, or source code.

## GitHub Actions remote deployment

Workflow:

```text
.github/workflows/hostinger-openclaw-24x7.yml
```

It is manual (`workflow_dispatch`) so it cannot unexpectedly modify the VPS on every application commit.

Expected GitHub Actions secrets:

```text
HOSTINGER_SSH_HOST
HOSTINGER_SSH_USER
HOSTINGER_SSH_PRIVATE_KEY
VERCEL_TOKEN                    # optional for bridge-secret synchronization
VERCEL_SCOPE                    # optional; defaults to the current SAHJONY scope
OPENCLAW_HOSTINGER_DOMAIN       # only for HTTPS step
LETSENCRYPT_EMAIL               # only for HTTPS step
```

No secret belongs in repository files.

## Recovery model

1. Docker `unless-stopped` handles process/server restarts.
2. systemd watchdog checks the container every two minutes.
3. One restart is allowed only after a five-minute cooldown to prevent restart loops.
4. Daily OpenClaw state backups are retained for 14 days.
5. Vercel/Supabase remain independent of Hostinger.
6. Meta Cloud WhatsApp is intended to be the primary transport once its official credentials are configured; Hostinger OpenClaw remains a persistent agent runtime and channel fallback.
7. The iMac can remain a cold/standby fallback and is not required for production uptime.

## Acceptance gates

Do not call the migration complete until all are true:

```text
Hostinger OpenClaw container/state: running
Docker restart policy: unless-stopped
Watchdog timer: active
Backup timer: active
HTTPS dashboard: reachable from iPhone
OpenClaw gateway authentication: required
sahjony-app-bridge: enabled
https://www.sahjony.com/whatsapp/health: gateway/cloud status truthful
24-hour test with iMac off: passed
```

## Important limitation

The repository can prepare and automate the server configuration, but the first connection to the actual Hostinger account/VPS requires either:

- an existing Hostinger-managed OpenClaw instance reachable through its dashboard, or
- SSH access to the Hostinger VPS supplied securely to GitHub Actions/runtime.

Passwords, gateway tokens, private SSH keys, Meta tokens and provider API keys must never be committed to GitHub.
