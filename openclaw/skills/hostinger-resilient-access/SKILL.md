# SAHJONY Hostinger Resilient Access Skill

## Purpose

Use this skill when the authorized SAHJONY Hostinger Kali VPS is reachable only partially, TCP/22 is closed, or a Hostinger account-level public-key attachment reports success but normal guest-OS SSH still does not authenticate.

The skill bypasses that fragile orchestration dependency. It does **not** bypass Hostinger, SSH, WhatsApp, MFA, or provider security controls.

## Authoritative access path

`GitHub runner → authenticated Hostinger API → direct Kali SSH when already valid → one owned Hostinger Recovery session only when required → mounted original Kali filesystem → native ssh.service → normal Kali boot`

Hostinger public-key attachment is treated as advisory account metadata, not proof that the running Kali guest has accepted the key.

## Primary tool

`openclaw/hostinger-24x7/hostinger-resilient-access-broker.sh`

Modes:

- `diagnose` — read-only classification of TCP/22 and SSH authentication.
- `solve` — prepares/uses one management key, waits for a stably idle Hostinger action plane, skips provider public-key attachment as a readiness dependency, and calls the canonical recovery controller in `repair-ssh` mode only when direct SSH cannot authenticate.

## Required environment

- `HOSTINGER_API_TOKEN`
- `HOSTINGER_VM_ID`
- `HOSTINGER_HOST`
- `HOSTINGER_USER` (defaults to `root`)
- `SSH_KEY_PATH` is optional for the script itself. A workflow should normally create a per-run ephemeral key and pass its path so the same key can be used for post-recovery verification and then removed.

## Why this exists

A provider-side key can be registered/attached successfully while the currently running guest OS still rejects that key. Therefore:

1. Provider key attachment must not be used as the sole readiness gate.
2. A successful attachment action does not equal successful guest authorization.
3. If normal SSH does not authenticate, the deterministic supported fallback is Hostinger Recovery, using Hostinger API authorization already held by the workflow.
4. The canonical recovery controller injects the public key directly into the mounted original Kali `/root/.ssh/authorized_keys`, validates OpenSSH configuration, enables only native `ssh.service`, exits only its owned Recovery session, and permits at most one bounded VM restart.

## Safety gates

1. Use the shared concurrency group `hostinger-vm-767852-mutation` for every workflow that can mutate this VPS.
2. Require zero nonterminal Hostinger actions before entering Recovery.
3. Never start a second Recovery session while another action is pending/running.
4. Never create a second SSH daemon; `ssh.service` is authoritative.
5. Never disable provider firewalls, authentication, MFA, or security controls.
6. Never use Hostinger Docker Manager as a fallback on this Kali VPS.
7. Do not touch Docker/OpenClaw until normal Kali SSH is authenticated.
8. Do not log out or automatically re-pair the WhatsApp Linked Device session.
9. Remove per-run ephemeral SSH keys from both the guest `authorized_keys` and the runner after the audit/recovery sequence finishes.

## Runtime handoff

Once access reports:

`SAHJONY_HOSTINGER_ACCESS_BROKER=READY`

hand off to:

`openclaw/hostinger-24x7/hostinger-recovery-controller.sh full`

with:

`SAHJONY_ALLOW_OPENCLAW_RECONSTRUCT=RECOVER_RETAINED_OPENCLAW`

The controller must reuse retained Docker/OpenClaw state and stop on ambiguity. It must not create a fresh OpenClaw/WhatsApp runtime without evidence-backed retained state.

## Acceptance gates

Access is READY only when:

- Hostinger action plane is idle after recovery;
- normal Kali TCP/22 is reachable;
- the management key authenticates directly to the normal guest OS;
- native `ssh.service` is active/valid;
- no duplicate custom SSH daemon is required.

The complete WhatsApp 24/7 system is READY only after the runtime controller additionally proves local Docker, retained OpenClaw, restart policy, guardian timer, and a connected/healthy WhatsApp channel probe.

## Expected marker

`SAHJONY_HOSTINGER_ACCESS_BROKER=READY`
