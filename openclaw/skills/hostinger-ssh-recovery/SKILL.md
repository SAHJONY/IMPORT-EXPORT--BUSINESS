# Hostinger SSH Recovery Skill

## Purpose

Repair and stabilize the SAHJONY Hostinger VPS management path without destroying the existing Kali system, Docker state, OpenClaw container, or WhatsApp Linked Device session.

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
4. Never delete/recreate the OpenClaw container blindly.
5. Preserve OpenClaw volumes and the authorized WhatsApp Linked Device session.
6. Never use Vercel health as proof of Hostinger-local readiness.
7. Hostinger Docker Manager is not a supported control path for this Kali VPS.
8. Meta Cloud is optional and must not block Hostinger/OpenClaw WhatsApp readiness.

## Failure classifier

Classify the current failure before choosing a repair path:

- `SSH_READY`: TCP/22 open and authenticated SSH succeeds. Do not enter Recovery. Stabilize Docker/OpenClaw and install the guardian.
- `SSH_AUTH_REJECTED`: TCP/22 open but SSH returns `Permission denied (publickey)`. Network and provider firewall are working; repair `authorized_keys` and sshd policy.
- `SSH_NETWORK_DOWN`: TCP/22 closed/filtered. Check Hostinger VM state, action plane, and network firewall. Do not assume OpenClaw is the cause.
- `ACTION_PLANE_BUSY`: a Hostinger action is nonterminal. Wait; never stack Recovery/restart operations.
- `RECOVERY_PASSWORD_REJECTED`: Hostinger returns validation error. Regenerate a policy-compliant password containing lowercase, uppercase, digit, and a literal symbol, then retry only after confirming no Recovery action started.
- `RECOVERY_SSH_READY`: Recovery mode authenticated successfully. Repair the mounted original Kali filesystem only.
- `KALI_REPAIRED`: normal Kali accepts the seeded ephemeral key after Recovery exit.
- `OPENCLAW_READY`: existing OpenClaw container is running with restart policy `unless-stopped` or `always` and channel probe succeeds.
- `WHATSAPP_24X7_READY`: guardian timer active plus fresh `last-good` plus local runtime marker `SAHJONY_HOSTINGER_LOCAL_RUNTIME=READY`.

## Repair ladder

### Layer 1 — Normal SSH

Probe TCP/22 and attempt the known management key if one exists. If authenticated, skip all provider repair and go directly to Docker/OpenClaw stabilization.

### Layer 2 — Hostinger public-key attachment

The Hostinger API supports account public-key creation and attachment. Treat this as an inexpensive diagnostic/bootstrap attempt, not as authoritative proof that Kali accepted the key.

Required validation after attach:

1. Confirm the API returned HTTP 200.
2. Query `/api/vps/v1/virtual-machines/{VM_ID}/public-keys` to confirm the key is attached at the Hostinger control plane.
3. Attempt real SSH authentication.
4. If SSH still returns `Permission denied (publickey)`, classify `SSH_AUTH_REJECTED` and move to targeted Recovery.

Important: deleting a Hostinger account public-key record does not remove a key already installed on a VPS. One-time SAHJONY keys must therefore also be removed directly from Kali `authorized_keys` when normal SSH becomes available.

### Layer 3 — Targeted Recovery key seed

Use Recovery only when normal SSH authentication is blocked and no Hostinger action is active.

Recovery password requirements:

- at least one uppercase letter
- at least one lowercase letter
- at least one digit
- at least one literal symbol

Use the repository tool to generate/validate the password. Do not hand-compose a password that can accidentally omit the symbol class.

Inside Recovery:

1. Locate the original Kali root (`/mnt`, `/mnt/sdb1`, or discovered mounted filesystem).
2. Back up the current root `authorized_keys` before modifying it.
3. Remove only dead SAHJONY one-time key comments (`sahjony-v7-*`, `sahjony-v8-*`, `sahjony-provider-bootstrap-*`).
4. Add the current ephemeral public key.
5. Set `/root/.ssh` mode 700 and `authorized_keys` mode 600 with root ownership.
6. Install one authoritative sshd drop-in:
   - `PubkeyAuthentication yes`
   - `PermitRootLogin prohibit-password`
   - `PasswordAuthentication no`
   - `KbdInteractiveAuthentication no`
   - `AuthorizedKeysFile .ssh/authorized_keys`
7. Ensure `ssh.service` or `sshd.service` is enabled.
8. Run `sshd -t` inside the chroot.
9. Record `sshd -T` values for `permitrootlogin`, `pubkeyauthentication`, `passwordauthentication`, and `authorizedkeysfile`.
10. Sync filesystem writes.

Then exit Recovery and wait for the Recovery-stop action to finish before probing normal SSH.

### Layer 4 — Existing OpenClaw stabilization

After authenticated normal SSH:

1. Verify Docker exists and is active.
2. Discover existing containers whose name/image contains `openclaw|claw`.
3. Never replace those containers automatically.
4. Apply `docker update --restart unless-stopped`.
5. Start a stopped existing container.
6. Run the OpenClaw channel probe.
7. Install/enable `sahjony-whatsapp-guardian.timer`.
8. Verify a fresh `last-good` timestamp and local READY marker.

## Stop conditions

Stop and report instead of escalating when:

- Hostinger action plane is busy.
- Recovery cannot authenticate with the generated Recovery credential.
- The original Kali root cannot be identified unambiguously.
- `sshd -t` fails.
- Docker is missing from the original VPS.
- No pre-existing OpenClaw container can be identified.
- The WhatsApp channel requires re-pairing. Never auto-logout or auto-pair a different account.

## Authoritative evidence order

1. Authenticated normal SSH into the Kali VPS.
2. Local Docker/OpenClaw state and local OpenClaw channel probe.
3. Guardian timer and fresh `last-good` marker.
4. Hostinger VM/action/firewall API.
5. Public SAHJONY `/whatsapp/health` endpoint only as secondary evidence.

## Repository tools

- `openclaw/hostinger-24x7/hostinger-recovery-tool.sh`
- `openclaw/hostinger-24x7/hostinger-recovery-key-seed.sh`
- `openclaw/hostinger-24x7/provider-bootstrap-stabilize.sh`
- `openclaw/hostinger-24x7/whatsapp-guardian.sh`
- `openclaw/hostinger-24x7/install-whatsapp-guardian.sh`

## Acceptance gate

Do not state that WhatsApp is active 24/7 until all are true:

- normal Kali SSH authenticated
- Docker active
- existing OpenClaw container preserved and running
- restart policy persistent
- OpenClaw WhatsApp channel probe healthy
- guardian timer enabled and active
- fresh guardian `last-good`
- `SAHJONY_HOSTINGER_LOCAL_RUNTIME=READY`
