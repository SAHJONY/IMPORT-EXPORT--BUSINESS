# WhatsApp 24x7

## Purpose
Maintain SAHJONY LLC WhatsApp availability continuously using the authorized **Hostinger + Docker + OpenClaw** runtime and its retained **WhatsApp Linked Device** session. Meta Cloud and Vercel are optional supporting systems; neither is part of the local production readiness chain.

Never bypass WhatsApp account verification, device-link restrictions, QR authorization, phone-number linking authorization, 2FA, rate limits, Hostinger authentication, access controls, or provider policy.

## Production authority
The production dependency chain is:

`Hostinger VPS -> Kali -> Docker -> existing OpenClaw container -> authorized WhatsApp Linked Device session`

Evidence priority:
1. Authenticated Hostinger OS inspection.
2. Docker container state and local `openclaw channels status --probe`.
3. `/var/lib/sahjony-whatsapp-guardian/status.json` and fresh `last-good`.
4. Active Hostinger guardian timer.
5. Signed Hostinger heartbeat, when the application/backend is reachable.
6. `/whatsapp/health` only as secondary observation.

Never infer Hostinger health from Vercel deployment state. Never mark WhatsApp unavailable solely because Meta, Vercel, the public API, a heartbeat endpoint, or a database is temporarily degraded.

## Primary operator tool
Use the local orchestrator first whenever normal Hostinger SSH works:

```bash
/usr/local/sbin/sahjony-whatsapp-orchestrator status
/usr/local/sbin/sahjony-whatsapp-orchestrator repair
/usr/local/sbin/sahjony-whatsapp-orchestrator verify
```

Source:
`openclaw/hostinger-24x7/whatsapp-24x7-orchestrator.sh`

The orchestrator is idempotent and non-destructive. It may start Docker, start the retained OpenClaw container, enforce a persistent Docker restart policy, and perform at most one cooldown-governed restart of that same container. It never deletes/recreates containers or volumes, never logs WhatsApp out, never generates a QR, and never forces device linking.

It writes machine-readable state to:

`/var/lib/sahjony-whatsapp-guardian/status.json`

### Orchestrator states
- `READY` — Hostinger Docker/OpenClaw is running, WhatsApp is locally connected, restart policy is persistent, and the guardian timer is active when verification requires it.
- `DOCKER_UNAVAILABLE` — Docker is not installed; do not fabricate a replacement runtime.
- `DOCKER_DOWN` — Docker exists but the daemon is unavailable after the permitted local repair.
- `CONTAINER_MISSING` — no existing OpenClaw container was found; refuse automatic recreation because that could lose the durable session.
- `CONTAINER_STOPPED` — retained OpenClaw container could not be started.
- `PAIRING_REQUIRED` — infrastructure is running but an authorized Linked Device session is missing, expired, revoked, or explicitly requires login. Stop infrastructure restart loops and move to the pairing controller.
- `CHANNEL_DEGRADED` — OpenClaw is running but WhatsApp is not ready and the probe does not positively identify an authorization requirement. One cooldown-governed restart is permitted.
- `DEGRADED_RESTART_POLICY` — channel is connected but Docker persistence is not configured.
- `DEGRADED_GUARDIAN` — channel is connected but the systemd guardian timer is inactive.

## State machine

### 1. Audit before changing anything
Run:

```bash
/usr/local/sbin/sahjony-whatsapp-orchestrator status
```

If `READY`, do not pair or restart again.

If the orchestrator is not installed yet, use the pairing controller audit as supporting evidence:

```bash
/usr/local/sbin/sahjony-whatsapp-pairing-controller audit
```

### 2. Local repair before infrastructure recovery
When authenticated Hostinger SSH works:

```bash
/usr/local/sbin/sahjony-whatsapp-orchestrator repair
```

This is the preferred self-healing path. It repairs only reversible runtime state and preserves the linked-device session.

The persistent guardian remains:

```bash
/usr/local/sbin/sahjony-whatsapp-guardian
```

with a systemd timer. Local WhatsApp health is authoritative. Heartbeat/public-health publication is best effort and must never turn a healthy local channel into a failed guardian run.

### 3. Treat `PAIRING_REQUIRED` separately from infrastructure failure
Pairing is an authorization operation, not a server-healing operation. If the orchestrator reports `PAIRING_REQUIRED`, do not dispatch repeated VPS recoveries or container restarts.

Use:

```bash
/usr/local/sbin/sahjony-whatsapp-pairing-controller audit
```

If WhatsApp shows **“Can’t link new devices right now. Try again later.”**, record a local safety backoff:

```bash
/usr/local/sbin/sahjony-whatsapp-pairing-controller mark-client-lock 21600
```

The six-hour value is a local anti-loop safety interval, not a claim about WhatsApp’s provider-side lock duration.

During a provider/device-link lock:
- do not call `web.login.start` repeatedly;
- do not use forced pairing;
- do not delete OpenClaw auth/session volumes;
- do not log out working linked devices;
- do not recreate the OpenClaw container merely to obtain another QR;
- do not rotate the business phone number;
- do not attempt to circumvent WhatsApp security or rate controls.

### 4. Pair once only when authorization is actually required and allowed
Use the canonical workflow:

`Hostinger WhatsApp Pair Live`

Choose `pair_once`. It must:
- require normal authenticated Hostinger SSH;
- install/use the lock-aware pairing controller;
- refuse to run during local pairing cooldown;
- start exactly one non-forced OpenClaw WhatsApp login;
- publish only one QR artifact;
- wait once for authorization;
- arm a backoff if pairing is not completed;
- never generate a second forced QR;
- finalize the 24x7 guardian only after a positive local channel probe.

The native WhatsApp **Link with phone number instead** path may be used when WhatsApp itself offers it and permits linking. It is an alternate authorized linking method, not a bypass for an active provider lock.

### 5. Hostinger Recovery V7 only when normal SSH/runtime control is unavailable
Use **Hostinger WhatsApp Recovery V7** only for host-level failure that cannot be repaired through authenticated normal SSH.

Infrastructure recovery and WhatsApp authorization are separate failure domains. V7 may repair Kali/SSH/Docker/OpenClaw, but it must not fabricate WhatsApp authorization or bypass device linking.

V7 must:
- serialize Hostinger VPS mutations;
- reconcile recent Hostinger actions before starting another action;
- authenticate Recovery SSH;
- repair original Kali SSH without erasing application state;
- leave Recovery and wait for the Hostinger action to finish;
- use at most one bounded official VPS restart if needed;
- stabilize the retained Docker/OpenClaw runtime;
- install the Hostinger-only guardian/tooling;
- verify the local WhatsApp probe if an authorized session already exists;
- surface `PAIRING_REQUIRED` if authorization has expired.

### 6. Public app / Meta / backend failures do not trigger destructive WhatsApp recovery
A failed or stale:
- Vercel deployment,
- `/whatsapp/health`,
- Hostinger heartbeat POST,
- Meta Cloud field,
- public API gateway,
- or database connection

is not evidence that the Hostinger Linked Device session is down. Observe and repair those systems independently. The local Hostinger probe remains authoritative for WhatsApp transport readiness.

### 7. Anti-loop policy
- One infrastructure recovery at a time.
- One WhatsApp pairing attempt at a time.
- No forced QR refresh loop.
- Pairing minimum interval: 30 minutes by default.
- Failed pairing backoff: 60 minutes by default.
- Client-side device-link lock safety backoff: 6 hours by default.
- Container restart cooldown: 5 minutes by default.
- Never erase OpenClaw state or create a replacement container merely to solve connectivity.
- Never restart a healthy OpenClaw container because Vercel, Meta, or another unrelated cloud service is degraded.

## Acceptance
Do not report `READY` until Hostinger OpenClaw is verified locally ready.
Require:
- normal Hostinger OS booted;
- Docker active;
- existing OpenClaw container running;
- persistent Docker restart policy (`unless-stopped` or `always`);
- local `openclaw channels status --probe` shows WhatsApp connected/ready;
- Hostinger guardian timer active;
- fresh local `last-good` and/or orchestrator `status.json`;
- production remains functional with the local iMac offline.

Public heartbeat and `/whatsapp/health` should be repaired and reconciled, but they are not allowed to override a positive local readiness result.

If the durable WhatsApp session expires or WhatsApp explicitly requires device re-linking, surface that as `PAIRING_REQUIRED`. Software must not fabricate or bypass that authorization.

## Operator tools
- `openclaw/hostinger-24x7/whatsapp-24x7-orchestrator.sh`
- `openclaw/hostinger-24x7/whatsapp-pairing-controller.sh`
- `openclaw/hostinger-24x7/whatsapp-guardian.sh`
- `openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh`
- `openclaw/hostinger-24x7/install-whatsapp-guardian.sh`
- `openclaw/hostinger-24x7/whatsapp-24x7-control-plane.sh`
- `.github/workflows/hostinger-whatsapp-pair-live.yml`
- `.github/workflows/hostinger-whatsapp-recovery-v7.yml`
- `.github/workflows/whatsapp-24x7-control-plane.yml`
- `.github/workflows/whatsapp-24x7-lint.yml`
