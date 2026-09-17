# Sofia media vision ("eyes") — build notes

**Branch:** `build/sofia-media-vision` (not merged; needs Juan's approval to merge/deploy)
**Date:** 2026-09-17
**Request:** Juan — "Add Sofia a tool or skills to see photos and videos and images to evaluate a business proposal."

## What was built

Sofia can now look at photos and videos a customer sends over WhatsApp and
reference what she actually saw in her reply ("Veo en las fotos que..."), in the
customer's language.

### New module: `sofia_media_evaluator.py`

`async def evaluate_media(*, media_bytes, media_kind, track, user_text="", language="es") -> dict`

Returns `{ok, summary, details, condition_notes, red_flags, deal_relevance,
limitations, model, media_kind, frames_evaluated, caveat}`.

- **Vision backend (FREE):** NVIDIA NIM chat-completions with a vision-capable
  model, same key/URL pattern as `sofia_hermes_nim_brain.py`.
  Verified against NVIDIA's public `/v1/models` catalog on 2026-09-17 — these
  vision models are listed:
  `meta/llama-3.2-11b-vision-instruct` (default), `meta/llama-3.2-90b-vision-instruct`,
  `microsoft/phi-3-vision-128k-instruct`, `adept/fuyu-8b`, `microsoft/kosmos-2`.
  Model is env-configurable via `SOFIA_VISION_MODEL`.
- **Honest failure:** no API key / HTTP error / unparseable output → `ok=False`
  with a plain reason (`vision_not_configured`, `vision_backend_error`, …).
  It never fabricates an evaluation.
- **Track-aware prompts:** `car_sale` (vehicle condition: exterior/interior,
  damage, odometer/VIN only if legible), `import_export` (product identity,
  quantity/packaging, document transcription of legible fields only),
  `my_cuba_cash` (receipts: amounts/dates/references transcribed exactly, never
  invented; unreadable flagged), plus a generic default. A `car_sale` prompt
  exists for forward-compatibility; the live track classifier is untouched.
- **Videos:** up to 6 frames extracted with ffmpeg, evaluated as a set.
  ffmpeg 8.1 is present on the VPS (`/usr/bin/ffmpeg`, verified 2026-09-17).
  Without ffmpeg, video returns an honest `video_unavailable:ffmpeg_not_available`.
- **Guardrails:** 12 MB input cap; images downscaled (longest side 1568 px) via
  ffmpeg before upload; prompts forbid inventing anything not visible; every
  `summary` carries the caveat: photos alone are not a binding condition
  certification — first visual impression, not an inspection.
- `health()` reports configuration state.

### Media plumbing: `whatsapp_api.py`

- `register_inbound_media(*, message_id, phone, media_kind, mime_type=None,
  media_bytes=None, media_url=None, caption="") -> dict` — tolerant ingest:
  accepts raw bytes or a fetchable URL (fetched with httpx, 12 MB cap), spools
  bytes to `SOFIA_MEDIA_SPOOL_DIR` (default `/tmp/sofia_media`), and inserts a
  metadata row into `whatsapp_media`. If that table doesn't exist the insert is
  skipped without breaking the flow (`metadata_stored: False`); the bytes and
  the returned registration dict still carry everything the runtime needs.
  Never raises.
- Hermes bridge handler: `HermesBridgeEvent.media[]` items are now registered
  (bytes as base64, or `url`/`media_url` fetched). Field shapes are tolerated.
- `_process_inbound(..., media=None)`: `image`/`video` turns with media now
  flow into `generate_sofia_reply` instead of being dropped (previously any
  non-text message returned early with no reply).
- Meta Cloud webhook: image/video descriptors are passed through (caption,
  mime, media id). **Gap:** the webhook only carries a Meta `media_id`, not
  bytes/URL — resolving it needs a Graph API media-URL lookup with the page
  token. Documented as a follow-up; registration records the attempt honestly.
- New internal endpoint `POST /whatsapp/media/evaluate`
  `{message_id, track, user_text, language}` → evaluates spooled media for a
  message (falls back to the spool dir when the metadata table is absent).

### Runtime wiring: `sofia_whatsapp_runtime.py`

- `generate_sofia_reply(..., media=None)` — media is a list of registration
  dicts from `register_inbound_media`.
- After track resolution, each attachment is evaluated (track-aware, in the
  reply language from `detect_reply_language`) and a **MEDIA EVIDENCE** block is
  injected into Sofia's system prompt, instructing her to reference what she saw
  ("Veo en las fotos que..."), keep it short/phone-readable, never overclaim,
  and repeat the no-certification caveat.
- A turn carrying media skips the blind "ask" short-circuit so the customer gets
  a reply about their photos instead of a generic "¿en qué te puedo ayudar?".
- If evaluation fails, the prompt instructs Sofia to say so honestly **in the
  user's language** and ask what they'd like her to look at.
- Audit payload now includes `media_evaluated` / `media_failed` counts.

## What the Hermes gateway must deliver (OPS note)

For live vision replies, each inbound media event must include **one** of:

1. `media[].bytes` — base64-encoded raw bytes, with `kind` (`image`/`video`)
   and preferably `mime_type`; or
2. `media[].url` (or `media_url`) — an HTTPS URL the API host can fetch
   (redirects followed, 30 s timeout, 12 MB cap), with `kind` and `mime_type`.

Optional: `caption`. The runtime evaluates in the same turn; no gateway-side
changes are needed beyond delivering bytes or a fetchable URL. Forbidden: do
not inspect or modify `/root/.hermes`, `/opt/sahjony-hermes`, or hermes units —
the ingest above is the entire contract.

## Env vars

| Var | Default | Purpose |
|---|---|---|
| `NVIDIA_API_KEY` | — | Existing key; vision uses the same account (free tier) |
| `NVIDIA_NIM_BASE_URL` | `https://integrate.api.nvidia.com/v1` | Existing; vision uses the same base |
| `SOFIA_VISION_MODEL` | `meta/llama-3.2-11b-vision-instruct` | Vision model (must be vision-capable) |
| `SOFIA_MEDIA_SPOOL_DIR` | `/tmp/sofia_media` | Where inbound media bytes are spooled |

## Limitations (honest)

- Vision quality = the model + photo quality. Blurry/cropped photos yield
  "unreadable" rather than guesses — by design.
- Video without ffmpeg → clear `video_unavailable` failure (ffmpeg IS on the VPS).
- Meta Cloud webhook media arrives as `media_id` only — needs the Graph lookup
  follow-up before photos via that path are analyzable.
- No live end-to-end vision call was made during the build (no inference spent);
  the backend path is unit-tested with a mocked transport. First live deploy
  should be smoke-tested with one real photo.
- The evaluation is an executive first impression, never an inspection,
  appraisal, or compliance determination.

## How to test

```bash
cd ~/workspace/repos/import-export-business
git checkout build/sofia-media-vision
python3 -m pytest tests/test_sofia_media_vision.py -q   # 27 tests, backend mocked
# Manual: with NVIDIA_API_KEY set —
python3 - <<'EOF'
import asyncio, sofia_media_evaluator as ev
data = open('sample.jpg','rb').read()
print(asyncio.run(ev.evaluate_media(media_bytes=data, media_kind='image',
      track='car_sale', user_text='mira este carro', language='es'))['summary'])
EOF
```

## Decision needed from Juan

1. **Merge + deploy** this branch (it changes Sofia's live reply behavior for
   photo/video messages — currently such messages get no useful reply at all).
2. Nothing else: no new paid service, no secrets added, no sends.
