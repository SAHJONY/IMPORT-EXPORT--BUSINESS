# Sofia Voice — ears + voice for WhatsApp

Sofia can now listen to voice notes and reply with voice messages.
Spanish-first: the Cuba market lives on voice notes.

## Architecture

```
Inbound voice note (ogg/opus)
  → whatsapp_api.register_inbound_audio()      # ingest: bytes or URL → record
  → sofia_voice_inbox.transcribe_audio()       # faster-whisper, LOCAL on VPS
  → generate_sofia_reply_for_audio()           # runtime: text → normal pipeline
  → sofia_whatsapp_runtime.generate_sofia_reply(text, ...)
  → should_reply_with_voice()                  # mirror policy: voice in → voice out
  → sofia_voice_outbox.synthesize_speech()     # edge-tts (primary) / Piper (fallback)
  → ogg/opus voice message → Hermes sends it
```

The transcript/history in `whatsapp_messages` always stores TEXT
(the transcription, or `[nota de voz — no se pudo transcribir]`), so the
conversation stays readable and searchable.

### Inbound: `sofia_voice_inbox.py`

- `transcribe_audio(audio_bytes, mime_hint="audio/ogg")` → dict
- Engine: **faster-whisper** (CTranslate2), runs on VPS CPU, no API key.
- Default model `small` (`SOFIA_WHISPER_MODEL` to change: tiny/base/small/medium).
- Spanish-first: auto language detection with a Spanish business-context
  initial prompt. Reply language is chosen by
  `sofia_track_classifier.detect_language` on the transcript.
- Honest failure: `ok=False` with `error_code` (`empty_audio`,
  `audio_too_large`, `engine_missing`, `empty_transcript`, `low_confidence`,
  `transcription_failed`). Sofia says she couldn't understand — never invents.

### Outbound: `sofia_voice_outbox.py`

- `synthesize_speech(text, language="es")` → ogg/opus bytes for WhatsApp.
- **Winner: edge-tts (primary).** Microsoft neural voices, free, no key,
  zero VPS footprint. `es-MX-DaliaNeural` for Spanish (closest neutral
  Latin-American voice; no `es-CU` exists), `en-US-AriaNeural` for English.
  Chosen for naturalness — a voice note must sound human in the Cuba market.
- **Fallback: Piper (offline).** Fully local, works with no network, but more
  robotic. Used automatically when edge-tts fails (`SOFIA_TTS_BACKEND=auto`).
- Voice cap: replies over `SOFIA_VOICE_MAX_CHARS` (default 900, ≈60s) stay
  text. `should_reply_with_voice()` also enforces text-in → text-out.

### Runtime: `sofia_whatsapp_runtime.py`

- `generate_sofia_reply_for_audio(audio_bytes, contact_name, ...)` — full
  voice turn, never raises.
- `should_reply_with_voice(inbound_medium, reply_text, tts_enabled)` — pure
  policy, unit-tested.

### Plumbing: `whatsapp_api.register_inbound_audio()`

Accepts raw bytes or a fetchable URL from the Hermes gateway. Audio bytes are
NOT persisted — only the transcription is stored.

> **Gateway requirement (Hermes side):** the gateway must hand the voice
> note's bytes (or a fetchable URL) + mime to `register_inbound_audio()`,
> then call `generate_sofia_reply_for_audio()` and send `reply_audio` as a
> WhatsApp audio message when present (always also storing `reply_text`).
> `/root/.hermes` and hermes units were not touched — this wiring is pending
> on the Hermes side.

> **Merge order:** branch `build/sofia-media-vision` adds
> `register_inbound_media()` in the same area of `whatsapp_api.py`. The two
> functions are independent (different names, `audio` vs `image`/`video`
> message types). Merge media-vision first, then this branch.

## VPS install

```bash
# faster-whisper (CPU) + edge-tts + ffmpeg
pip install faster-whisper edge-tts
apt-get install -y ffmpeg          # ogg/opus encode/decode

# optional offline fallback
# - install piper binary (https://github.com/OHF-Voice/piper1-gpl/releases)
# - download a Spanish voice, e.g. es_MX-claude-high.onnx (+ .onnx.json)
# - export SOFIA_PIPER_VOICE=/opt/piper-voices/es_MX-claude-high.onnx

# download the whisper model once (auto-downloads on first use otherwise)
python3 -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"
```

systemd: add to the `sahjony-fallback-whatsapp` unit environment (or
`/etc/sahjony-fallback/env`):

```
SOFIA_WHISPER_MODEL=small
SOFIA_TTS_BACKEND=auto
# SOFIA_TTS_VOICE_ES=es-MX-DaliaNeural   # default
# SOFIA_TTS_VOICE_EN=en-US-AriaNeural    # default
# SOFIA_PIPER_VOICE=/opt/piper-voices/es_MX-claude-high.onnx
```

## Resource footprint (VPS)

| Component | Disk | RAM (in use) | Network |
|---|---|---|---|
| faster-whisper `small` | ~500 MB (model + deps) | ~1 GB during transcription | none (offline) |
| faster-whisper `tiny` (lighter alt) | ~150 MB | ~300 MB | none |
| edge-tts | ~0 (pure Python) | negligible | outbound HTTPS per reply |
| Piper voice | ~60–120 MB per voice | ~200 MB during synthesis | none |
| ffmpeg | ~80 MB system pkg | negligible | none |

Recommended: `small` model. `tiny` is 3x faster but noticeably worse on
Cuban-accented Spanish; `medium` is better but ~1.5 GB disk / 2 GB RAM.

## Limitations

- edge-tts is an unofficial free endpoint: no SLA, could be rate-limited or
  change. Piper fallback covers outages; worst case the reply stays text.
- No `es-CU` neural voice exists; `es-MX-DaliaNeural` is neutral Latin-American.
- Transcription of very noisy audio or heavy slang may fail — Sofia says so
  honestly instead of guessing.
- Voice replies are capped at ~60s; long/complex replies stay text.

## Testing

```bash
python3 -m pytest tests/test_sofia_voice.py -q   # 22 tests, mocked engines
```

Live smoke test (needs installs above + a WhatsApp ogg sample):

```bash
python3 - <<'EOF'
import asyncio
from sofia_voice_inbox import transcribe_audio
from sofia_voice_outbox import synthesize_speech
audio = open("sample.ogg", "rb").read()
print(asyncio.run(transcribe_audio(audio)))
print(asyncio.run(synthesize_speech("Hola, soy Sofía.", language="es"))["backend"])
EOF
```

## Env reference

| Var | Default | Purpose |
|---|---|---|
| `SOFIA_WHISPER_MODEL` | `small` | faster-whisper model |
| `SOFIA_WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `SOFIA_WHISPER_COMPUTE_TYPE` | `int8` | quantization |
| `SOFIA_WHISPER_MIN_LOGPROB` | `-1.0` | confidence floor |
| `SOFIA_VOICE_MAX_BYTES` | 15728640 | max inbound audio (15 MB) |
| `SOFIA_TTS_BACKEND` | `auto` | `auto`/`edge`/`piper`/`off` |
| `SOFIA_TTS_VOICE_ES` | `es-MX-DaliaNeural` | Spanish voice |
| `SOFIA_TTS_VOICE_EN` | `en-US-AriaNeural` | English voice |
| `SOFIA_VOICE_MAX_CHARS` | `900` | voice-reply length cap |
| `SOFIA_PIPER_VOICE` | _(unset)_ | path to Piper `.onnx` voice |
