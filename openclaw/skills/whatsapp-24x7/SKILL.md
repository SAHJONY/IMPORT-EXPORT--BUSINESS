# WhatsApp 24x7

## Purpose
Maintain SAHJONY LLC WhatsApp availability continuously using the authorized **Hostinger + Docker + OpenClaw** runtime. Meta Cloud is optional and is not part of the production dependency chain.

Never bypass WhatsApp account verification, device-link restrictions, QR authorization, phone-number linking authorization, 2FA, rate limits, Hostinger authentication, access controls, or provider policy.

## Use this skill when
- WhatsApp is disconnected, degraded, stale, or not sending/receiving.
- Hostinger OpenClaw needs health verification or a safe restart.
- WhatsApp displays **“Can’t link new devices right now. Try again later.”**
- A QR is generated but the phone refuses device linking.
- Repeated pairing attempts must be stopped before they worsen a provider-side lock.
- The local Mac/iMac must not be required for production uptime.

## Evidence priority
1. Authenticated Hostinger OS inspection.
2. Docker container state and `openclaw channels status --probe` on Hostinger.
3. Fresh `hostinger-vps` heartbeat.
4. `/whatsapp/health` Hostinger-specific fields.
5. Generic public gateway fields only as supporting evidence.

Never infer Hostinger health from Vercel deployment state. Never mark WhatsApp READY because of Meta fields.

## State machine

### 1. Audit before changing anything
Run the local pairing controller on Hostinger:

```bash
/usr/local/sbin/sahjony-whatsapp-pairing-controller audit
```

If WhatsApp is already connected, do not pair again. Preserve the retained session and arm the guardian.

### 2. Treat “Can’t link new devices right now” as a provider-side authorization lock
This error is not solved by generating more QR codes. When the phone shows the lock:

```bash
/usr/local/sbin/sahjony-whatsapp-pairing-controller mark-client-lock 21600
```

The six-hour value is a **local safety backoff**, not a claim about WhatsApp’s actual lock duration. It prevents SAHJONY automation from repeatedly requesting new pairings while WhatsApp is refusing them. The backoff can be extended by an authorized operator.

During this state:
- do not call `web.login.start` repeatedly;
- do not use `force:true`;
- do not delete OpenClaw auth/session volumes;
- do not log out working linked devices;
- do not recreate the OpenClaw container merely to obtain another QR;
- do not rotate the business phone number;
- do not attempt to circumvent WhatsApp security/rate controls.

On the phone, the authorized operator should leave the account intact, keep WhatsApp current, verify the device has normal network access and automatic date/time, and review WhatsApp **Linked Devices** for stale or unrecognized entries. The native **Link with phone number instead** option may be used after the provider allows new linking again; it is an alternate authorization method, not a bypass for an active lock.

### 3. Pair once after cooldown
Use the canonical workflow:

`Hostinger WhatsApp Pair Live`

Choose `pair_once`. It:
- requires normal authenticated Hostinger SSH;
- installs the lock-aware pairing controller;
- refuses to run during a local safety cooldown;
- starts exactly one non-forced OpenClaw WhatsApp login;
- publishes only one QR artifact;
- waits once for authorization;
- arms a backoff if pairing is not completed;
- never generates a second forced QR;
- finalizes the 24x7 guardian only after a positive channel probe.

If the phone again displays “Can’t link new devices right now,” stop the pairing attempt and run the same workflow with `mark_client_lock` instead of requesting another QR.

### 4. Prefer safe local healing after connection
When Hostinger SSH is authenticated, install/run:

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
- installs a persistent systemd timer;
- retains pairing and durable state.

### 5. Hostinger recovery only when normal SSH is unavailable
Use the canonical **Hostinger WhatsApp Recovery V7** path when the VPS cannot be managed through normal authenticated SSH.

Infrastructure recovery and WhatsApp pairing are separate failure domains. V7 may repair the Hostinger/Kali/SSH/Docker/OpenClaw runtime, but it must not fabricate WhatsApp authorization or bypass device linking.

V7 recovery must:
- serialize Hostinger VPS mutations;
- reconcile recent Hostinger actions before starting another action;
- authenticate Recovery SSH;
- repair original Kali SSH without erasing application state;
- leave Recovery and wait for the action to finish;
- use at most one bounded official VPS restart if needed;
- stabilize the retained Docker/OpenClaw runtime;
- install the Hostinger-only guardian;
- verify the local WhatsApp probe if an authorized session already exists;
- surface `PAIRING_REQUIRED` if authorization has expired.

### 6. Anti-loop policy
- One infrastructure recovery at a time.
- One WhatsApp pairing attempt at a time.
- No forced QR refresh loop.
- Pairing minimum interval: 30 minutes by default.
- Failed pairing backoff: 60 minutes by default.
- Client-side device-link lock safety backoff: 6 hours by default.
- Container restart cooldown remains independent from pairing cooldown.
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
- `openclaw/hostinger-24x7/whatsapp-pairing-controller.sh`
- `openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh`
- `openclaw/hostinger-24x7/whatsapp-24x7-control-plane.sh`
- `.github/workflows/hostinger-whatsapp-pair-live.yml`
- `.github/workflows/hostinger-whatsapp-recovery-v7.yml`
- `.github/workflows/whatsapp-24x7-control-plane.yml`
- `.github/workflows/whatsapp-24x7-lint.yml`
