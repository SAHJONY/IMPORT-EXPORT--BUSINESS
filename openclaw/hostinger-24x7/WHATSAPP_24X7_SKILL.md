# SAHJONY WhatsApp 24/7 Recovery Skill

## Mission
Keep SAHJONY LLC WhatsApp communications available 24/7 with **Hostinger OpenClaw as the production primary transport**.

Production order:

1. **Hostinger VPS + Docker + OpenClaw + authorized WhatsApp Linked Device session** — primary transport.
2. **SAHJONY app/API + durable backend** — business logic, state, heartbeat, queues and governance.
3. **Local/iMac** — cold standby only; never required for production uptime.
4. **Meta Cloud API** — optional future transport only. It is not required for present production readiness and must never block or downgrade a healthy Hostinger OpenClaw runtime.

This skill automates legitimate infrastructure recovery. It must **never bypass** WhatsApp pairing, 2FA, account verification, Hostinger authentication, provider access controls, consent rules, anti-spam controls, or platform policy.

## Truth hierarchy
When signals conflict, use this order:

1. Direct authenticated Hostinger inspection.
2. Docker/OpenClaw channel probe on Hostinger.
3. Fresh Hostinger-specific gateway heartbeat (`gateway_id=hostinger-vps`).
4. Public `https://www.sahjony.com/whatsapp/health`.
5. Generic gateway/legacy heartbeat fields.
6. Meta Cloud fields are informational only while Meta is not configured/controlled.

Vercel deployment state is not Hostinger runtime evidence. Meta configuration state is not Hostinger runtime evidence.

## Primary state machine

### A. Hostinger SSH reachable and authenticated
Run the Hostinger guardian/control plane.

The guardian must:
- find the existing OpenClaw container; never install a duplicate blindly;
- preserve the authorized WhatsApp Linked Device session and durable OpenClaw state;
- set Docker restart policy to `unless-stopped`;
- start a stopped container;
- probe `openclaw channels status --probe`;
- allow at most one restart per cooldown window;
- use host-level Docker lifecycle control instead of blindly running `openclaw gateway restart` inside Docker;
- keep watchdog and backup timers active;
- keep the WhatsApp guardian timer active;
- report Hostinger-local readiness independently from Vercel/Meta.

### B. SSH TCP open but authentication fails
Do not keep retrying arbitrary keys. Use the reviewed Hostinger Recovery workflow with an ephemeral credential and repair the original OS from Recovery mode.

### C. SSH TCP closed/unreachable
Use the reviewed bounded Recovery workflow only after confirming no Recovery workflow is already active and the cooldown permits another attempt.

The Recovery workflow must be symmetric:

```text
POST /recovery
  -> capture action_id
  -> wait action.state=success
  -> authenticate Recovery SSH
  -> identify original OS disk
  -> install ephemeral public key
  -> generate host keys if needed
  -> validate sshd config with sshd -t
  -> enable ssh.service/sshd.service
DELETE /recovery
  -> capture stop action_id
  -> wait stop action.state=success
  -> wait for normal TCP/22
  -> authenticate normal Kali SSH
  -> if still unavailable, perform at most one official Hostinger VM restart
  -> capture restart action_id and wait state=success
  -> authenticate normal Kali SSH again
  -> stabilize Docker/OpenClaw
  -> install 24/7 guardian
  -> verify WhatsApp Linked Device channel locally
  -> remove ephemeral access
```

Never treat an HTTP 2xx response from Hostinger as proof that an asynchronous VPS action has completed.

## Anti-loop rules
- One Hostinger Recovery at a time.
- Recovery cooldown: at least 90 minutes unless an authorized operator explicitly forces it.
- At most one VM restart per bounded Recovery run.
- Local container restart cooldown: at least 5 minutes.
- Never restart a healthy local OpenClaw container solely because Vercel or Meta is degraded.
- Never erase OpenClaw/WhatsApp durable state to solve a connectivity problem.
- Never replace an existing OpenClaw instance until discovery/recovery proves it unrecoverable.
- Never log out/re-pair WhatsApp automatically. Pairing is an authorization event and must be preserved.

## GitHub recovery path
Preferred bounded recovery workflow:

```text
.github/workflows/hostinger-whatsapp-recovery-v6.yml
```

V6 performs:

```text
Hostinger Recovery start action
-> authenticated Recovery SSH
-> original Kali repair + sshd validation
-> Recovery stop action
-> normal SSH probe
-> one bounded Hostinger VM restart if required
-> Docker/OpenClaw stabilization
-> guardian installation
-> local WhatsApp readiness verification
-> ephemeral access cleanup
```

## Acceptance gates
Do not call WhatsApp 24/7 complete until these Hostinger/OpenClaw gates pass:

```text
Hostinger VPS normal OS reachable
Docker service active
Existing OpenClaw container running
Restart policy = unless-stopped or always
OpenClaw WhatsApp Linked Device channel probe connected/ready
SAHJONY app bridge enabled
Gateway ID = hostinger-vps
Fresh Hostinger-specific heartbeat
Watchdog timer active
Backup timer active
WhatsApp guardian timer active
No duplicate Recovery run active
Public health accurately reflects Hostinger primary state
24-hour test succeeds with iMac offline
```

## Meta Cloud status
Meta Cloud is **not part of the present critical path**. Missing Meta App/WABA/Phone Number ID/token/webhook credentials must not set Hostinger/OpenClaw production status to failed.

If Meta is added later, treat it as an additional official transport/failover path. Do not claim it is configured until its official credentials and verification pass. Do not attempt to fabricate or bypass those requirements.
