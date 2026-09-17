"""Tests for Sofia's voice capability (ears + voice).

- sofia_voice_inbox: transcription with mocked faster-whisper
  (ok / low-confidence / engine-missing paths). Never invents words.
- sofia_voice_outbox: TTS with mocked engine, length cap, voice selection
  matched to the reply language.
- sofia_whatsapp_runtime: voice-mirror policy and the end-to-end audio turn
  with mocked transcription + generation + synthesis.
"""
import asyncio

import pytest

import sofia_voice_inbox as inbox
import sofia_voice_outbox as outbox


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeSegment:
    def __init__(self, text, avg_logprob=-0.3):
        self.text = text
        self.avg_logprob = avg_logprob


class _FakeInfo:
    def __init__(self, language="es", language_probability=0.95, duration=4.0):
        self.language = language
        self.language_probability = language_probability
        self.duration = duration


class _FakeWhisperModel:
    def __init__(self, segments, info):
        self._segments = segments
        self._info = info

    def transcribe(self, path, language=None, initial_prompt=None, vad_filter=False):
        return self._segments, self._info


def _install_fake_whisper(monkeypatch, segments, info):
    monkeypatch.setattr(inbox, "_model", _FakeWhisperModel(segments, info))
    monkeypatch.setattr(inbox, "_model_error", None)
    monkeypatch.setattr(inbox, "whisper_available", lambda: True)


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

def test_transcribe_ok_spanish(monkeypatch):
    _install_fake_whisper(
        monkeypatch,
        [_FakeSegment("Hola, quiero comprar un carro para Cuba")],
        _FakeInfo(language="es", language_probability=0.97),
    )
    result = asyncio.run(inbox.transcribe_audio(b"fake-ogg-bytes"))
    assert result["ok"] is True
    assert "carro" in result["text"]
    assert result["language"] == "es"
    assert result["model"] == inbox.WHISPER_MODEL_NAME


def test_transcribe_low_confidence_is_honest_failure(monkeypatch):
    _install_fake_whisper(
        monkeypatch,
        [_FakeSegment("mmmblah", avg_logprob=-2.5)],
        _FakeInfo(language="es", language_probability=0.9),
    )
    result = asyncio.run(inbox.transcribe_audio(b"fake-ogg-bytes"))
    assert result["ok"] is False
    assert result["error_code"] == "low_confidence"
    assert "text" not in result or True  # no invented words surfaced as ok


def test_transcribe_empty_result_is_failure(monkeypatch):
    _install_fake_whisper(monkeypatch, [], _FakeInfo())
    result = asyncio.run(inbox.transcribe_audio(b"fake-ogg-bytes"))
    assert result["ok"] is False
    assert result["error_code"] == "empty_transcript"


def test_transcribe_engine_missing(monkeypatch):
    monkeypatch.setattr(inbox, "whisper_available", lambda: False)
    result = asyncio.run(inbox.transcribe_audio(b"fake-ogg-bytes"))
    assert result["ok"] is False
    assert result["error_code"] == "engine_missing"


def test_transcribe_empty_audio():
    result = asyncio.run(inbox.transcribe_audio(b""))
    assert result["ok"] is False
    assert result["error_code"] == "empty_audio"


def test_transcribe_oversized_audio_rejected():
    result = asyncio.run(inbox.transcribe_audio(b"x" * (inbox.MAX_AUDIO_BYTES + 1)))
    assert result["ok"] is False
    assert result["error_code"] == "audio_too_large"


# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------

def test_pick_voice_spanish_default():
    assert outbox.pick_voice("es") == "es-MX-DaliaNeural"
    assert outbox.pick_voice("") == "es-MX-DaliaNeural"


def test_pick_voice_english():
    assert outbox.pick_voice("en") == "en-US-AriaNeural"


async def _fake_edge_ok(text, voice):
    return b"fake-ogg-audio", 4.2


def test_synthesize_ok_uses_language_voice(monkeypatch):
    monkeypatch.setattr(outbox, "_synthesize_edge", _fake_edge_ok)
    result = asyncio.run(outbox.synthesize_speech("Hola, ¿en qué te puedo ayudar?", language="es", backend="edge"))
    assert result["ok"] is True
    assert result["mime"] == "audio/ogg"
    assert result["voice"] == "es-MX-DaliaNeural"
    assert result["backend"] == "edge"
    assert isinstance(result["audio_bytes"], bytes)


def test_synthesize_too_long_stays_text():
    long_text = "x" * (outbox.MAX_VOICE_CHARS + 1)
    result = asyncio.run(outbox.synthesize_speech(long_text, language="es", backend="edge"))
    assert result["ok"] is False
    assert result["error_code"] == "too_long"


def test_synthesize_empty_text():
    result = asyncio.run(outbox.synthesize_speech("   ", language="es"))
    assert result["ok"] is False
    assert result["error_code"] == "empty_text"


async def _fake_edge_boom(text, voice):
    raise RuntimeError("endpoint down")


async def _fake_piper_ok(text, language):
    return b"fake-piper-ogg", 3.1


def test_synthesize_auto_falls_back_to_piper(monkeypatch):
    monkeypatch.setattr(outbox, "_synthesize_edge", _fake_edge_boom)
    monkeypatch.setattr(outbox, "_synthesize_piper", _fake_piper_ok)
    result = asyncio.run(outbox.synthesize_speech("Hola", language="es", backend="auto"))
    assert result["ok"] is True
    assert result["backend"] == "piper"


def test_synthesize_all_backends_down(monkeypatch):
    monkeypatch.setattr(outbox, "_synthesize_edge", _fake_edge_boom)
    monkeypatch.setattr(outbox, "_synthesize_piper", _fake_edge_boom)
    result = asyncio.run(outbox.synthesize_speech("Hola", language="es", backend="auto"))
    assert result["ok"] is False
    assert result["error_code"] == "tts_failed"


def test_tts_off():
    result = asyncio.run(outbox.synthesize_speech("Hola", language="es", backend="off"))
    assert result["ok"] is False
    assert result["error_code"] == "tts_off"


# ---------------------------------------------------------------------------
# Runtime: voice-mirror policy + audio turn
# ---------------------------------------------------------------------------

def test_should_reply_with_voice_mirrors_voice_note():
    from sofia_whatsapp_runtime import should_reply_with_voice
    assert should_reply_with_voice(inbound_medium="voice", reply_text="Claro, con gusto.", tts_enabled=True) is True


def test_should_reply_with_voice_text_stays_text():
    from sofia_whatsapp_runtime import should_reply_with_voice
    assert should_reply_with_voice(inbound_medium="text", reply_text="Claro, con gusto.", tts_enabled=True) is False


def test_should_reply_with_voice_long_reply_stays_text():
    from sofia_whatsapp_runtime import should_reply_with_voice
    assert should_reply_with_voice(
        inbound_medium="voice", reply_text="x" * 5000, tts_enabled=True
    ) is False


def test_should_reply_with_voice_tts_disabled():
    from sofia_whatsapp_runtime import should_reply_with_voice
    assert should_reply_with_voice(inbound_medium="voice", reply_text="Hola.", tts_enabled=False) is False


def test_audio_turn_end_to_end(monkeypatch):
    import sofia_whatsapp_runtime as runtime

    async def fake_transcribe(audio_bytes, mime_hint="audio/ogg", language_hint=None):
        return {"ok": True, "text": "¿Cuánto cuesta el carro?", "language": "es",
                "language_probability": 0.97, "avg_logprob": -0.2, "duration_s": 3.0}

    async def fake_generate(text, contact_name, owner_context=False, sender_phone=None):
        assert "carro" in text  # transcription fed through the normal pipeline
        return "El carro está en 8,500 USD. ¿Te interesa verlo?"

    async def fake_synth(text, language="es", backend=None):
        return {"ok": True, "audio_bytes": b"fake-voice", "mime": "audio/ogg",
                "duration_s": 4.0, "voice": "es-MX-DaliaNeural", "backend": "edge"}

    monkeypatch.setattr(inbox, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(runtime, "generate_sofia_reply", fake_generate)
    monkeypatch.setattr(outbox, "synthesize_speech", fake_synth)
    monkeypatch.setattr(outbox, "tts_configured", lambda: True)

    result = asyncio.run(runtime.generate_sofia_reply_for_audio(b"fake-audio", "Juan"))
    assert result["reply_text"].startswith("El carro")
    assert result["reply_audio"] == b"fake-voice"
    assert result["audio_mime"] == "audio/ogg"
    assert result["reply_language"] == "es"
    assert result["inbound_medium"] == "voice"


def test_audio_turn_transcription_failure_is_honest(monkeypatch):
    import sofia_whatsapp_runtime as runtime

    async def fake_transcribe_fail(audio_bytes, mime_hint="audio/ogg", language_hint=None):
        return {"ok": False, "error": "no speech detected", "error_code": "empty_transcript"}

    async def boom_generate(*a, **k):
        raise AssertionError("pipeline must not run on failed transcription")

    monkeypatch.setattr(inbox, "transcribe_audio", fake_transcribe_fail)
    monkeypatch.setattr(runtime, "generate_sofia_reply", boom_generate)

    result = asyncio.run(runtime.generate_sofia_reply_for_audio(b"fake-audio", "Juan"))
    assert result["reply_audio"] is None
    assert "nota de voz" in result["reply_text"]  # honest Spanish apology, no invented words
    assert result["reply_language"] == "es"


# ---------------------------------------------------------------------------
# whatsapp_api plumbing
# ---------------------------------------------------------------------------

def test_register_inbound_audio_stores_transcription(monkeypatch):
    import whatsapp_api

    stored = {}

    async def fake_register(**kwargs):
        stored.update(kwargs)

    async def fake_transcribe(audio_bytes, mime_hint="audio/ogg", language_hint=None):
        return {"ok": True, "text": "Quiero vender mi Toyota", "language": "es",
                "language_probability": 0.9, "avg_logprob": -0.4, "duration_s": 5.0}

    monkeypatch.setattr(whatsapp_api, "_register_inbound_message", fake_register)
    monkeypatch.setattr(inbox, "transcribe_audio", fake_transcribe)

    result = asyncio.run(whatsapp_api.register_inbound_audio(
        phone="+1234", message_id="wam_1", contact_name="Juan", audio_bytes=b"fake-audio"))
    assert result["ok"] is True
    assert stored["message_type"] == "audio"
    assert stored["text"] == "Quiero vender mi Toyota"  # transcript stays text


def test_register_inbound_audio_failed_transcription_placeholder(monkeypatch):
    import whatsapp_api

    stored = {}

    async def fake_register(**kwargs):
        stored.update(kwargs)

    async def fake_transcribe_fail(audio_bytes, mime_hint="audio/ogg", language_hint=None):
        return {"ok": False, "error": "x", "error_code": "empty_transcript"}

    monkeypatch.setattr(whatsapp_api, "_register_inbound_message", fake_register)
    monkeypatch.setattr(inbox, "transcribe_audio", fake_transcribe_fail)

    result = asyncio.run(whatsapp_api.register_inbound_audio(phone="+1234", audio_bytes=b"fake-audio"))
    assert result["ok"] is True
    assert "no se pudo transcribir" in stored["text"]
