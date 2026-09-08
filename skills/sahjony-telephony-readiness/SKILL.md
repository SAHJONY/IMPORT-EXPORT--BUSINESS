---
name: sahjony-telephony-readiness
description: Preflight, route selection, failover, and meeting-readiness controls for SAHJONY priority phone calls across OpenAI Realtime SIP, Telnyx TeXML, and the production voice fallback.
---

# SAHJONY Telephony Readiness

Use this skill before any priority supplier, buyer, logistics, partner, or owner call.

## Non-negotiable objective
Never move a priority call onto a new telephony route unless a real end-to-end test has passed. Preserve the known-good production route as fallback until the replacement is verified.

## Route order
1. Preferred native route: PSTN DID -> Telnyx TeXML Application -> TeXML Bin -> OpenAI Realtime SIP -> Sofia.
2. Fallback: existing production inbound assistant/number.
3. Never treat a Caller-ID-only number as inbound-capable.

## OpenAI target
The SIP Request-URI must preserve the project user exactly:
`sip:proj_wo5NVFLZGfkoDpPyGghDAzuw@sip.api.openai.com;transport=tls`

## TeXML rules
- Prefer a Telnyx TeXML Application bound to the DID.
- When using `TeXML Bin URL`, select the existing Bin inside Telnyx; do not assume the `/v2/media/...xml` URL is publicly fetchable.
- The Bin must contain a `<Dial><Sip>` instruction targeting the full OpenAI SIP URI.
- Do not mix TeXML and Voice API/Call Control commands on the same call.
- Do not enable recording, transcription, voicemail, T.38, comfort noise, or Telnyx AI for the native OpenAI route unless separately required.

## Preflight gates
A route is READY only when all are true:
1. DID is active and assigned to the intended application.
2. TeXML application is active and references the intended Bin.
3. TeXML contains the exact OpenAI SIP target.
4. OpenAI webhook/gateway health returns HTTP 200.
5. `realtime.call.incoming` webhook is configured for the correct OpenAI project.
6. A real PSTN test reaches Sofia, two-way audio works, interruption works, and no material echo/loop exists.
7. Fallback line remains available until the native route passes.

## Fail-closed behavior
If any gate is unknown or fails, mark the native route NOT_READY and keep the priority meeting on the fallback. Never claim cutover success from configuration screens alone.
