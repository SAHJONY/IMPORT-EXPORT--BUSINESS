"""Focused tests for WhatsApp voice-note support (Cloud API path).

All network I/O (Graph API, Whisper, TTS) is mocked. Covers:
- audio message detection
- transcription -> reply -> audio-out wiring
- audio-out Graph payload shape
- text-in -> text-out behavior unchanged
- fail-closed: flag OFF, missing key, transcription/TTS failure
"""

import asyncio

import pytest

import whatsapp_api
import whatsapp_audio


class FakeBackend:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.inserted = []

    async def select(self, table, *, params=None):
        return list(self.rows)

    async def insert(self, table, row):
        self.inserted.append((table, row))
        return [row]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def audio_env(monkeypatch):
    monkeypatch.setenv("WHATSAPP_AI_AUTO_REPLY_ENABLED", "true")
    monkeypatch.setenv("WHATSAPP_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.delenv("OWNER_WHATSAPP_E164", raising=False)
    monkeypatch.setattr(whatsapp_api, "get_backend", lambda: FakeBackend())
    monkeypatch.setattr(whatsapp_api, "_send_ready", lambda cfg: True)
    monkeypatch.setattr(whatsapp_api, "hermes_configured", lambda: True)


CFG = {"phone_number_id": "12345", "access_token": "tok", "graph_api_version": "v21.0"}


# ---------------------------------------------------------------------------
# Pure detection helpers
# ---------------------------------------------------------------------------

def test_extract_audio_media_id_from_audio_message():
    msg = {"type": "audio", "audio": {"id": "media_1", "mime_type": "audio/ogg", "voice": True}}
    assert whatsapp_audio.extract_audio_media_id(msg) == "media_1"


def test_extract_audio_media_id_none_for_text():
    assert whatsapp_audio.extract_audio_media_id({"type": "text", "text": {"body": "hola"}}) is None


def test_extract_audio_media_id_none_when_missing():
    assert whatsapp_audio.extract_audio_media_id({"type": "audio"}) is None
    assert whatsapp_audio.extract_audio_media_id({}) is None


def test_audio_pipeline_ready_reflects_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert whatsapp_audio.audio_pipeline_ready() is True
    monkeypatch.delenv("OPENAI_API_KEY")
    assert whatsapp_audio.audio_pipeline_ready() is False


def test_bridge_message_is_audio_markers():
    assert whatsapp_audio.bridge_message_is_audio({"type": "ptt"}) is True
    assert whatsapp_audio.bridge_message_is_audio({"type": "audio"}) is True
    assert whatsapp_audio.bridge_message_is_audio({"mimetype": "audio/ogg; codecs=opus"}) is True
    assert whatsapp_audio.bridge_message_is_audio({"type": "text", "body": "hola"}) is False
    assert whatsapp_audio.bridge_message_is_audio({"type": "image", "hasMedia": True}) is False
    assert whatsapp_audio.bridge_message_is_audio({}) is False


# ---------------------------------------------------------------------------
# Full audio pipeline: voice note -> transcription -> spoken reply
# ---------------------------------------------------------------------------

def test_process_inbound_audio_replies_with_audio_not_text(audio_env, monkeypatch):
    calls = {"download": 0, "transcribe": 0, "tts": 0}
    sent_audio = []
    sent_text = []

    async def fake_download(version, token, media_id):
        calls["download"] += 1
        assert media_id == "media_1"
        return b"oggbytes", "audio/ogg"

    async def fake_transcribe(audio_bytes, filename="voice-note.ogg"):
        calls["transcribe"] += 1
        assert audio_bytes == b"oggbytes"
        return "¿Cuánto cuesta el azúcar?"

    async def fake_reply(text, contact_name, **kwargs):
        assert text == "¿Cuánto cuesta el azúcar?"
        return "El azúcar está a $45 el saco de 25 kg."

    async def fake_tts(text):
        calls["tts"] += 1
        assert "azúcar" in text
        return b"mp3bytes"

    async def fake_send_audio(cfg, **kwargs):
        sent_audio.append(kwargs)

    async def fake_send_text(cfg, **kwargs):
        sent_text.append(kwargs)

    monkeypatch.setattr(whatsapp_audio, "download_whatsapp_media", fake_download)
    monkeypatch.setattr(whatsapp_audio, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(whatsapp_audio, "synthesize_speech", fake_tts)
    monkeypatch.setattr(whatsapp_api, "generate_sofia_reply", fake_reply)
    monkeypatch.setattr(whatsapp_api, "_send_audio", fake_send_audio)
    monkeypatch.setattr(whatsapp_api, "_send_text", fake_send_text)

    run(whatsapp_api._process_inbound(
        CFG,
        phone="5351234567",
        message_id="wamid.audio1",
        message_type="audio",
        text="[audio received]",
        contact_name="Dayana",
        audio_media_id="media_1",
    ))

    assert calls == {"download": 1, "transcribe": 1, "tts": 1}
    assert len(sent_audio) == 1
    assert sent_audio[0]["to"] == "5351234567"
    assert sent_audio[0]["audio"] == b"mp3bytes"
    assert sent_audio[0]["transcript"] == "El azúcar está a $45 el saco de 25 kg."
    assert sent_audio[0]["autonomous"] is True
    assert sent_text == [], "audio-in must never produce a text reply"


def test_process_inbound_text_path_unchanged(audio_env, monkeypatch):
    sent_audio = []
    sent_text = []
    calls = {"transcribe": 0, "tts": 0}

    async def fake_reply(text, contact_name, **kwargs):
        return "Hola, ¿en qué le ayudo?"

    async def fake_send_audio(cfg, **kwargs):
        sent_audio.append(kwargs)

    async def fake_send_text(cfg, **kwargs):
        sent_text.append(kwargs)

    async def fake_transcribe(audio_bytes, filename="voice-note.ogg"):
        calls["transcribe"] += 1
        return "nope"

    monkeypatch.setattr(whatsapp_api, "generate_sofia_reply", fake_reply)
    monkeypatch.setattr(whatsapp_api, "_send_audio", fake_send_audio)
    monkeypatch.setattr(whatsapp_api, "_send_text", fake_send_text)
    monkeypatch.setattr(whatsapp_audio, "transcribe_audio", fake_transcribe)

    run(whatsapp_api._process_inbound(
        CFG,
        phone="5351234567",
        message_id="wamid.text1",
        message_type="text",
        text="Hola",
        contact_name="Dayana",
    ))

    assert len(sent_text) == 1
    assert sent_text[0]["body"] == "Hola, ¿en qué le ayudo?"
    assert sent_text[0]["to"] == "5351234567"
    assert sent_audio == []
    assert calls["transcribe"] == 0


# ---------------------------------------------------------------------------
# Fail-closed behavior
# ---------------------------------------------------------------------------

def test_audio_flag_off_records_but_never_replies(monkeypatch):
    monkeypatch.setenv("WHATSAPP_AI_AUTO_REPLY_ENABLED", "false")
    monkeypatch.setenv("WHATSAPP_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.delenv("OWNER_WHATSAPP_E164", raising=False)
    backend = FakeBackend()
    monkeypatch.setattr(whatsapp_api, "get_backend", lambda: backend)
    monkeypatch.setattr(whatsapp_api, "_send_ready", lambda cfg: True)

    calls = {"download": 0, "reply": 0, "send_audio": 0, "send_text": 0}

    async def fake_download(*args, **kwargs):
        calls["download"] += 1
        return b"x", "audio/ogg"

    async def fake_reply(*args, **kwargs):
        calls["reply"] += 1
        return "x"

    async def fake_send_audio(cfg, **kwargs):
        calls["send_audio"] += 1

    async def fake_send_text(cfg, **kwargs):
        calls["send_text"] += 1

    monkeypatch.setattr(whatsapp_audio, "download_whatsapp_media", fake_download)
    monkeypatch.setattr(whatsapp_api, "generate_sofia_reply", fake_reply)
    monkeypatch.setattr(whatsapp_api, "_send_audio", fake_send_audio)
    monkeypatch.setattr(whatsapp_api, "_send_text", fake_send_text)

    run(whatsapp_api._process_inbound(
        CFG,
        phone="5351234567",
        message_id="wamid.audio2",
        message_type="audio",
        text="[audio received]",
        contact_name="Dayana",
        audio_media_id="media_1",
    ))

    assert calls == {"download": 0, "reply": 0, "send_audio": 0, "send_text": 0}
    # The turn is still recorded for memory/visibility.
    tables = {table for table, _ in backend.inserted}
    assert "whatsapp_leads" in tables
    assert "business_events" in tables


def test_audio_missing_openai_key_fail_closed(monkeypatch):
    monkeypatch.setenv("WHATSAPP_AI_AUTO_REPLY_ENABLED", "true")
    monkeypatch.setenv("WHATSAPP_AUTOMATION_ENABLED", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OWNER_WHATSAPP_E164", raising=False)
    backend = FakeBackend()
    monkeypatch.setattr(whatsapp_api, "get_backend", lambda: backend)
    monkeypatch.setattr(whatsapp_api, "_send_ready", lambda cfg: True)

    calls = {"download": 0, "send_audio": 0, "send_text": 0}

    async def fake_download(*args, **kwargs):
        calls["download"] += 1
        return b"x", "audio/ogg"

    async def fake_send_audio(cfg, **kwargs):
        calls["send_audio"] += 1

    async def fake_send_text(cfg, **kwargs):
        calls["send_text"] += 1

    monkeypatch.setattr(whatsapp_audio, "download_whatsapp_media", fake_download)
    monkeypatch.setattr(whatsapp_api, "_send_audio", fake_send_audio)
    monkeypatch.setattr(whatsapp_api, "_send_text", fake_send_text)

    run(whatsapp_api._process_inbound(
        CFG,
        phone="5351234567",
        message_id="wamid.audio3",
        message_type="audio",
        text="[audio received]",
        contact_name="Dayana",
        audio_media_id="media_1",
    ))

    assert calls == {"download": 0, "send_audio": 0, "send_text": 0}


def test_audio_transcription_failure_sends_nothing(audio_env, monkeypatch):
    async def fake_download(version, token, media_id):
        return b"oggbytes", "audio/ogg"

    async def fake_transcribe(audio_bytes, filename="voice-note.ogg"):
        raise RuntimeError("whisper boom")

    sent_audio = []
    sent_text = []

    async def fake_send_audio(cfg, **kwargs):
        sent_audio.append(kwargs)

    async def fake_send_text(cfg, **kwargs):
        sent_text.append(kwargs)

    monkeypatch.setattr(whatsapp_audio, "download_whatsapp_media", fake_download)
    monkeypatch.setattr(whatsapp_audio, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(whatsapp_api, "_send_audio", fake_send_audio)
    monkeypatch.setattr(whatsapp_api, "_send_text", fake_send_text)

    run(whatsapp_api._process_inbound(
        CFG,
        phone="5351234567",
        message_id="wamid.audio4",
        message_type="audio",
        text="[audio received]",
        contact_name="Dayana",
        audio_media_id="media_1",
    ))

    assert sent_audio == []
    assert sent_text == []


def test_audio_tts_failure_sends_nothing_not_text_fallback(audio_env, monkeypatch):
    async def fake_download(version, token, media_id):
        return b"oggbytes", "audio/ogg"

    async def fake_transcribe(audio_bytes, filename="voice-note.ogg"):
        return "hola"

    async def fake_reply(text, contact_name, **kwargs):
        return "Hola, ¿en qué le ayudo?"

    async def fake_tts(text):
        raise RuntimeError("tts boom")

    sent_audio = []
    sent_text = []

    async def fake_send_audio(cfg, **kwargs):
        sent_audio.append(kwargs)

    async def fake_send_text(cfg, **kwargs):
        sent_text.append(kwargs)

    monkeypatch.setattr(whatsapp_audio, "download_whatsapp_media", fake_download)
    monkeypatch.setattr(whatsapp_audio, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(whatsapp_api, "generate_sofia_reply", fake_reply)
    monkeypatch.setattr(whatsapp_audio, "synthesize_speech", fake_tts)
    monkeypatch.setattr(whatsapp_api, "_send_audio", fake_send_audio)
    monkeypatch.setattr(whatsapp_api, "_send_text", fake_send_text)

    run(whatsapp_api._process_inbound(
        CFG,
        phone="5351234567",
        message_id="wamid.audio5",
        message_type="audio",
        text="[audio received]",
        contact_name="Dayana",
        audio_media_id="media_1",
    ))

    assert sent_audio == []
    assert sent_text == [], "TTS failure must not fall back to text"


# ---------------------------------------------------------------------------
# Audio-out Graph payload shape
# ---------------------------------------------------------------------------

def test_send_audio_payload_shape(audio_env, monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(whatsapp_api, "get_backend", lambda: backend)
    async def fake_eligibility(to):
        return {"recipient": "5351234567", "mode": "session"}

    monkeypatch.setattr(
        whatsapp_api, "_assert_compliant_session_outbound", fake_eligibility
    )
    uploads = []
    meta_calls = []

    async def fake_upload(version, phone_number_id, token, audio_bytes, mime_type="audio/mpeg"):
        uploads.append({
            "version": version,
            "phone_number_id": phone_number_id,
            "token": token,
            "bytes": audio_bytes,
            "mime_type": mime_type,
        })
        return "media_out_1"

    async def fake_meta_json(url, *, access_token="", method="GET", payload=None, params=None):
        meta_calls.append({"url": url, "method": method, "payload": payload})
        return {"messages": [{"id": "wamid.out1"}]}

    monkeypatch.setattr(whatsapp_audio, "upload_media", fake_upload)
    monkeypatch.setattr(whatsapp_api, "_meta_json", fake_meta_json)
    # Avoid the real memory-consolidation hook touching anything.
    monkeypatch.setattr(whatsapp_api.sofia_memory, "queue_consolidation", lambda **kwargs: None)

    result = run(whatsapp_api._send_audio(
        CFG, to="+5351234567", audio=b"mp3bytes",
        transcript="El azúcar está a $45.",
        autonomous=True,
    ))

    assert uploads[0]["version"] == "v21.0"
    assert uploads[0]["phone_number_id"] == "12345"
    assert uploads[0]["bytes"] == b"mp3bytes"
    assert len(meta_calls) == 1
    payload = meta_calls[0]["payload"]
    assert payload["type"] == "audio"
    assert payload["audio"] == {"id": "media_out_1"}
    assert payload["to"] == "5351234567"
    assert result["status"] == "submitted"
    # Outbound recorded as audio with the spoken transcript for brain history.
    audio_rows = [
        row for table, row in backend.inserted
        if table == "whatsapp_messages" and row.get("message_type") == "audio"
    ]
    assert len(audio_rows) == 1
    assert audio_rows[0]["text"] == "El azúcar está a $45."
    assert audio_rows[0]["direction"] == "outbound"
