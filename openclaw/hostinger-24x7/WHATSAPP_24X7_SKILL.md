# SAHJONY WhatsApp 24/7 Recovery Skill

## Mission
Keep SAHJONY LLC WhatsApp communications available 24/7 using the strongest authorized transport that is actually healthy:

1. **Meta Cloud API** — preferred primary transport when official Meta credentials, webhook, WABA and Phone Number ID are complete.
2. **Hostinger OpenClaw** — persistent 24/7 agent runtime and WhatsApp fallback.
3. **Local/iMac** — cold standby only; never required for production uptime.

This skill automates legitimate recovery. It must **never bypass** Meta verification, WhatsApp pairing, 2FA, Hostinger authentication, provider access controls, consent rules, or platform policy.

## Truth hierarchy
When signals conflict, use this order:

1. Direct authenticated Hostinger inspection.
2. Docker/OpenClaw channel probe on Hostinger.
3. Fresh Hostinger-specific gateway heartbeat (`gateway_id=hostinger-vps`).
4. Public `https://www.sahjony.com/whatsapp/health`.
5. Generic `gateway_connected` or older heartbeat fields.

Vercel deployment state is not Hostinger runtime evidence.

## State machine

### A. Meta Cloud independently ready
Treat Meta as production primary when health proves cloud send + webhook readiness (`cloud_independent_of_local_mac=true`, or equivalent explicit Meta fields). Keep Hostinger OpenClaw healthy as fallback, but do not place the VPS into Recovery merely because the fallback is degraded while Meta is fully operational.

### B. Hostinger SSH reachable and authenticated
Run:

```bash
sudo bash openclaw/hostinger-24x7/whatsapp-24x7-guardian.sh install
```

The guardian must:
- find the existing OpenClaw container; never install a duplicate blindly;
- set Docker restart policy to `unless-stopped`;
- start a stopped container;
- probe `openclaw channels status --probe`;
- allow at most one restart per cooldown window;
- preserve OpenClaw state/pairing;
- keep watchdog and backup timers active;
- install its own two-minute guardian timer;
- report public and local health separately.

Do **not** run `openclaw gateway restart` blindly inside Docker. Prefer host-level Docker lifecycle control.

### C. SSH TCP open but authentication fails
Do not keep retrying arbitrary keys. Use the reviewed Hostinger Recovery workflow with an ephemeral credential and repair the original OS from Recovery mode.

### D. SSH TCP closed/unreachable
Use the reviewed Recovery workflow only after confirming no Recovery workflow is already active and the cooldown permits another attempt.

The Recovery workflow must be symmetric:

```text
POST /recovery
  -> capture action_id
  -> wait action.state=success
  -> authenticate Recovery SSH
  -> identify original OS disk
  -> install ephemeral public key
  -> validate sshd config with sshd -t
  -> enable ssh.service/sshd.service
DELETE /recovery
  -> capture stop action_id
  -> wait stop action.state=success
  -> wait for normal TCP/22
  -> authenticate normal Kali SSH
  -> stabilize Docker/OpenClaw
  -> install 24/7 guardian
  -> verify WhatsApp
  -> remove ephemeral access
```

Never treat an HTTP 2xx response from Hostinger as proof that an asynchronous VPS action has completed.

## Anti-loop rules
- One Hostinger Recovery at a time.
- Recovery cooldown: at least 90 minutes unless an authorized operator explicitly forces it.
- Local container restart cooldown: at least 5 minutes.
- Never restart a healthy local OpenClaw container solely because Vercel, Meta Cloud, or another cloud dependency is degraded.
- Never erase OpenClaw durable state to solve a connectivity problem.
- Never replace an existing OpenClaw instance unless there is explicit evidence the instance is unrecoverable.

## Control-plane commands
Audit only:

```bash
MODE=audit bash openclaw/hostinger-24x7/whatsapp-24x7-control-plane.sh
```

Safe heal over existing SSH:

```bash
MODE=heal bash openclaw/hostinger-24x7/whatsapp-24x7-control-plane.sh
```

Dispatch reviewed Recovery when local healing is impossible:

```bash
MODE=recover bash openclaw/hostinger-24x7/whatsapp-24x7-control-plane.sh
```

Strict acceptance verification:

```bash
MODE=verify bash openclaw/hostinger-24x7/whatsapp-24x7-control-plane.sh
```

## GitHub control plane
Workflow:

```text
.github/workflows/whatsapp-24x7-control-plane.yml
```

It runs every 15 minutes in safe healing mode and can be manually invoked as `audit`, `heal`, `recover`, or `verify`.

Scheduled runs do **not** perform disk Recovery by default. To authorize autonomous Recovery after local healing becomes impossible, set repository variable:

```text
SAHJONY_AUTO_RECOVERY=true
```

The control plane still enforces active-run detection and Recovery cooldown.

## Acceptance gates
Do not call WhatsApp 24/7 complete until all applicable gates pass:

```text
At least one production transport ready: Meta Cloud OR Hostinger OpenClaw
Hostinger VPS normal OS reachable
Docker service active
Existing OpenClaw container running
Restart policy = unless-stopped or always
OpenClaw WhatsApp channel probe connected/ready
SAHJONY app bridge enabled
Gateway ID = hostinger-vps
Fresh Hostinger-specific heartbeat
Watchdog timer active
Backup timer active
WhatsApp 24/7 guardian timer active
No duplicate Recovery run active
Public health accurately reflects the transport state
24-hour test succeeds with iMac offline
```

## Meta activation blockers
Software cannot legitimately fabricate or bypass these requirements. If Meta Cloud is not ready, surface the exact missing requirement instead of claiming activation:

- Meta App ID / App Secret
- WhatsApp Business Account (WABA) ID
- Phone Number ID
- valid access token with required permissions
- webhook verify token
- webhook subscription/verification
- supported Graph API version
- business/phone verification where Meta requires it

Until those are complete, Hostinger OpenClaw can provide the 24/7 runtime path, provided its WhatsApp session remains valid and its durable state is preserved.
