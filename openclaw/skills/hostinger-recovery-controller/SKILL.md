# SAHJONY Hostinger Recovery Controller Skill

## Purpose

Use this skill for recovery and 24/7 stabilization of the authorized SAHJONY Hostinger VPS running Kali Linux, Docker, OpenClaw, and the WhatsApp Linked Device transport.

The goal is to recover service without depending on Hostinger Docker Manager, without creating duplicate SSH daemons or OpenClaw containers, and without bypassing WhatsApp/Meta authentication controls.

## Authoritative architecture

Production path:

`Hostinger VPS → Kali → native ssh.service → local Docker engine → existing OpenClaw container → authorized WhatsApp Linked Device session → SAHJONY app/API`

Not required for this path:

- Hostinger Docker Manager. It is unsupported on this Kali VPS.
- Meta Cloud transport. It may exist later as an optional transport, but it is not a recovery dependency.
- The owner's iMac. It is not part of the 24/7 production runtime.

## Canonical tools

### Recovery controller

`openclaw/hostinger-24x7/hostinger-recovery-controller.sh`

Modes:

- `diagnose`: read-only. Reports Hostinger action-plane activity, TCP/22 reachability, authenticated SSH when a key is available, and confirms Docker Manager/Meta are not required.
- `repair-ssh`: uses a single owned Hostinger Recovery session only when normal SSH cannot authenticate. Repairs native Kali OpenSSH and removes the known duplicate `sahjony-sshd.service` regression.
- `heal-runtime`: requires authenticated normal SSH. Starts local Docker, preserves the one existing OpenClaw container, applies `unless-stopped`, and installs/runs the Hostinger-only WhatsApp guardian.
- `full`: repair SSH only if required, then heal the existing Docker/OpenClaw runtime.

### Retained-runtime bootstrap

`openclaw/hostinger-24x7/hostinger-runtime-bootstrap.sh`

Use this when normal Kali SSH works but `docker` is missing.

The bootstrap:

1. audits `/var/lib/docker`, `/var/lib/containerd`, compose files, and OpenClaw-related artifacts;
2. restores the distro `docker.io` package only when retained runtime evidence exists;
3. never creates a fresh OpenClaw container;
4. requires exactly one existing OpenClaw-like container after Docker restoration;
5. applies `unless-stopped` and starts only that retained container;
6. stops on missing or ambiguous state so the WhatsApp Linked Device session is not overwritten.

### Hostinger-only guardian

`openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh`

The guardian operates only on the existing local OpenClaw container. It has a restart cooldown, installs a systemd timer, and treats a valid WhatsApp channel probe as the local readiness authority.

## Non-negotiable safety gates

1. Never start Recovery while the Hostinger action plane has a nonterminal action.
2. Never create or enable a second SSH daemon on TCP/22.
3. Native Kali `ssh.service` is authoritative. `sahjony-sshd.service` must not exist.
4. Never create a replacement OpenClaw container during recovery. If no existing OpenClaw container is found, stop and investigate.
5. If more than one OpenClaw-like container exists, stop on ambiguity rather than guessing.
6. Never call `openclaw gateway restart` as the infrastructure recovery primitive. Use local Docker lifecycle at the host level.
7. Preserve the existing WhatsApp Linked Device session. Do not log out or re-pair automatically.
8. Do not bypass WhatsApp, Meta, Hostinger, SSH, MFA, or provider authentication controls.
9. One bounded VPS restart is permitted after a targeted offline SSH repair; do not loop restarts.
10. Recovery cleanup must exit only a Recovery session owned by the current controller run.
11. Do not reinstall Docker blindly. Restore Docker only if retained Docker/OpenClaw state is present.
12. Do not use Hostinger Docker Manager as a fallback on Kali.

## Proven failure modes and fixes

### SSH daemon collision

Forensics showed two SSH daemons competing for TCP/22:

- native `ssh.service` successfully bound `0.0.0.0:22`;
- custom `sahjony-sshd.service` repeatedly failed with `Address already in use`.

Fix: remove only the duplicate custom unit and keep the distribution OpenSSH service.

### Missing Docker binary

After SSH was repaired and authenticated normally, runtime recovery reported `DOCKER_NOT_FOUND=1`.

Fix: do not re-enter SSH repair. Run the retained-runtime bootstrap. It first proves retained Docker/OpenClaw state, then restores the local Docker engine and reattaches to the retained container metadata. If retained state cannot be proved, stop rather than creating a new OpenClaw instance.

## Decision tree

1. Run `diagnose`.
2. If authenticated normal SSH works, do not enter Recovery.
3. If `docker` exists, run `heal-runtime`.
4. If `docker` is missing, run `hostinger-runtime-bootstrap.sh audit`.
5. If retained runtime evidence exists, run `hostinger-runtime-bootstrap.sh heal`.
6. If retained runtime evidence does not exist, stop and investigate disk/volume state; do not create OpenClaw.
7. If TCP/22 or authenticated SSH is unavailable, run `repair-ssh` or `full`.
8. Before every Hostinger mutation, require zero nonterminal Hostinger actions.
9. In Recovery, mount/discover the original Kali root, remove duplicate `sahjony-sshd.service`, validate `sshd -t`, enable only `ssh.service`, preserve existing authorized keys, and allow TCP/22 in UFW when present.
10. Exit Recovery and wait for Hostinger's stop action to reach success.
11. Prove normal SSH. If it does not return, perform at most one official VPS restart and prove SSH again.
12. Identify exactly one retained OpenClaw container.
13. Apply Docker restart policy `unless-stopped` and start the existing container if stopped.
14. Install the Hostinger-only guardian and verify its systemd timer.
15. Run the local WhatsApp/OpenClaw probe.
16. Only declare 24/7 READY when the local Hostinger gates pass.

## Workflow authority

Canonical control surfaces:

- `.github/workflows/hostinger-recovery-controller.yml` — manual, guarded controller entrypoint.
- `.github/workflows/hostinger-runtime-recovery-v11.yml` — temporary one-shot retained-runtime recovery used to resolve the current missing-Docker condition; retire its push trigger after the recovery is complete.

Legacy Hostinger workflows that independently mutate Recovery, SSH, Docker, or Hostinger Docker Manager must remain retired. Read-only diagnostics may remain available.

## 24/7 acceptance gates

Required:

- Hostinger action plane idle after recovery work
- normal Kali SSH authenticates
- native `ssh.service` active
- no `sahjony-sshd.service`
- local Docker engine active
- exactly one intended retained OpenClaw container identified
- OpenClaw container running
- restart policy `unless-stopped` or `always`
- Hostinger guardian timer active
- local OpenClaw WhatsApp probe reports connected/ready/healthy

Public Vercel health is secondary evidence only. It must never be used as proof that the Hostinger VPS is down or healthy.

## Failure classification

- `CONTROL_PLANE_BUSY`: another Hostinger action is active. Wait; do not mutate.
- `RECOVERY_SSH_FAILED`: Hostinger Recovery booted but password SSH did not authenticate. Inspect Recovery state before any retry.
- `NORMAL_SSH_FAILED`: targeted repair finished but normal SSH does not authenticate. One bounded restart is permitted.
- `DOCKER_NOT_FOUND`: SSH is healthy; switch to retained-runtime bootstrap rather than repeating SSH repair.
- `NO_RETAINED_RUNTIME_STATE_REFUSING_FRESH_DOCKER_INSTALL`: do not install Docker or create OpenClaw; investigate disk/state retention.
- `OPENCLAW_CONTAINER_NOT_FOUND_AFTER_DOCKER_RESTORE`: do not create a new container. Inspect Docker metadata, volumes, compose files, and backups.
- `OPENCLAW_CONTAINER_AMBIGUITY`: multiple candidates exist. Inspect before touching any container.
- `WHATSAPP_NOT_CONNECTED`: preserve session state. If the durable Linked Device session truly expired, human re-pairing/authentication is required.

## Recovery objective

The controller exists to make recovery deterministic and idempotent. It bypasses unsupported infrastructure dependencies and recurring orchestration mistakes; it does not bypass provider security or authorization.
