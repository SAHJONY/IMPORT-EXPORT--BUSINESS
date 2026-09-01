# SAHJONY Hostinger VPS Doctor

Use this skill for the production VPS `srv767852.hstgr.cloud` (`69.62.68.67`, Hostinger VM `767852`) when SSH, Docker, OpenClaw, or the WhatsApp linked-device transport is degraded.

## Objective

Diagnose before mutating. Preserve the existing Kali installation, Docker volumes, OpenClaw container, and authorized WhatsApp linked-device session. Meta Cloud is not a production dependency.

## Non-negotiable safety rules

1. Never bypass SSH authentication, WhatsApp authentication, or provider security controls.
2. Never create a second OpenClaw container when an existing one is present or may contain the linked session.
3. Never logout, unlink, or re-pair WhatsApp automatically.
4. Never mutate guest firewall rules automatically. Report suspected firewall blockage instead.
5. Never run disk Recovery while a Hostinger VM action, Recovery, or V7 recovery is active.
6. Never use repeated blind reboots. Recovery V7 is the bounded escalation path.
7. Public Vercel health is secondary evidence; Hostinger-local evidence is authoritative.
8. Do not make the iMac part of the 24/7 production dependency chain.

## Evidence ladder

Work through these gates in order:

1. Hostinger control plane: VM identity/state and recent action list.
2. External reachability: TCP/22, then optional 80/443 observations.
3. Authenticated SSH using the durable Hostinger key.
4. Guest OS: `sshd -t`, service state, listener on 22, default route, disk/inode pressure, firewall observation.
5. Docker: daemon active and existing OpenClaw container discovery.
6. OpenClaw: container running, restart policy `unless-stopped` or `always`.
7. WhatsApp: `openclaw channels status --probe` indicates connected/ready/healthy.
8. Guardian: systemd timer active and last-good evidence fresh when available.

## Doctor command

Audit only:

```bash
sudo bash openclaw/hostinger-24x7/hostinger-vps-doctor.sh audit
```

Bounded heal on an already authenticated production shell:

```bash
sudo bash openclaw/hostinger-24x7/hostinger-vps-doctor.sh heal
```

`heal` may enable a valid SSH service, start Docker, start the existing OpenClaw container, enforce a durable Docker restart policy, and delegate one bounded WhatsApp recovery to the existing guardian. It does not alter firewall policy, recreate the container, or re-pair WhatsApp.

## Root-cause classifications

- `sshd_config_invalid`: repair SSH config through Recovery V7; do not reboot-loop.
- `sshd_not_serving`: if normal authenticated SSH is impossible, use Recovery V7 after action-plane reconciliation.
- `guest_firewall_suspect`: use Hostinger Web Console or Recovery V7 to inspect/fix the guest rules deliberately; do not flush firewall rules blindly.
- `storage_pressure`: free space/inodes conservatively before restarting services.
- `docker_missing`: investigate package/runtime provenance before installing anything; do not replace a custom runtime blindly.
- `docker_inactive`: start/enable Docker, then re-run audit.
- `openclaw_container_missing`: stop automatic healing and locate volumes/compose provenance first.
- `openclaw_container_stopped`: start the existing container; never create a replacement automatically.
- `whatsapp_channel_unhealthy`: invoke the existing Hostinger guardian for one bounded host-level container recovery; preserve linked-device state.
- `restart_policy_weak`: set existing container to `unless-stopped`.
- `guardian_inactive`: install/enable the existing guardian timer.
- `ready`: local production gates pass.

## Escalation decision

Escalate to `.github/workflows/hostinger-whatsapp-recovery-v7.yml` only when all are true:

- durable normal SSH is unavailable or cannot repair the fault;
- the Hostinger action plane has no nonterminal VM/Recovery action;
- no V7 run is queued or in progress;
- evidence has been captured first.

V7 is allowed to enter Hostinger Recovery, authenticate Recovery SSH, repair original Kali SSH, seed the durable key, exit Recovery, and then stabilize Docker/OpenClaw. It must preserve OpenClaw data and the linked WhatsApp session.

## Acceptance gates

Do not report 24/7 READY until normal authenticated SSH works, Docker is running, the existing OpenClaw container is preserved and running, WhatsApp probe is healthy, restart policy is durable, and the guardian is active with fresh local evidence. Public `/whatsapp/health` is only a secondary confirmation.
