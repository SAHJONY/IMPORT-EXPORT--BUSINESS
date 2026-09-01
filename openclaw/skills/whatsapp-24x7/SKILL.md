# WhatsApp 24x7

## Purpose
Maintain SAHJONY LLC WhatsApp availability continuously using authorized Meta Cloud and Hostinger OpenClaw transports. Never bypass account verification, pairing, 2FA, access controls, or provider policy.

## Use this skill when
- WhatsApp is disconnected, degraded, stale, or not sending/receiving.
- Hostinger OpenClaw needs health verification or safe restart.
- The local Mac/iMac must not be required for production uptime.
- A recovery workflow is stuck or repeated recoveries must be prevented.

## Evidence priority
1. Authenticated Hostinger OS inspection.
2. Docker container state and `openclaw channels status --probe` on Hostinger.
3. Fresh `hostinger-vps` heartbeat.
4. `/whatsapp/health` Hostinger-specific fields.
5. Generic public gateway fields.

Never infer Hostinger health from Vercel deployment state.

## State machine

### 1. Audit transports
Check `https://www.sahjony.com/whatsapp/health`.

Meta primary is ready only when explicit Meta send + webhook readiness is true.
Hostinger fallback is ready only when the `hostinger-vps` gateway is fresh/connected or direct local evidence confirms the channel.

### 2. Prefer safe local healing
If Hostinger SSH is authenticated, run the persistent guardian installer:

```bash
/opt/sahjony-openclaw/whatsapp-24x7-guardian.sh install
```

The guardian:
- uses an exclusive lock;
- finds the existing OpenClaw container rather than creating a duplicate;
- enforces `unless-stopped` restart policy;
- starts stopped Docker/OpenClaw services;
- probes the WhatsApp channel;
- permits at most one container restart per cooldown;
- installs a two-minute systemd timer;
- retains pairing and durable state.

### 3. Recovery only when local healing is unavailable
Use `Hostinger WhatsApp 24x7 Recovery V6` only when neither Meta nor Hostinger is verified ready and normal Hostinger SSH cannot be used.

V6 must:
- prevent concurrent V5/V6 recovery by shared concurrency lock;
- POST Recovery and wait for its action ID to reach `success`;
- authenticate Recovery SSH;
- locate the original OS disk;
- install an ephemeral SSH key;
- validate `sshd -t` in the original OS;
- DELETE Recovery and wait for its stop action ID to reach `success`;
- authenticate the normal OS;
- stabilize the existing Docker/OpenClaw container;
- persist/install the guardian before removing the ephemeral key;
- verify WhatsApp locally and through public health;
- clean up ephemeral access.

### 4. Anti-loop policy
- One recovery at a time.
- V6 cooldown: 90 minutes after a completed V6 unless an authorized operator explicitly forces it.
- Container restart cooldown: 5 minutes.
- A failed legacy V5 does not block the first V6 remediation.
- Never erase OpenClaw state or create a replacement container merely to solve connectivity.

## Acceptance
Do not report `READY` until at least one production transport is verified ready.
For Hostinger readiness, require:
- normal OS booted;
- Docker active;
- existing OpenClaw container running;
- persistent restart policy;
- WhatsApp channel probe connected/ready;
- guardian timer active;
- fresh Hostinger-specific heartbeat or equivalent direct evidence.

For full cloud-primary readiness, Meta must also have the official WABA/Phone Number IDs, access token, app secret, webhook verify token, webhook subscription, and supported Graph API version configured.

## Operator tools
- `openclaw/hostinger-24x7/whatsapp-24x7-guardian.sh`
- `openclaw/hostinger-24x7/whatsapp-24x7-control-plane.sh`
- `.github/workflows/whatsapp-24x7-control-plane.yml`
- `.github/workflows/hostinger-whatsapp-24x7-recovery-v6.yml`
