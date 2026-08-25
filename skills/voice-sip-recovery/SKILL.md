# SAHJONY Voice SIP Recovery

Use this skill when SAHJONY inbound voice shows Bland SIP 400/4xx errors, `/voice/inbound/configure` 5xx errors, callers hear provider/billing messages, or the OpenAI Realtime route cannot be verified.

## Objective
Restore Bland telephony transport to OpenAI Realtime without exposing credentials, enabling Bland conversational AI, or sharing the production phone number externally before end-to-end verification passes.

## Recovery sequence
1. Confirm the deployed commit and production deployment are aligned.
2. Call `GET /voice/inbound/doctor` with owner authorization. This is read-only.
3. Require `preflight_ok=true`. The doctor validates the OpenAI SIP destination using Bland's destination parser and determines whether the number needs an SIP `attach` or `update`.
4. If `current_inbound_exists=true`, use SIP update. Never create a duplicate inbound direction by blindly attaching again.
5. If no inbound direction exists, attach one canonical route to `sip:<OPENAI_PROJECT_ID>@sip.api.openai.com;transport=tls`, TLS port 5061 with secure media enabled.
6. Call `GET /voice/inbound/status` and require `sip_verified=true`.
7. Verify the OpenAI incoming-call webhook accepts a real `realtime.call.incoming` event.
8. Perform one real inbound call and confirm the first audible content is the SAHJONY Global Trade greeting, with no provider, credit, balance, or technical message.
9. Only after step 8 may the number be treated as externally shareable.

## Failure handling
- If destination preflight fails, do not mutate routing. Preserve and surface Bland's sanitized provider message.
- If SIP update/attach fails, do not detach the existing route automatically. Fail closed and preserve the previous configuration.
- If the provider reports entitlement, organization, billing, or account restrictions, reconcile the Bland organization/workspace against the funded account before making additional routing changes.
- A missing `BLAND_PATHWAY_ID` is not a reason to move conversational voice to Bland. OpenAI Realtime remains the conversational engine; Bland is transport only.
- Never log API keys, authorization headers, passwords, or SIP credentials.

## CLI doctor
Use `node tools/voice-sip-doctor.mjs --url=<production-url> --token=<owner-token>` for read-only diagnosis. Add `--apply=true` only after the read-only doctor reports `preflight_ok=true`.

## Definition of done
- Bland SIP destination preflight passes.
- SIP write returns 2xx and verification reports `sip_verified=true`.
- OpenAI accepts the incoming SIP call.
- Real inbound test reaches SAHJONY Global Trade.
- Voice control-plane 5xx count returns to zero.
