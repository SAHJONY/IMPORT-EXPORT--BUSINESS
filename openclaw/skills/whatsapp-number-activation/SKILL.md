# SAHJONY WhatsApp Linked-Number Activation Skill

## Purpose
Activate and keep operational the WhatsApp Business number that is already authorized as an OpenClaw Linked Device on the Hostinger production runtime.

This skill repairs infrastructure state. It does **not** bypass WhatsApp authentication, Meta controls, or provider security.

## Production authority
- Runtime: `hostinger-vps`
- Transport: OpenClaw WhatsApp Linked Device
- Gateway ID: `hostinger-vps`
- App health: `https://www.sahjony.com/whatsapp/health`
- Meta Cloud: non-authoritative and not required

## Immutable session rule
Treat the existing linked WhatsApp session as authoritative state.

Never automatically:
- scan or request a QR code,
- invoke login/link-device commands,
- log out or unlink WhatsApp,
- delete OpenClaw state,
- remove or recreate the OpenClaw container,
- delete or replace Docker volumes,
- migrate the number to another provider,
- claim the number is active from a database row alone.

A new pairing is a separate manual user action and is outside automatic recovery.

## Activation decision tree
1. Read `/whatsapp/health` as a secondary control-plane signal.
2. If `hostinger_openclaw.connected=true`, the business number matches the configured expected number, and `send_ready=true`, activation is already complete.
3. Otherwise inspect the Hostinger runtime directly.
4. Verify Docker is running and locate the existing OpenClaw container. Never create a replacement solely to recover WhatsApp.
5. Set/preserve Docker restart policy as `unless-stopped` or `always`.
6. Run `openclaw channels status --probe` inside the existing container.
7. Treat explicit `WhatsApp ... connected` or `linked, running, connected` as the channel connectivity authority. A missing optional `health:healthy` string must not create a false negative.
8. If the linked channel is not connected, allow exactly one bounded host-level `docker restart` of the existing container, then probe once again.
9. If still disconnected, stop automatic activation and report `linked_whatsapp_session_not_connected_no_relink_attempted`. Do not re-pair.
10. If connected, emit a signed heartbeat with `gateway_id=hostinger-vps`, configured account ID, business number, business name, model, and OpenClaw version.
11. Re-read `/whatsapp/health` and require all acceptance gates below.
12. Write a fresh local last-good marker only after every gate passes.

## Heartbeat identity repair
The production bridge and every health sidecar must default to `hostinger-vps`, never `default`.

The heartbeat is signed using the existing SAHJONY application bridge secret. Never print, log, echo, upload, or expose that secret. The signature format must match the application API exactly:

`sha256=HMAC_SHA256(secret, "<unix_timestamp>.<compact_json_body>")`

Headers:
- `X-SAHJONY-Timestamp`
- `X-SAHJONY-Signature`

## Primary activation tool
Run:

```bash
sudo bash openclaw/hostinger-24x7/whatsapp-number-activate.sh
```

The tool is idempotent and non-destructive. It does not use Meta Cloud and does not alter WhatsApp authentication.

Optional runtime inputs:
- `SAHJONY_GATEWAY_ID` (default `hostinger-vps`)
- `SAHJONY_WHATSAPP_ACCOUNT_ID`
- `SAHJONY_WHATSAPP_BUSINESS_NUMBER`
- `SAHJONY_WHATSAPP_BUSINESS_NAME`
- `SAHJONY_APP_URL`
- `OPENCLAW_CONTAINER`

## Acceptance gates
Do not report the phone number as active until:
1. Hostinger normal OS is reachable/authenticated.
2. Docker daemon is running.
3. The pre-existing OpenClaw container is running and preserved.
4. `openclaw channels status --probe` explicitly reports WhatsApp connected.
5. The signed production heartbeat is accepted under `gateway_id=hostinger-vps`.
6. `/whatsapp/health` reports:
   - `status=ok`
   - `hostinger_independent_runtime=true`
   - `send_ready=true`
   - `webhook_ready=true`
   - `hostinger_openclaw.connected=true`
   - the configured business number on `hostinger_openclaw.business_number`
7. For 24/7 readiness, Docker restart policy is persistent and the guardian has a fresh last-good signal.

## Recovery escalation
If normal SSH is unavailable, do not improvise a destructive workaround.

- First reconcile current Hostinger actions and GitHub maintenance runs.
- Never run two Recovery operations concurrently.
- If there is no active Hostinger maintenance action and normal SSH remains unavailable, use the canonical race-safe `Hostinger WhatsApp Recovery V7` workflow exactly once.
- After V7 restores normal SSH, return to the activation tool above.

## Dashboard use
The OpenClaw dashboard may be used to observe the linked channel and its status. It is not required for automatic activation. Dashboard actions must preserve the existing linked session; do not use logout/unlink/re-pair controls during routine recovery.

## Safety and truthfulness
- Do not infer connectivity from a stale heartbeat.
- Do not treat Meta configuration as a prerequisite.
- Do not mark production ready from Vercel health alone when Hostinger has not been locally verified.
- Do not expose credentials in logs, workflow outputs, artifacts, or error messages.
- Do not send a customer message merely as a health check unless the owner explicitly requests that message.
