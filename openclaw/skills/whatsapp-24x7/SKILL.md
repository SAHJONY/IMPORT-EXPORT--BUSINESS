# WhatsApp 24x7

## Purpose
Maintain SAHJONY LLC WhatsApp availability continuously using the authorized **Hostinger + Docker + OpenClaw** runtime. Meta Cloud is not controlled and is not part of the production dependency chain.

Never bypass WhatsApp account verification, QR/device pairing, 2FA, Hostinger authentication, access controls, or provider policy.

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
5. Generic public gateway fields only as supporting evidence.

Never infer Hostinger health from Vercel deployment state. Never mark WhatsApp READY because of Meta fields.

## State machine

### 1. Audit Hostinger OpenClaw
Check `https://www.sahjony.com/whatsapp/health`, but treat direct Hostinger evidence as authoritative.

Hostinger is ready only when `hostinger_independent_runtime=true`, `hostinger_openclaw.connected=true`, or direct authenticated inspection proves the WhatsApp channel is connected.

### 2. Prefer safe local healing
If Hostinger SSH is authenticated, install/run:

```bash
/opt/sahjony-openclaw/whatsapp-hostinger-only-guardian.sh install
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

### 3. Recovery only when normal SSH cannot heal the runtime
Use `Hostinger WhatsApp 24x7 Recovery V6` when Hostinger WhatsApp is not ready and normal Hostinger SSH cannot be used.

Recovery must:
- prevent concurrent V5/V6 recovery by shared concurrency lock;
- POST Recovery and wait for its Hostinger action ID to reach `success`;
- authenticate Recovery SSH;
- locate the original OS disk;
- install an ephemeral SSH key;
- validate `sshd -t` in the original OS;
- DELETE Recovery and wait for its stop action ID to reach `success`;
- authenticate the normal OS;
- stabilize the existing Docker/OpenClaw container;
- persist/install the Hostinger-only guardian before removing ephemeral access;
- verify WhatsApp locally and through Hostinger-specific public health;
- clean up ephemeral access.

### 4. Anti-loop policy
- One recovery at a time.
- V6 cooldown: 90 minutes after a completed V6 unless an authorized operator explicitly forces it.
- Container restart cooldown: 5 minutes.
- A failed legacy V5 does not block the first V6 remediation.
- Never erase OpenClaw state or create a replacement container merely to solve connectivity.
- Never restart a healthy OpenClaw container because Vercel or another unrelated cloud service is degraded.

## Acceptance
Do not report `READY` until Hostinger OpenClaw is verified ready.
Require:
- normal Hostinger OS booted;
- Docker active;
- existing OpenClaw container running;
- persistent restart policy;
- `openclaw channels status --probe` shows WhatsApp connected/ready;
- Hostinger-only guardian timer active;
- fresh Hostinger-specific heartbeat or equivalent direct evidence;
- production continues with the local iMac offline.

If the durable WhatsApp session expires or WhatsApp explicitly requires device re-linking, surface that as a pairing requirement. Software must not fabricate or bypass that authorization.

## Operator tools
- `openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh`
- `openclaw/hostinger-24x7/whatsapp-24x7-control-plane.sh`
- `.github/workflows/whatsapp-24x7-control-plane.yml`
- `.github/workflows/hostinger-whatsapp-24x7-recovery-v6.yml`
- `.github/workflows/whatsapp-24x7-lint.yml`
