# SAHJONY WhatsApp 24/7 Recovery Skill

## Mission
Keep SAHJONY LLC WhatsApp communications available 24/7 with **Hostinger OpenClaw as the production primary transport**.

Production order:
1. Hostinger VPS + Docker + OpenClaw + authorized WhatsApp Linked Device session.
2. SAHJONY app/API + durable backend.
3. Local/iMac as cold standby only.
4. Meta Cloud API as optional future transport only.

Never bypass WhatsApp pairing, 2FA, Hostinger authentication, provider controls, consent, anti-spam, or platform policy. Never erase or re-pair an authorized WhatsApp session as a recovery shortcut.

## Truth hierarchy
1. Direct authenticated Hostinger inspection.
2. Docker/OpenClaw channel probe on Hostinger.
3. Fresh Hostinger-specific heartbeat (`gateway_id=hostinger-vps`).
4. Public `https://www.sahjony.com/whatsapp/health`.
5. Generic/legacy heartbeat fields.
6. Meta fields are informational while Meta is not controlled.

Vercel deployment state and Meta configuration are not Hostinger runtime evidence.

## Canonical recovery engine
Use the current targeted workflow:

```text
.github/workflows/hostinger-kali-ssh-repair-v8.yml
```

Provider action decisions must use:

```text
openclaw/hostinger-24x7/provider-recovery-adaptive.sh
```

The adaptive helper reconciles the Hostinger action plane before mutation, waits for asynchronous actions, and performs bounded retry/backoff for transient provider responses such as 403/409/422/423/429/5xx. A provider rejection is never bypassed; the engine waits/reconciles and fails closed when the response is non-transient.

Runtime forensics/reconstruction uses:

```text
openclaw/hostinger-24x7/openclaw-runtime-recovery.sh
```

Reconstruction is allowed only when retained durable state and an unambiguous runtime definition are proven. Never create a blind duplicate OpenClaw instance.

## State machine
### A. Normal SSH authenticates
Run the guardian/control plane. Discover the existing OpenClaw container, preserve state, set restart policy `unless-stopped`, start if stopped, and run `openclaw channels status --probe`.

### B. TCP/22 open but authentication fails
Use V8 with an ephemeral Recovery credential to repair the original Kali SSH configuration and seed only authorized SSH identity.

### C. TCP/22 closed/unreachable
First reconcile the Hostinger action plane. Start one owned Recovery session only when idle. Wait for the Recovery action to reach success before attempting Recovery SSH.

Canonical sequence:
```text
provider diagnose/wait-idle
-> POST /recovery with bounded transient retry
-> capture action_id
-> wait action.state=success
-> authenticate Recovery SSH
-> identify original Kali root
-> seed ephemeral/durable authorized key
-> generate host keys if needed
-> validate sshd with sshd -t
-> enable ssh.service/sshd.service
-> DELETE /recovery
-> wait stop action.state=success
-> authenticate normal Kali SSH
-> stabilize Docker/OpenClaw
-> install guardian
-> local WhatsApp probe
-> remove ephemeral access
```

Never treat HTTP 2xx as proof that an asynchronous Hostinger action completed.

## Anti-loop rules
- One Hostinger mutation workflow at a time (`hostinger-vm-767852-mutation`).
- One Recovery session at a time.
- Do not stack disk Recovery requests to work around 403/409/provider locks.
- At most one bounded VM restart in a recovery sequence.
- Container restart cooldown at least 5 minutes.
- Never restart healthy OpenClaw because Vercel or Meta is degraded.
- Never erase durable OpenClaw/WhatsApp state.
- Never auto logout/re-pair WhatsApp.

## Acceptance gates
Do not call WhatsApp 24/7 complete until all pass:
```text
Hostinger normal Kali reachable/authenticated
Docker active
Existing/recovered OpenClaw runtime running
Restart policy = unless-stopped or always
WhatsApp Linked Device channel probe connected/ready
SAHJONY app bridge enabled
Gateway ID = hostinger-vps
Fresh Hostinger-specific heartbeat
Watchdog timer active
Backup timer active
WhatsApp guardian timer active
No duplicate Recovery active
Public health reflects Hostinger primary state
24-hour test succeeds with iMac offline
```

## Meta Cloud
Meta Cloud is not in the present critical path. Missing Meta credentials must not downgrade a healthy Hostinger/OpenClaw runtime. If added later, it remains an official optional transport/failover and must pass its own provider verification.
