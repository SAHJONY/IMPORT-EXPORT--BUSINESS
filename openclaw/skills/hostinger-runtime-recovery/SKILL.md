# SAHJONY Hostinger Runtime Recovery Skill

## Purpose
Recover the retained SAHJONY WhatsApp/OpenClaw runtime on the Hostinger Kali VPS when normal SSH is unavailable, without creating a second SSH daemon, replacing Docker/OpenClaw state, or re-pairing WhatsApp.

## Architecture
Hostinger Recovery is the control-plane escape hatch. The original Kali filesystem is repaired offline while mounted by Recovery. The next normal boot then self-heals native `ssh.service`, restores retained Docker/OpenClaw state, and installs/heals the WhatsApp guardian.

Critical path:

`Hostinger API -> Recovery -> mounted Kali -> native ssh.service self-heal -> normal boot -> retained Docker/OpenClaw -> WhatsApp guardian`

Meta Cloud is optional and must never block this path.

## Canonical components
- `openclaw/hostinger-24x7/ssh-self-heal.sh`
  - owns SSH repair policy
  - repairs only distro-native `ssh.service`
  - removes legacy competing SAHJONY sshd units
  - installs a persistent two-minute native SSH guard
- `openclaw/hostinger-24x7/hostinger-runtime-bootstrap.sh`
  - restores Docker only when retained runtime state exists
  - refuses to create a new OpenClaw container
  - requires exactly one retained OpenClaw container before healing it
- `openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh`
  - protects the retained authorized WhatsApp/OpenClaw runtime
  - never logs out or re-pairs WhatsApp
- `openclaw/hostinger-24x7/recovery-seed-boot-rescue.sh`
  - runs inside Recovery
  - discovers the mounted Kali root
  - installs an ephemeral management key and optional durable key
  - applies the canonical native SSH self-heal offline
  - seeds the runtime bootstrap and guardian into the original OS
  - installs a normal-boot rescue service so runtime restoration does not depend on pre-existing normal SSH

## Recovery decision tree
1. Query Hostinger VM actions. If any VPS mutation is nonterminal, do not start another mutation.
2. If authenticated normal SSH works, skip Recovery and run the live self-heal/runtime/guardian path.
3. If normal SSH is unavailable, enter one owned Recovery session through the Hostinger API.
4. Authenticate Recovery SSH using the temporary Recovery credential.
5. Locate the original mounted Kali filesystem. Never assume `/mnt` is the root without validating `etc/os-release`, `etc/ssh`, and `root`.
6. Copy these files into Recovery `/tmp`:
   - one-run public key
   - optional durable management public key
   - `ssh-self-heal.sh`
   - `hostinger-runtime-bootstrap.sh`
   - `whatsapp-hostinger-only-guardian.sh`
   - `recovery-seed-boot-rescue.sh`
7. Execute `recovery-seed-boot-rescue.sh` inside Recovery.
8. Require these offline gates before exiting Recovery:
   - `RECOVERY_SEEDED_BOOT_RESCUE=READY`
   - `NATIVE_SSH_SINGLE_DAEMON=1`
   - `RETAINED_OPENCLAW_ONLY=1`
   - `WHATSAPP_REPAIR_OR_LOGOUT_AUTOMATION=0`
   - `chroot <root> /usr/sbin/sshd -t` succeeds
9. Exit only the Recovery session owned by the current run and poll the Hostinger action ID to terminal success.
10. Observe two independent normal-runtime signals:
    - management: authenticated native SSH
    - service: Hostinger/OpenClaw local heartbeat or direct local WhatsApp probe
11. A single bounded Hostinger restart is allowed only when both signals remain dark after Recovery exit and the Hostinger action plane is idle.
12. Once SSH is available, run live audits and remove the one-run ephemeral key.

## What this skill must never do
- Do not start a second or custom `sshd` daemon.
- Do not use a push-triggered destructive recovery loop.
- Do not launch a second Recovery while another VPS mutation is active.
- Do not destroy or recreate `/var/lib/docker`, OpenClaw containers, volumes, or WhatsApp session storage.
- Do not create a new OpenClaw container when retained state is missing or ambiguous.
- Do not automatically pair, log out, unlink, replace, or regenerate the authorized WhatsApp Linked Device session.
- Do not treat a Vercel/public health failure as proof the Hostinger runtime is down.
- Do not make Meta Cloud credentials a prerequisite.

## Acceptance gates for 24/7 READY
All applicable local gates must pass before declaring production ready:
- native `ssh.service` active and TCP/22 listening
- `sahjony-ssh-runtime-guard.timer` enabled/active
- Docker active
- exactly one retained OpenClaw container identified
- OpenClaw container running with restart policy `unless-stopped` or `always`
- direct `openclaw channels status --probe` succeeds locally (native or inside retained container)
- Hostinger-only WhatsApp guardian timer active
- fresh guardian `last-good` marker/status
- no WhatsApp logout/re-pair event occurred

Public `/whatsapp/health` is secondary evidence and should agree after the Hostinger-local gates are healthy.

## Failure classification
- Recovery API 403/409/422: reconcile Hostinger action plane first; do not spam retries.
- Recovery SSH unavailable: remain in the owned Recovery flow and perform bounded credential/connectivity probes.
- Offline `sshd -t` fails: stop before Recovery exit; repair config against mounted Kali.
- Normal SSH unavailable after a valid offline repair: wait for normal boot, then allow at most one official Hostinger restart if both management and runtime signals are dark.
- Docker binary missing with retained Docker/OpenClaw state: runtime bootstrap may restore the distro Docker package.
- No retained OpenClaw state/container: fail closed and preserve disk for diagnosis; do not create a replacement automatically.
- More than one OpenClaw container candidate: fail closed and require inventory-based disambiguation.

## Operational rule
Prefer repair of retained state over reconstruction. Every mutation must be bounded, idempotent, serializable, and reversible where practical.