"""Regression tests for the 2026-09-29 owner voice-note incident.

Juan sent a Spanish voice note to the Hermes/Sofia WhatsApp line. The bridge
poller trusted the gateway's garbled English transcription ("event stories",
"Prut") instead of transcribing it itself, the language rule saw English and
answered in English, and the brain produced a corporate questionnaire
mentioning "our CRM".

Three fixes, three tests:
1. Bridge poller ALWAYS self-transcribes audio with Whisper (es) and ignores
   any gateway-provided body for audio events.
2. owner_context forces the Spanish reply language no matter the input.
3. The outbound guard deterministically blocks any "CRM" mention (the prompt
   ban alone was disobeyed); the owner prompt tells Sofia to flag garbled
   transcriptions instead of building on them.
"""
import re
from pathlib import Path

from sofia_whatsapp_runtime import (
    _contains_internal_jargon,
    apply_outbound_guard,
    language_rule,
)

ROOT = Path(__file__).resolve().parents[1]

GARBLED_ENGLISH = (
    "Well, look, I think we have a group of event stories in which we "
    "promote the products by more or less, and any product that you can "
    "try, I'm going to try to get a good commission for me and a good "
    "commission for the stories, which I give them so that they sell Prut."
)


def _api_source():
    return (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")


def _handler_source():
    source = _api_source()
    start = source.index("async def _handle_bridge_message(")
    end = source.index("async def _sofia_bridge_poller(")
    return source[start:end]


def test_bridge_poller_self_transcribes_audio_despite_gateway_body():
    """Incident 2026-09-29: the old `if not body and is_voice_event:` gate let
    the gateway's garbled English transcription through untouched. Audio
    events must now ALWAYS go through our own Whisper transcription."""
    handler = _handler_source()
    assert "if not body and is_voice_event:" not in handler
    # The transcription block still exists and runs for every audio event.
    assert "if is_voice_event:" in handler
    assert "whatsapp_audio.transcribe_audio(audio_bytes)" in handler
    assert "body = voice_text[:4000]" in handler


def test_owner_context_forces_spanish_on_english_input():
    """The owner's garbled English input must still get a Spanish reply."""
    rule = language_rule(GARBLED_ENGLISH, owner_context=True)
    assert "SPANISH" in rule
    assert "Write your ENTIRE reply in Spanish" in rule


def test_owner_context_forces_spanish_on_plain_english():
    rule = language_rule("Hello, I need help with a shipment", owner_context=True)
    assert "SPANISH" in rule
    assert "ENGLISH" not in rule


def test_non_owner_english_still_gets_english():
    """No behavior change for regular contacts."""
    rule = language_rule("Hello, I need help with a shipment")
    assert "ENGLISH" in rule


def test_guard_blocks_crm_mention():
    """The 2026-09-29 reply said 'our CRM' despite the prompt ban. The
    deterministic guard must catch it."""
    hits = _contains_internal_jargon(
        "I can draft a plan and create the necessary records in our CRM."
    )
    assert hits, "expected a jargon hit for 'CRM'"
    assert not _contains_internal_jargon("Te ayudo con tu importación, Juan.")


def test_guard_replaces_crm_reply_with_safe_fallback():
    reply = (
        "I need a few details to set up a proper commission scheme that meets "
        "SAHJONY's policies and compliance. Once I have those points nailed "
        "down, I can draft a plan and create the necessary records in our CRM."
    )
    clean, report = apply_outbound_guard(
        reply,
        memory={},
        sales={},
        text=GARBLED_ENGLISH,
        contact_name="Juan",
        language="es",
    )
    assert report["blocked"] is True
    assert report["block_reason"] == "internal_jargon"
    assert "crm" in " ".join(report["jargon_hits"]).lower()
    assert "CRM" not in clean


def test_owner_prompt_flags_garbled_transcriptions():
    """Sofia must say the transcription came out garbled instead of building
    questionnaires on garbage input."""
    runtime = (ROOT / "sofia_whatsapp_runtime.py").read_text(encoding="utf-8")
    assert "garbled" in runtime.lower()
    assert "NEVER answer a garbled machine transcription as if it made sense" in runtime
