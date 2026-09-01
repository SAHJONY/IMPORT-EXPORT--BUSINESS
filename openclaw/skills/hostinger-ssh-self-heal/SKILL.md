# Hostinger Kali SSH Self-Heal Skill

## Purpose

Use this skill whenever the SAHJONY Hostinger VPS is reachable through Hostinger Recovery but normal Kali SSH is unavailable, reset, or refusing connections.

This skill repairs **only the distro-native `ssh.service`**. It must never create or start a second `sshd` daemon on TCP/22.

## Root cause this skill prevents

A previous fallback created `sahjony-sshd.service` with `RuntimeDirectory=sshd` while Kali's native `ssh.service` also owned `/run/sshd`. The duplicate daemon repeatedly failed to bind TCP/22. Because systemd managed the same runtime directory for both units, the duplicate unit could remove `/run/sshd` while the native daemon was still running. The native daemon would continue listening but new sessions failed in pre-auth with:

`fatal: chroot("/run/sshd"): No such file or directory [preauth]`

The permanent rule is therefore: **one SSH daemon, one owner of TCP/22, native `ssh.service` only.**

## Repair engine

Canonical script:

`openclaw/hostinger-24x7/ssh-self-heal.sh`

### Live repair

Run on normal Kali:

```bash
sudo /usr/local/sbin/sahjony-ssh-self-heal
```

The engine:

- removes legacy `sahjony-sshd.service` and its target symlinks;
- removes explicit SSH masks and `sshd_not_to_be_run`;
- preserves the native Kali/OpenSSH service;
- installs `99-sahjony-native.conf` with key-only root management access;
- installs `/etc/tmpfiles.d/sahjony-sshd.conf` so `/run/sshd` exists at boot;
- installs a native `ssh.service` drop-in with an `ExecStartPre` that creates `/run/sshd`;
- validates `sshd -t` before restarting;
- enables the native `ssh.service`;
- installs a two-minute runtime guard that repairs `/run/sshd` and restarts only the native service if it is inactive or TCP/22 is not listening.

### Offline Recovery repair

From Hostinger Recovery with the original Kali root mounted at `/mnt/sdb1`:

```bash
ROOT_PREFIX=/mnt/sdb1 ./ssh-self-heal.sh
```

The offline mode:

- never starts a daemon inside the mounted root;
- removes the competing unit;
- installs the native configuration and guard;
- enables native `ssh.service` through target links;
- validates the original OS using `chroot /mnt/sdb1 /usr/sbin/sshd -t`;
- emits `OFFLINE_SSH_REPAIR_READY=1` only after validation passes.

## Recovery decision tree

1. If normal SSH authenticates, run the live repair and validate.
2. If TCP/22 is open but sessions reset, inspect the normal boot journal. A `/run/sshd` preauth error is repaired by this skill; do not add another daemon.
3. If TCP/22 refuses connections, use one serialized Hostinger Recovery session, mount the original root, run offline repair, exit Recovery, then test normal SSH.
4. Only one Hostinger VPS mutation workflow may run at a time.
5. Do not use Docker Manager on this Kali VPS; Hostinger reports the OS does not support Docker Manager.
6. Do not destroy or recreate the OpenClaw container while repairing SSH.
7. Meta Cloud is not required for the WhatsApp transport path.

## Acceptance gates

SSH is considered repaired only when all are true:

- `systemctl is-active ssh.service` returns active;
- no active or enabled `sahjony-sshd.service` exists;
- `/run/sshd` exists with mode 0755 and root ownership;
- `/usr/sbin/sshd -t` succeeds;
- TCP/22 is listening;
- an actual key-authenticated SSH command succeeds;
- `sahjony-ssh-runtime-guard.timer` is enabled and active.

After SSH is repaired, continue with Docker/OpenClaw/WhatsApp verification. Do not label WhatsApp 24/7 READY until the OpenClaw container, WhatsApp channel probe, restart policy, and guardian gates also pass.
