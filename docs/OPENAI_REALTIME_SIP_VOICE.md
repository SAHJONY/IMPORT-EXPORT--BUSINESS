# SAHJONY Native OpenAI Realtime SIP Voice

## Objective
Run Sofía as a native OpenAI speech-to-speech phone agent, removing the external TTS layer that can introduce robotic cadence and echo.

## Architecture

Phone carrier / SIP trunk -> OpenAI Realtime SIP -> GPT Realtime 2.1 native audio -> caller

The SAHJONY gateway is only the control plane. It receives the verified `realtime.call.incoming` webhook and accepts/configures the call. Audio stays on the native SIP/Reatime media path; the gateway does not transcode or synthesize audio.

## Supabase Edge Function
Production function slug:

`openai-realtime-sip-gateway`

Required server-side secrets:

- `OPENAI_API_KEY`
- `OPENAI_WEBHOOK_SECRET`
- `OPENAI_REALTIME_MODEL=gpt-realtime-2.1`
- `OPENAI_REALTIME_VOICE=marin` (or another supported native OpenAI Realtime voice)

The function rejects unverified webhook events. Do not expose either secret to browser code.

## OpenAI setup

1. Create/configure an OpenAI API project with Realtime access.
2. Add an OpenAI webhook pointing to the production Edge Function endpoint.
3. Store the webhook signing secret in `OPENAI_WEBHOOK_SECRET`.
4. Route the test SIP DID/trunk to the OpenAI Realtime SIP destination shown for that project.
5. Place a real inbound test call.
6. Confirm the function accepts `realtime.call.incoming` and OpenAI returns a successful call accept.
7. Only after the test passes should production inbound traffic be migrated.

## Audio policy

- Native speech-to-speech only.
- No ElevenLabs or Cartesia in this path.
- No artificial ambient sound.
- Server VAD enables natural turn taking and interruption.
- The voice prompt asks for a warm Caribbean/Latina business cadence without caricature.

## Migration safety

The existing Autocalls inbound line must remain untouched until native SIP E2E testing passes. Use a separate test DID or a temporary SIP route first. Rollback is simply restoring the carrier route to the existing inbound path.

## Commercial governance

Sofía must not invent or bind SAHJONY to prices, inventory, capacity, certifications, purchases, payments, contracts, banking instructions, or verified counterparty status. A voice call is not automatically a qualified RFQ, deal, revenue, or collected revenue.
