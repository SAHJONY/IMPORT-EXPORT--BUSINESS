# SAHJONY Hostinger Recovery Controller Skill

## Purpose

Use this skill for recovery and 24/7 stabilization of the authorized SAHJONY Hostinger VPS running Kali Linux, Docker, OpenClaw, and the WhatsApp Linked Device transport.

The goal is to recover service without depending on Hostinger Docker Manager, without creating duplicate SSH daemons or OpenClaw containers, and without bypassing WhatsApp/Meta authentication controls.

## Authoritative architecture

Production path:

`Hostinger VPS → Kali → native ssh.service → Docker → existing OpenClaw container → authorized WhatsApp Linked Device session → SAHJONY app/API`

Not required for this path:

- Hostinger Docker Manager. It is unsupported on this Kali VPS.
- Meta Cloud transport. It may exist later as an optional transport, but it is not a recovery dependency.
- The owner's iMac. It is not part of the 24/7 production runtime.

## Controller

Tool:

`openclaw/hostinger-24x7/hostinger-recovery-controller.sh`

Modes:

- `diagnose`: read-only. Reports Hostinger action-plane activity, TCP/22 reachability, authenticated SSH when a key is available, and confirms Docker Manager/Meta are not required.
- `repair-ssh`: uses a single owned Hostinger Recovery session only when normal SSH cannot authenticate. Repairs native Kali OpenSSH and removes the known duplicate `sahjony-sshd.service` regression.
- `heal-runtime`: requires authenticated normal SSH. Starts Docker, preserves the one existing OpenClaw container, applies `unless-stopped`, and installs/runs the Hostinger-only WhatsApp guardian.
- `full`: repair SSH only if required, then heal the existing Docker/OpenClaw runtime.

## Non-negotiable safety gates

1. Never start Recovery while the Hostinger action plane has a nonterminal action.
2. Never create or enable a second SSH daemon on TCP/22.
3. Native Kali `ssh.service` is authoritative. `sahjony-sshd.service` must not exist.
4. Never create a replacement OpenClaw container during recovery. If no existing OpenClaw container is found, stop and investigate.
5. If more than one OpenClaw-like container exists, stop on ambiguity rather than guessing.
6. Never call `openclaw gateway restart` as the infrastructure recovery primitive. Use Docker lifecycle at the host level.
7. Preserve the existing WhatsApp Linked Device session. Do not log out or re-pair automatically.
8. Do not bypass WhatsApp, Meta, Hostinger, SSH, MFA, or provider authentication controls.
9. One bounded VPS restart is permitted after a targeted offline SSH repair; do not loop restarts.
10. Recovery cleanup must exit only a Recovery session owned by the current controller run.

## Known root cause fixed by this skill

Forensics showed two SSH daemons competing for TCP/22:

- native `ssh.service` successfully bound `0.0.0.0:22`
- custom `sahjony-sshd.service` repeatedly failed with `Address already in use`

The controller removes only the duplicate custom unit and keeps the distribution OpenSSH service.

## Decision tree

1. Run `diagnose`.
2. If authenticated normal SSH works, do not enter Recovery. Run `heal-runtime`.
3. If TCP/22 or authenticated SSH is unavailable, run `repair-ssh` or `full`.
4. Before every mutation, require zero nonterminal Hostinger actions.
5. In Recovery, mount/discover the original Kali root, remove duplicate `sahjony-sshd.service`, validate `sshd -t`, enable only `ssh.service`, preserve existing authorized keys, and allow TCP/22 in UFW when present.
6. Exit Recovery and wait for Hostinger's stop action to reach success.
7. Prove normal SSH. If it does not return, perform at most one official VPS restart and prove SSH again.
8. Start Docker and identify exactly one existing OpenClaw container.
9. Apply Docker restart policy `unless-stopped` and start the existing container if stopped.
10. Install the Hostinger-only guardian and verify its systemd timer.
11. Run the local WhatsApp/OpenClaw probe.
12. Only declare 24/7 READY when the local Hostinger gates pass.

## 24/7 acceptance gates

Required:

- Hostinger action plane idle after recovery work
- normal Kali SSH authenticates
- native `ssh.service` active
- no `sahjony-sshd.service`
- Docker active
- exactly one intended existing OpenClaw container identified
- OpenClaw container running
- restart policy `unless-stopped` or `always`
- Hostinger guardian timer active
- local OpenClaw WhatsApp probe reports connected/ready/healthy

Public Vercel health is secondary evidence only. It must never be used as proof that the Hostinger VPS is down or healthy.

## Failure classification

- `CONTROL_PLANE_BUSY`: another Hostinger action is active. Wait; do not mutate.
- `RECOVERY_SSH_FAILED`: Hostinger Recovery booted but password SSH did not authenticate. Inspect Recovery state before any retry.
- `NORMAL_SSH_FAILED`: targeted repair finished but normal SSH does not authenticate. One bounded restart is permitted.
- `OPENCLAW_CONTAINER_NOT_FOUND`: do not create a new container. Investigate Docker volumes, compose files, and stopped containers.
- `OPENCLAW_CONTAINER_AMBIGUITY`: multiple candidates exist. Inspect before touching any container.
- `WHATSAPP_NOT_CONNECTED`: preserve session state. If the durable Linked Device session truly expired, human re-pairing/authentication is required.

## Recovery objective

The controller exists to make recovery deterministic and idempotent. It bypasses unsupported infrastructure dependencies and recurring orchestration mistakes; it does not bypass provider security or authorization.
