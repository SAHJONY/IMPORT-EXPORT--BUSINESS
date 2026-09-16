# SAHJONY Native OpenAI Realtime SIP Voice

## Objective
Run Sofía as a native OpenAI speech-to-speech phone agent, removing the external TTS layer that can contribute to robotic cadence and echo.

## Production architecture

Phone carrier / SIP trunk -> OpenAI Realtime SIP -> GPT-Realtime-2.1 native audio -> caller

Control plane:
OpenAI `realtime.call.incoming` webhook -> dedicated Vercel gateway -> verified call accept/configuration

The audio media path stays native to OpenAI Realtime. The SAHJONY gateway does not transcode, synthesize, or add ambient audio.

## Active production gateway

Vercel project: `sahjony-sofia-realtime-voice`

Stable webhook endpoint:

`https://sahjony-sofia-realtime-voice.vercel.app/api/realtime-sip`

OpenAI project SIP destination:

`sip:proj_wo5NVFLZGfkoDpPyGghDAzuw@sip.api.openai.com;transport=tls`

Required server-side environment variables:

- `OPENAI_API_KEY`
- `OPENAI_WEBHOOK_SECRET`
- `OPENAI_REALTIME_MODEL=gpt-realtime-2.1`
- `OPENAI_REALTIME_VOICE=marin`

Do not expose secrets to browser code or commit them to Git.

## Webhook reliability behavior

The gateway uses the official OpenAI SDK to verify the raw webhook body.

- invalid signature -> HTTP 401
- valid non-call event -> HTTP 200 ignored
- valid OpenAI test event without a live `call_id` -> HTTP 200 acknowledged
- real `realtime.call.incoming` with `call_id` -> accept/configure the call through OpenAI Realtime
- OpenAI call-accept failure -> HTTP 502 with sanitized diagnostics

The OpenAI dashboard `Send test event` flow has been validated successfully with HTTP 200.

## Audio policy

- Native speech-to-speech only.
- GPT-Realtime-2.1 for the live audio conversation.
- OpenAI native voice `marin` unless deliberately changed after testing.
- No ElevenLabs/Cartesia on this native route.
- No artificial ambient/background audio.
- Server VAD supports natural turn-taking and interruption.
- Sofía speaks concise Spanish-first business language and switches naturally to English.

## Telephony status

The webhook/control plane is ready. A real SIP-capable DID or trunk is still required for end-to-end phone testing.

Current Autocalls account has no BYO SIP trunk configured. The existing production line must remain untouched until native OpenAI SIP passes a real inbound test.

Safe cutover sequence:

1. Provision or connect a separate test SIP DID/trunk.
2. Route inbound calls to the OpenAI project SIP destination.
3. Place a real inbound call.
4. Verify OpenAI emits `realtime.call.incoming` with a real `call_id`.
5. Confirm gateway accepts the call and native two-way audio works.
6. Validate interruptions, echo, latency, Spanish/English behavior, and call termination.
7. Only then migrate or forward the production number.

## Import-Export integration

The gateway is a dedicated voice microservice of the SAHJONY Import-Export platform. The next application-layer phase is a sideband controller that gives Sofía governed access to CRM/customer recognition, RFQs, supplier intelligence, quotations, logistics context, and post-call logging without exposing privileged secrets to the live audio model.

## Commercial governance

Sofía must not invent or bind SAHJONY to prices, inventory, capacity, certifications, credit, purchases, payments, contracts, refunds, banking instructions, legal conclusions, or verified counterparty status. A voice call is not automatically a qualified RFQ, deal, revenue, or collected revenue.
