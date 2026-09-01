# SAHJONY Hostinger/OpenClaw Recovery Skill

## Objective
Restore the Hostinger Kali VPS, Docker, OpenClaw, and the authorized WhatsApp Linked Device runtime without depending on Meta Cloud or the Hostinger Docker Manager.

## Non-negotiable invariants
- Hostinger/OpenClaw is the primary WhatsApp transport. Meta Cloud is optional and must never gate recovery.
- Never start a second VPS mutation while a Hostinger action is nonterminal.
- Never use Docker Manager on this Kali VPS; Hostinger reports the OS is unsupported.
- Never destroy/recreate the OpenClaw container or its volumes merely to recover connectivity.
- Never auto-logout, unlink, or re-pair the authorized WhatsApp Linked Device session.
- Do not use `openclaw gateway restart` as the primary Docker recovery mechanism.
- Vercel/public health is secondary evidence only. Hostinger-local probes are authoritative.

## Deterministic recovery ladder
1. Run `hostinger-recovery-preflight.sh`.
2. If `HOSTINGER_MUTATION_GATE=WAIT`, wait for the existing Hostinger action to terminate; do not mutate.
3. If durable normal SSH works, skip disk Recovery and repair Docker/OpenClaw in place.
4. If normal SSH is unavailable, permit one bounded official VPS restart and wait for its action ID to reach a terminal state.
5. If SSH is still unavailable, enter Hostinger Recovery exactly once with per-run credentials.
6. Authenticate Recovery SSH; never treat TCP/22 alone as success.
7. Discover the original Kali root, seed the durable SSH key, enable ssh/sshd, validate `sshd -t`, then sync.
8. Stop only the Recovery session owned by the current run and poll the stop action to completion.
9. Authenticate normal Kali SSH.
10. Verify Docker service. Discover and preserve the existing OpenClaw container and volumes.
11. Set container restart policy to `unless-stopped` unless it is already `always`/`unless-stopped`.
12. Start the existing container if stopped; use one host-level `docker restart` only if the local OpenClaw WhatsApp probe fails.
13. Install/verify the WhatsApp guardian systemd timer.
14. Require `openclaw channels status --probe` to show the WhatsApp channel healthy/connected.
15. Write/verify a fresh guardian `last-good` marker.
16. Only after local gates pass, inspect public `/whatsapp/health` as secondary evidence.

## READY gates
Do not declare 24/7 READY until all are true:
- authenticated normal SSH
- Docker running
- existing OpenClaw container preserved and running
- restart policy persistent
- local WhatsApp probe healthy
- guardian timer active
- fresh last-good timestamp
- Hostinger-local runtime marker READY

## Failure classification
- `ACTION_PLANE_BUSY`: nonterminal Hostinger action; wait, never collide.
- `RESTART_FAILED`: inspect action payload; proceed to Recovery only after terminal state.
- `RECOVERY_AUTH_FAILED`: stop owned Recovery safely; do not loop.
- `KALI_ROOT_NOT_FOUND`: inspect block devices/mounts; do not format or repartition.
- `NORMAL_SSH_FAILED`: verify sshd enablement/config/key from Recovery before another infrastructure mutation.
- `DOCKER_DOWN`: start Docker service; do not invoke Docker Manager.
- `OPENCLAW_CONTAINER_MISSING`: inventory Docker containers/volumes before any creation.
- `WHATSAPP_PROBE_FAILED`: one bounded container restart, re-probe, preserve session.
- `PUBLIC_HEALTH_STALE`: fix/deploy web API separately; do not downgrade a healthy Hostinger-local runtime.
