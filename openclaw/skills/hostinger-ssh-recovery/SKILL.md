# Hostinger SSH Recovery Skill

## Purpose

Repair and stabilize the SAHJONY Hostinger VPS management path without destroying the existing Kali system, Docker state, OpenClaw runtime state, or WhatsApp Linked Device session.

This skill is intentionally conservative: diagnose first, mutate only the failing layer, serialize every Hostinger mutation, and verify from the VPS itself before declaring readiness.

## Canonical VPS

- VM ID: `767852`
- IPv4: `69.62.68.67`
- OS: Kali Linux
- SSH user: `root`
- Hostinger API base: `https://developers.hostinger.com`

## Non-negotiable invariants

1. Never run two Recovery/restart/key-attachment mutations at the same time.
2. Use GitHub Actions concurrency group `hostinger-vm-767852-mutation` with `cancel-in-progress: false`.
3. Never recreate or reinstall the VPS as a recovery shortcut.
4. Never delete/recreate OpenClaw blindly.
5. Preserve retained OpenClaw state and the authorized WhatsApp Linked Device session.
6. Never use Vercel health as proof of Hostinger-local readiness.
7. Hostinger Docker Manager is not a supported control path for this Kali VPS.
8. Meta Cloud is optional and must not block Hostinger/OpenClaw WhatsApp readiness.
9. Never interpret shell exit `141` from a bounded `find|head` discovery pipeline as lost runtime state. The runtime-forensics tool must use SIGPIPE-safe bounded scans.

## Failure classifier

Classify the current failure before choosing a repair path:

- `SSH_READY`: TCP/22 open and authenticated SSH succeeds. Do not enter Recovery. Stabilize Docker/OpenClaw and install the guardian.
- `SSH_AUTH_REJECTED`: TCP/22 open but SSH returns `Permission denied (publickey)`. Network and provider firewall are working; repair `authorized_keys` and sshd policy.
- `SSH_NETWORK_DOWN`: TCP/22 closed/filtered. Check Hostinger VM state, action plane, and network firewall. Do not assume OpenClaw is the cause.
- `ACTION_PLANE_BUSY`: a Hostinger action is nonterminal. Wait; never stack Recovery/restart operations.
- `RECOVERY_PASSWORD_REJECTED`: Hostinger returns validation error. Regenerate a policy-compliant password containing lowercase, uppercase, digit, and a literal symbol, then retry only after confirming no Recovery action started.
- `RECOVERY_SSH_READY`: Recovery mode authenticated successfully. Repair the mounted original Kali filesystem only.
- `KALI_REPAIRED`: normal Kali accepts the seeded ephemeral key after Recovery exit.
- `OPENCLAW_CONTAINER_MISSING`: Docker is healthy but current Docker metadata has no OpenClaw-like container. Do not re-enter Recovery. Run retained-state forensics and the runtime resolver.
- `OPENCLAW_FORENSICS_NO_SAFE_CANDIDATE`: no single evidence-backed reconstruction candidate exists. Stop destructive automation and preserve the forensic report.
- `OPENCLAW_FORENSICS_AMBIGUOUS`: more than one existing/high-confidence candidate exists. Stop automatic reconstruction.
- `OPENCLAW_READY`: exactly one OpenClaw container is running with restart policy `unless-stopped` or `always` and channel probe succeeds.
- `WHATSAPP_24X7_READY`: guardian timer active plus fresh `last-good` plus local runtime marker `SAHJONY_HOSTINGER_LOCAL_RUNTIME=READY`.

## Repair ladder

### Layer 1 — Normal SSH

Probe TCP/22 and attempt the known management key if one exists. If authenticated, skip all provider repair and go directly to Docker/OpenClaw stabilization.

### Layer 2 — Hostinger public-key attachment

The Hostinger API supports account public-key creation and attachment. Treat this as an inexpensive diagnostic/bootstrap attempt, not as authoritative proof that Kali accepted the key.

Required validation after attach:

1. Confirm the API accepted the request.
2. Confirm the key is attached at the Hostinger control plane.
3. Attempt real SSH authentication.
4. If SSH still returns `Permission denied (publickey)`, classify `SSH_AUTH_REJECTED` and move to targeted Recovery.

Important: deleting a Hostinger account public-key record does not remove a key already installed on a VPS. One-time SAHJONY keys must therefore also be removed directly from Kali `authorized_keys` when normal SSH becomes available.

### Layer 3 — Targeted Recovery key seed

Use Recovery only when normal SSH authentication is blocked and no Hostinger action is active.

Inside Recovery:

1. Locate the original Kali root (`/mnt`, `/mnt/sdb1`, or discovered mounted filesystem).
2. Back up the current root `authorized_keys` before modifying it.
3. Remove only dead SAHJONY one-time key comments.
4. Add the current ephemeral public key.
5. Set `/root/.ssh` mode 700 and `authorized_keys` mode 600 with root ownership.
6. Install one authoritative sshd drop-in with public-key auth enabled and password auth disabled.
7. Ensure native `ssh.service`/`sshd.service` is enabled.
8. Run `sshd -t` inside the chroot.
9. Install the persistent SAHJONY native SSH self-heal timer.
10. Sync filesystem writes.

Then exit Recovery and wait for Recovery-stop success before probing normal SSH.

### Layer 4 — OpenClaw runtime resolution

Use this layer after authenticated normal SSH. Never re-enter disk Recovery merely because the OpenClaw container is absent from Docker metadata.

Canonical tools:

- `openclaw/hostinger-24x7/openclaw-runtime-recovery.sh`
- `openclaw/hostinger-24x7/openclaw-runtime-resolver.sh`

Procedure:

1. Verify Docker exists and `docker.service` is active.
2. Discover existing OpenClaw-like containers by container name/image.
3. If exactly one exists, preserve it, set restart policy `unless-stopped`, start if stopped, and probe the channel.
4. If no container exists, run the read-only runtime audit and plan.
5. The planner scores retained compose/docker-run artifacts using OpenClaw references, WhatsApp/session references, restart policy, retained host state, and real non-empty bind sources.
6. Automatic reconstruction is permitted only when exactly one high-confidence candidate exists and its retained bind sources still exist immediately before `docker compose up`.
7. Reconstruction uses the retained compose definition with `--no-build`; it never creates a synthetic replacement configuration from guesses.
8. After reconstruction, require exactly one OpenClaw-like container, persistent restart policy, and a successful `openclaw channels status --probe`.
9. If the planner returns no candidate or multiple candidates, preserve the reports under `/var/lib/sahjony-openclaw-recovery` and stop automatic reconstruction.
10. Exit `141` is classified as a runtime-forensics implementation regression, not as missing data. The current planner isolates bounded `head` pipelines from global `pipefail` so this condition does not abort a valid scan.

### Layer 5 — WhatsApp 24/7 guardian

Only after OpenClaw runtime resolution succeeds:

1. Install/enable `sahjony-whatsapp-guardian.timer`.
2. Run the guardian immediately.
3. Verify channel probe locally.
4. Verify a fresh `/var/lib/sahjony-whatsapp-guardian/last-good`.
5. Verify restart policy remains `unless-stopped` or `always`.
6. Emit `SAHJONY_HOSTINGER_LOCAL_RUNTIME=READY` only after all local gates pass.

## Stop conditions

Stop and report instead of escalating when:

- Hostinger action plane is busy.
- Recovery cannot authenticate with the generated Recovery credential.
- The original Kali root cannot be identified unambiguously.
- `sshd -t` fails.
- Docker is missing from the original VPS.
- More than one OpenClaw-like container is present.
- Runtime forensics finds no safe reconstruction candidate.
- Runtime forensics finds multiple high-confidence candidates.
- The WhatsApp channel requires re-pairing. Never auto-logout or auto-pair a different account.

## Authoritative evidence order

1. Authenticated normal SSH into the Kali VPS.
2. Local Docker/OpenClaw state and local OpenClaw channel probe.
3. Guardian timer and fresh `last-good` marker.
4. Hostinger VM/action/firewall API.
5. Public SAHJONY `/whatsapp/health` endpoint only as secondary evidence.

## Repository tools

- `openclaw/hostinger-24x7/hostinger-recovery-controller.sh`
- `openclaw/hostinger-24x7/hostinger-recovery-preflight.sh`
- `openclaw/hostinger-24x7/provider-recovery-adaptive.sh`
- `openclaw/hostinger-24x7/hostinger-provider-ssh-preflight.sh`
- `openclaw/hostinger-24x7/openclaw-runtime-recovery.sh`
- `openclaw/hostinger-24x7/openclaw-runtime-resolver.sh`
- `openclaw/hostinger-24x7/provider-bootstrap-stabilize.sh`
- `openclaw/hostinger-24x7/whatsapp-guardian.sh`
- `openclaw/hostinger-24x7/install-whatsapp-guardian.sh`

## Acceptance gate

Do not state that WhatsApp is active 24/7 until all are true:

- normal Kali SSH authenticated
- Docker active
- exactly one preserved or evidence-reconstructed OpenClaw container running
- restart policy persistent
- OpenClaw WhatsApp channel probe healthy
- guardian timer enabled and active
- fresh guardian `last-good`
- `SAHJONY_HOSTINGER_LOCAL_RUNTIME=READY`
