# Hostinger OpenClaw Authorization Recovery

Purpose: restore a 24/7 OpenClaw control path using only credentials/connections that SAHJONY has already authorized. This design never bypasses Hostinger, SSH, GitHub, MFA, or account security.

## Recovery order

1. Probe SAHJONY production health. If gateway is healthy, stop.
2. Detect an existing OpenClaw runtime on the current Hostinger host and run the non-destructive bootstrap.
3. Detect an existing Hostinger/OpenClaw connector and preserve/use connector-native authorization.
4. Detect an existing local SSH identity without exposing its contents. Require an explicit known Hostinger host/user before remote execution.
5. If none exists, return `WAITING_FOR_AUTHORIZATION`; do not fabricate credentials or weaken authentication.

## 24/7 target

- Hostinger: persistent OpenClaw gateway/runtime
- Docker/systemd: restart + watchdog
- GitHub: source of truth and repair workflows
- Vercel: SAHJONY web/API layer
- Supabase: durable CRM/memory/state
- Meta Cloud: primary WhatsApp transport
- OpenClaw: agent runtime/fallback transport

## Success gates

- `gateway_connected=true`
- heartbeat fresh
- watchdog active
- daily backup successful
- SAHJONY app bridge healthy
- dashboard protected by TLS and authentication
- iMac may remain powered off without affecting the cloud runtime

## Security invariant

Recovery may discover and reuse an existing authorized connection. It must never print private keys/tokens, bypass MFA, disable authentication, create guessed credentials, or expose the gateway directly to the public Internet without TLS/authentication.
