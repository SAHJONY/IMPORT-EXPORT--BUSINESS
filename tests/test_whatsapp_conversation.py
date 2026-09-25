"""WhatsApp conversation: owner chat mode + voice-to-voice (feat/whatsapp-conversation).

Owner chat: the bridge poller routes recognized owner messages through the
Sofia brain with owner_context=True, keeps them private (no lead), and queues
a reply — text for text, voice note for voice note.

Voice-to-voice: inbound bridge audio is resolved from the bridge's audio
cache, transcribed with Whisper, answered by the Sofia brain, and the reply is
synthesized (sage @ 1.25) and queued as a native ptt voice bubble. Every
failure mode is fail-closed: no reply without a real transcription and real
synthesized audio.

Source-inspection tests for whatsapp_api.py (it needs heavy server deps to
import); real unit tests for whatsapp_audio (importable).
"""
import re
from pathlib import Path

import pytest

import whatsapp_audio

ROOT = Path(__file__).resolve().parents[1]


def _api_source():
    return (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")


def _handler_source():
    source = _api_source()
    start = source.index("async def _handle_bridge_message(")
    end = source.index("async def _sofia_bridge_poller(")
    return source[start:end]


def _owner_branch():
    handler = _handler_source()
    start = handler.index("# OWNER CONVERSATION")
    end = handler.index("lead_id = await _upsert_whatsapp_lead")
    return handler[start:end]


# ---------------------------------------------------------------------------
# Real unit tests: voice defaults and audio detection
# ---------------------------------------------------------------------------

def test_sofia_voice_is_sage():
    """Juan's permanent voice pick (2026-09-25): sage."""
    assert whatsapp_audio.TTS_VOICE == "sage"


def test_sofia_voice_speed_is_1_25():
    """Juan's permanent speed pick (2026-09-25): 1.25."""
    assert whatsapp_audio.TTS_SPEED == 1.25


def test_tts_speed_clamped_to_openai_range():
    import importlib
    import os
    os.environ["SOFIA_TTS_SPEED"] = "99"
    try:
        reloaded = importlib.reload(whatsapp_audio)
        assert reloaded.TTS_SPEED == 4.0
    finally:
        del os.environ["SOFIA_TTS_SPEED"]
        importlib.reload(whatsapp_audio)


def test_bridge_audio_detection_ptt_and_mime():
    assert whatsapp_audio.bridge_message_is_audio({"type": "ptt"}) is True
    assert whatsapp_audio.bridge_message_is_audio({"type": "audio"}) is True
    assert whatsapp_audio.bridge_message_is_audio({"mimetype": "audio/ogg; codecs=opus"}) is True
    assert whatsapp_audio.bridge_message_is_audio({"type": "imageMessage"}) is False
    assert whatsapp_audio.bridge_message_is_audio({"body": "hola"}) is False
    assert whatsapp_audio.bridge_message_is_audio({}) is False


# ---------------------------------------------------------------------------
# Source inspection: owner chat mode
# ---------------------------------------------------------------------------

def test_owner_branch_uses_owner_context_brain():
    branch = _owner_branch()
    assert "owner_context=True" in branch
    assert "generate_sofia_reply(" in branch


def test_owner_message_never_becomes_lead():
    branch = _owner_branch()
    assert "_upsert_whatsapp_lead" not in branch


def test_owner_inbound_recorded_privately():
    branch = _owner_branch()
    assert "_register_inbound_message(" in branch
    assert "_record_owner_private_whatsapp_event(" in branch


def test_owner_voice_note_gets_voice_reply():
    branch = _owner_branch()
    assert "synthesize_speech" in branch
    assert "_enqueue_hermes_audio(" in branch


def test_owner_text_gets_text_reply():
    branch = _owner_branch()
    assert "_enqueue_hermes_message(" in branch


def test_owner_replies_gated_by_kill_switch():
    branch = _owner_branch()
    assert "_ai_auto_reply_enabled()" in branch


def test_owner_no_longer_dropped():
    handler = _handler_source()
    assert "if await _is_owner_whatsapp(phone):\n        return" not in handler


# ---------------------------------------------------------------------------
# Source inspection: voice-to-voice pipeline
# ---------------------------------------------------------------------------

def test_voice_pipeline_order_transcribe_cognition_synthesize_enqueue():
    handler = _handler_source()
    transcribe_at = handler.index("transcribe_audio(")
    brain_at = handler.index("generate_sofia_reply(")
    synth_at = handler.index("synthesize_speech(")
    enqueue_at = handler.index("_enqueue_hermes_audio(")
    assert transcribe_at < brain_at < synth_at < enqueue_at


def test_audio_resolved_from_bridge_cache_only():
    source = _api_source()
    assert "~/.hermes/audio_cache" in source
    # Path traversal guard: only paths inside the cache dir are read.
    assert "cache not in path.parents" in source


def test_oversized_audio_rejected():
    source = _api_source()
    assert "MAX_AUDIO_BYTES" in source
    assert whatsapp_audio.MAX_AUDIO_BYTES == 20 * 1024 * 1024


def test_audio_enqueue_carries_media_fields():
    source = _api_source()
    start = source.index("async def _enqueue_hermes_audio(")
    end = source.index("async def _enqueue_hermes_message(")
    fn = source[start:end]
    assert '"media_type": "audio"' in fn
    assert '"media_base64": str(audio_b64)' in fn
    # Same compliance gate and dedupe as the text path.
    assert "_assert_compliant_session_outbound(to)" in fn
    assert "_outbox_duplicate(recipient, fingerprint)" in fn


def test_audio_enqueue_validates_payload_size():
    source = _api_source()
    start = source.index("async def _enqueue_hermes_audio(")
    fn = source[start:source.index("async def _enqueue_hermes_message(")]
    assert "1_000 <= len(raw) <= 1_500_000" in fn


def test_transcription_failure_is_fail_closed():
    handler = _handler_source()
    # A failed transcription records "[audio received]" and never replies.
    assert "_record_untranscribed_bridge_audio(msg)" in handler
    # TTS/enqueue failures are swallowed, never retried as text.
    assert re.search(r"except Exception:\n\s+pass\n        return", handler)


def test_no_text_regression():
    handler = _handler_source()
    # The text path still exists: non-voice turns enqueue text replies.
    assert "WhatsAppSend(to=clean_phone or phone, body=reply" in handler


def test_groups_stay_record_only():
    handler = _handler_source()
    start = handler.index("if group_jid:")
    end = handler.index("phone = _bridge_sender_phone(msg)")
    group_branch = handler[start:end]
    assert "_enqueue_hermes_message" not in group_branch
    assert "_enqueue_hermes_audio" not in group_branch
    assert "generate_sofia_reply" not in group_branch


def test_no_echo_loops_and_dedupe():
    handler = _handler_source()
    assert 'msg.get("fromMe") or msg.get("fromOwner")' in handler
    assert "_message_seen(message_id)" in handler
    # Both enqueue paths share the 10-minute duplicate suppression.
    source = _api_source()
    assert source.count("_outbox_duplicate(recipient, fingerprint)") == 2


def test_audio_pipeline_gated_on_openai_key():
    handler = _handler_source()
    assert "whatsapp_audio.audio_pipeline_ready()" in handler
