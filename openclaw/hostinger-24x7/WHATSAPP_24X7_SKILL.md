# SAHJONY WhatsApp 24/7 Recovery Skill

## Objective
Keep the authorized SAHJONY WhatsApp transport available continuously using Hostinger as the durable OpenClaw runtime, while treating Meta Cloud API as the preferred long-term transport.

## Non-negotiable rules
- Never bypass WhatsApp/Meta authentication, verification, opt-out, rate-limit, anti-spam, or account-integrity controls.
- Never treat Vercel health as proof that Hostinger is down.
- Hostinger-local Docker/OpenClaw probes are authoritative for Hostinger runtime health.
- Use host-level `docker restart`; do not use `openclaw gateway restart` inside Docker for recovery.
- Do not start a second Hostinger Recovery operation while one is active.
- Persist Docker restart policy as `unless-stopped`.

## Recovery ladder
1. Check Hostinger TCP/22 and authenticated SSH.
2. If SSH works: inspect Docker; do not enter Recovery mode.
3. If Docker is stopped: enable/start Docker.
4. Discover existing OpenClaw containers by name/image; never create a replacement until discovery is exhausted.
5. Set restart policy `unless-stopped`, start container, run `openclaw channels status --probe` inside it.
6. If WhatsApp probe fails: restart the OpenClaw container once at host level and re-probe.
7. If SSH is unavailable but VPS is running: use Hostinger Recovery API.
8. For both POST and DELETE `/recovery`, capture the returned action ID and poll `/actions/{actionId}` until `state=success` before proceeding.
9. In Recovery, use documented `/mnt` first; otherwise discover Linux root. Validate `sshd -t`, install ephemeral key, enable ssh/sshd service.
10. Exit Recovery, wait for exit action success, then wait for authenticated normal SSH.
11. Stabilize Docker/OpenClaw, install the guardian timer, and verify local WhatsApp probe.
12. Public `/whatsapp/health` is secondary evidence; reconcile it after local runtime is READY.

## 24/7 guardian gates
PASS only when all are true:
- Docker service active.
- Existing OpenClaw container running.
- Restart policy is persistent.
- `openclaw channels status --probe` indicates WhatsApp connected/ready.
- `sahjony-whatsapp-guardian.timer` active.
- Last-good timestamp is fresh.

## Meta Cloud primary path
For true infrastructure independence, configure the official WhatsApp Cloud API with WABA ID, Phone Number ID, access token, webhook verification token, App Secret, and supported Graph API version. Hostinger OpenClaw then remains AI/workforce/fallback rather than the sole transport.

## Escalation
Do not attempt to circumvent a provider rejection. Surface the exact provider/API error and required authorized remediation.
