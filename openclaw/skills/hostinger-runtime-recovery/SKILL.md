# SAHJONY Hostinger Runtime Recovery Skill

## Purpose
Recover the retained SAHJONY LLC WhatsApp/OpenClaw runtime on the authorized Hostinger Kali VPS without destructive recovery loops, duplicate SSH daemons, replacement containers, Meta Cloud dependencies, or WhatsApp re-pairing.

Critical path:

`Hostinger API -> owned Recovery only if needed -> mounted Kali -> native ssh.service -> normal Kali -> local Docker -> retained OpenClaw -> WhatsApp guardian`

Meta Cloud is optional and must never block this path.

## Canonical components
- `openclaw/hostinger-24x7/hostinger-recovery-controller.sh` — serialized recovery state machine.
- `openclaw/hostinger-24x7/ssh-self-heal.sh` — repairs distro-native `ssh.service` and persistent `/run/sshd` handling.
- `openclaw/hostinger-24x7/hostinger-runtime-bootstrap.sh` — restores Docker only when retained state exists; never invents OpenClaw.
- `openclaw/hostinger-24x7/openclaw-runtime-recovery.sh` — pipefail-safe retained-runtime forensic planner and gated reconstruction engine.
- `openclaw/hostinger-24x7/runtime-plan-doctor.sh` — read-only classifier for planner failures and forensic results.
- `openclaw/hostinger-24x7/whatsapp-hostinger-only-guardian.sh` — protects the authorized Linked Device runtime without logout/re-pair.
- `.github/workflows/hostinger-runtime-recovery-engine.yml` — one serialized GitHub execution surface.

## Failure classifier

### TCP/22 closed or filtered
1. Read Hostinger VM/action state.
2. Do not mutate while a provider action is nonterminal.
3. Prefer a bounded normal restart only when appropriate.
4. If normal SSH cannot be restored, enter one owned Recovery session, repair the original Kali filesystem, exit Recovery, then verify normal SSH.

### TCP/22 open but `Permission denied (publickey)`
The network path and sshd are alive. Do not reboot repeatedly. Seed a temporary authorized management key through one owned Recovery session, validate `sshd -t`, enable native `ssh.service`, and install the SSH runtime-guard timer.

### Recovery action succeeds but Recovery SSH fails
Treat this as a provider/Recovery-path failure. Exit only the Recovery session owned by the current run and do not immediately start a second disk Recovery.

### Runtime planner exits 141
`141 = 128 + SIGPIPE`. Under `set -o pipefail`, early-exit truncation pipelines such as `find | head` can surface 141 even when the underlying runtime data is valid.

Required behavior:
- never interpret rc=141 as “OpenClaw state missing”;
- never reconstruct or delete state because of rc=141;
- use the Python forensic engine in `openclaw-runtime-recovery.sh`, which bounds results without terminating upstream producers early;
- run `runtime-plan-doctor.sh` to emit a structured classification.

### Docker healthy, OpenClaw container metadata absent
Run the retained-runtime forensic planner. It must search bounded administrative roots, score candidate compose/runtime artifacts, and exclude `/var/lib/docker` from durable-state evidence so a newly empty Docker volume cannot be mistaken for the prior WhatsApp session.

Automatic reconstruction is allowed only when all conditions are true:
- exactly one high-confidence candidate exists;
- the candidate is a retained compose file;
- at least one real host bind source exists and contains files;
- Docker Compose validates the candidate;
- the explicit gate `RECOVER_RETAINED_OPENCLAW` is present.

Otherwise return a forensic classification and preserve all state.

### Multiple OpenClaw containers or multiple safe reconstruction candidates
Stop and classify ambiguity. Never choose one arbitrarily.

### WhatsApp requires device re-linking
Surface a pairing requirement. No recovery automation may fabricate Linked Device authorization, bypass 2FA, or force a re-pair.

## Recovery sequence
1. Confirm the GitHub/VPS mutation queue is clear.
2. Repair/authenticate normal Kali SSH only if needed.
3. Require native `ssh.service`, TCP/22, `/run/sshd`, and the SSH runtime-guard timer.
4. Verify Docker locally on Kali.
5. If exactly one retained OpenClaw container exists, enforce `unless-stopped`, start it if required, install the WhatsApp guardian, and run `openclaw channels status --probe`.
6. If Docker contains no OpenClaw metadata, run `runtime-plan-doctor.sh` and use its structured result.
7. Reconstruct only through the explicit retained-state gate and only from one unambiguous durable compose candidate.
8. Verify Hostinger-local WhatsApp and guardian gates before reporting 24/7 READY.

## Hard prohibitions
- Never start a second/custom sshd daemon.
- Never run two Hostinger VPS mutations concurrently.
- Never destroy/reinitialize `/var/lib/docker`, `/var/lib/containerd`, OpenClaw state, volumes, or WhatsApp session storage as a recovery shortcut.
- Never create a replacement OpenClaw container from weak or ambiguous evidence.
- Never automatically logout, unlink, pair, replace, or regenerate the authorized WhatsApp Linked Device session.
- Never treat Vercel/public health as authoritative for Hostinger runtime health.
- Never make Meta Cloud credentials a prerequisite.

## Acceptance gates for 24/7 READY
All local gates must pass:
- normal Kali SSH authenticates;
- native `ssh.service` is active and listening on port 22;
- `sahjony-ssh-runtime-guard.timer` is active;
- Docker is active;
- exactly one intended OpenClaw runtime is identified and running;
- restart policy is `unless-stopped` or `always`;
- direct `openclaw channels status --probe` confirms WhatsApp connected/ready;
- Hostinger-only WhatsApp guardian timer is active;
- guardian `last-good`/heartbeat is fresh;
- durable linked-device state is preserved;
- no iMac or Meta dependency is required.

Public `/whatsapp/health` is secondary evidence and should agree only after these Hostinger-local gates pass.
