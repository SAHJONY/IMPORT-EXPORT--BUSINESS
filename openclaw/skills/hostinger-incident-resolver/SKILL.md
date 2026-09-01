# SAHJONY Hostinger Incident Resolver Skill

## Purpose

Use this skill when the SAHJONY Hostinger VPS, Kali SSH, Docker, OpenClaw, or the WhatsApp Linked Device runtime is degraded and the exact failure is not yet known.

The resolver is designed to bypass unsupported or dead-end infrastructure paths, not security controls. It never bypasses Hostinger authentication, SSH authentication, WhatsApp pairing, MFA, or provider authorization.

## Authoritative production path

`Hostinger VPS → Kali → native ssh.service → local Docker → retained OpenClaw runtime → authorized WhatsApp Linked Device session → SAHJONY app/API`

The following are not production dependencies:

- Hostinger Docker Manager on this Kali VPS. It is unsupported and diagnostic-only.
- Meta Cloud. It is optional and must not block the Hostinger/OpenClaw transport.
- The owner's iMac.

## Primary tool

`openclaw/hostinger-24x7/hostinger-incident-resolver.sh`

Modes:

- `diagnose` — read-only classification of the current incident.
- `solve` — waits for a stable Hostinger action plane, exhausts the safer provider-side SSH key path, then invokes the canonical recovery controller only when necessary.

## What the resolver fixes

The resolver removes the recurring orchestration failures that caused earlier recovery attempts to collide or choose an unsupported path:

1. Hostinger Docker Manager is treated as non-authoritative and may be skipped completely.
2. Nonterminal Hostinger actions are drained to a stable idle state before a mutation is attempted.
3. Transient Hostinger HTTP 408/409/425/429/5xx responses are retried with bounded backoff.
4. HTTP 401/403 is treated as a credential/permission failure and is never bypassed.
5. Normal SSH is used first when it authenticates.
6. Provider-side stable SSH key reconciliation is attempted before disk Recovery.
7. The canonical controller owns all Recovery, reboot, SSH repair, Docker restoration, and OpenClaw lifecycle mutations.
8. OpenClaw is reconstructed only when the retained-runtime forensic planner proves exactly one safe retained candidate.
9. The existing WhatsApp Linked Device state is preserved. The resolver never logs out or automatically re-pairs WhatsApp.
10. Meta Cloud does not participate in readiness or recovery decisions.

## Incident classes

The resolver emits one of these principal classes:

- `READY` — SSH, local Docker, exactly one OpenClaw runtime, and the WhatsApp/OpenClaw probe are healthy.
- `SSH_TRANSPORT_DOWN` — TCP/22 is unavailable.
- `SSH_KEY_UNAVAILABLE` — the runner has no durable SSH private key; Recovery may still seed an ephemeral management identity.
- `SSH_AUTH_FAILED` — TCP/22 is reachable but the configured key does not authenticate.
- `DOCKER_MISSING` — normal SSH works but Docker is not installed/present.
- `DOCKER_INACTIVE` — Docker exists but the daemon is not active.
- `OPENCLAW_CONTAINER_MISSING` — Docker is healthy but current metadata has no OpenClaw container.
- `OPENCLAW_CONTAINER_AMBIGUOUS` — multiple possible OpenClaw containers exist; automatic guessing is forbidden.
- `OPENCLAW_CLASSIFICATION_FAILED` — Docker metadata could not be classified safely.
- `OPENCLAW_OR_WHATSAPP_UNHEALTHY` — one retained OpenClaw container exists but the local readiness probe is not healthy.

## Solve algorithm

1. Classify the current failure.
2. If already `READY`, perform no mutation.
3. Query Hostinger's action plane and wait until it is idle for two consecutive samples.
4. Run `hostinger-provider-ssh-preflight.sh` to reconcile the already-authorized stable key when available.
5. Re-check the action plane before the canonical controller runs.
6. Invoke `hostinger-recovery-controller.sh full` with the retained-runtime reconstruction gate enabled.
7. The controller uses normal SSH when possible; otherwise it creates one owned Recovery session, repairs native Kali SSH, exits only the Recovery session it owns, and permits at most one bounded VPS restart after targeted SSH repair.
8. Restore local Docker only when retained Docker/OpenClaw evidence exists.
9. Reuse the existing OpenClaw container when one unambiguous container exists.
10. If no container exists, reconstruct only when exactly one evidence-backed retained compose candidate is proven.
11. Apply persistent Docker restart policy and the Hostinger-only guardian.
12. Re-run local OpenClaw/WhatsApp readiness classification.
13. Declare success only when the final class is `READY`.

## Safety rules

- Never use Hostinger Docker Manager as a required fallback on Kali.
- Never start a second Recovery while a Hostinger action is nonterminal.
- Never run multiple Hostinger mutation workflows concurrently.
- Never disable Hostinger firewall or authentication controls.
- Never create a second SSH daemon on port 22.
- Never create a fresh OpenClaw runtime without retained-state evidence.
- Never choose between multiple OpenClaw candidates automatically.
- Never use `openclaw gateway restart` as infrastructure recovery.
- Never log out or re-pair the WhatsApp Linked Device automatically.
- Never claim 24/7 readiness from Vercel/public health alone; Hostinger-local readiness is authoritative.

## Workflow

Manual entrypoint:

`.github/workflows/hostinger-incident-resolver.yml`

Use `mode=diagnose` for a read-only report. Use `mode=solve` with `confirm_mutation=RESOLVE` to allow the bounded recovery sequence.

## Expected success marker

`SAHJONY_HOSTINGER_INCIDENT_RESOLVER=READY`

A successful run must also emit a final incident report with `incident_class: READY`.
