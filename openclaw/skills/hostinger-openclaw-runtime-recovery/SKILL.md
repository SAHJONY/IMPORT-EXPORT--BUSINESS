# Hostinger OpenClaw Runtime Recovery Skill

## Purpose

Use this skill after normal Kali SSH is healthy but the Hostinger Docker/OpenClaw runtime is missing, incomplete, or no longer represented in Docker metadata.

This skill is specifically designed for the proven case where:

- normal SSH authenticates;
- Docker can be restored;
- `/var/lib/docker` does not contain an OpenClaw container;
- OpenClaw-related deployment/configuration artifacts still exist elsewhere on the Kali filesystem.

The objective is to recover the authorized retained runtime without fabricating an empty OpenClaw instance or destroying the existing WhatsApp Linked Device state.

## Canonical tool

`openclaw/hostinger-24x7/openclaw-runtime-recovery.sh`

Commands:

- `audit` — read-only filesystem, Docker, compose, deployment, and retained-state inventory.
- `plan` — scores recovery candidates and determines whether safe reconstruction is possible.
- `reconstruct` — reconstructs only when there is exactly one high-confidence retained compose candidate backed by existing durable host bind state.

## Safety model

A missing Docker container does **not** automatically authorize a fresh container.

Automatic reconstruction is permitted only when all of these are true:

1. no existing OpenClaw-like container is present;
2. exactly one retained compose file reaches the configured confidence threshold;
3. that compose definition references OpenClaw/WhatsApp runtime semantics;
4. it contains one or more absolute host bind mounts whose source paths still exist and contain data;
5. those durable sources are outside `/var/lib/docker`;
6. Docker Compose validates the retained definition before starting anything;
7. the operator/controller provides `SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT=RECOVER_RETAINED_OPENCLAW`;
8. the reconstruction results in exactly one OpenClaw-like container;
9. the reconstructed container passes `openclaw channels status --probe`.

If any gate fails, the tool stops with a forensic decision rather than guessing.

## Why named Docker volumes are not enough

When `/var/lib/docker` metadata has been lost or recreated, a compose file that references only a named Docker volume can silently create a new empty volume. That can produce a superficially healthy container while losing the authorized Linked Device/session state.

For that reason, this recovery tool requires retained host bind-state evidence for automatic reconstruction. Named-volume-only candidates remain forensic/manual cases.

## Candidate scoring

The audit scores retained artifacts using evidence such as:

- OpenClaw/Claw/WhatsApp references;
- container/compose definitions;
- session/auth references;
- persistent restart policy;
- retained OpenClaw state elsewhere on the host;
- existing, non-empty absolute host bind sources.

A candidate with durable bind state receives the largest confidence increase. Multiple high-confidence candidates cause a hard ambiguity stop.

## Decision outcomes

- `USE_EXISTING_CONTAINER` — exactly one current OpenClaw container exists; do not reconstruct.
- `FORENSICS_REQUIRED_NO_SAFE_RECONSTRUCTION` — no candidate meets the safe threshold.
- `FORENSICS_REQUIRED_MULTIPLE_HIGH_CONFIDENCE_CANDIDATES` — more than one plausible retained runtime exists.
- `SAFE_RECONSTRUCTION_CANDIDATE_FOUND` — one retained compose definition with durable host state is eligible.
- `OPENCLAW_RUNTIME_RECONSTRUCTION=READY` — reconstruction completed and the OpenClaw channel probe passed.

## Integration order

1. Repair and persist native SSH with `ssh-self-heal.sh`.
2. Prove normal key-authenticated SSH.
3. Run `openclaw-runtime-recovery.sh audit`.
4. If exactly one existing OpenClaw container exists, preserve it and install the guardian.
5. If container metadata is absent, run `plan`.
6. Only if `plan` returns one safe candidate may the controller invoke `reconstruct` with the explicit reconstruction token.
7. Install the Hostinger-only guardian.
8. Verify Docker restart policy and `openclaw channels status --probe`.
9. Do not declare WhatsApp 24/7 READY until those local gates pass.

## Prohibited shortcuts

- Do not create a blank OpenClaw container because an image or deploy script exists.
- Do not run `docker compose up` against an arbitrary compose file.
- Do not treat a newly created named volume as retained session state.
- Do not log out, delete, reset, or automatically re-pair WhatsApp.
- Do not bypass WhatsApp, Hostinger, SSH, Meta, MFA, or provider authentication controls.
- Do not use Hostinger Docker Manager on this Kali VPS.

## Current proven failure classification

The current runtime failure is:

`OPENCLAW_CONTAINER_NOT_FOUND_AFTER_DOCKER_RESTORE`

This is no longer an SSH failure. The correct next step is retained-runtime discovery and state provenance, not another SSH Recovery loop.
