"""WhatsApp voice-note support (Meta Cloud API path).

INBOUND:  an audio-type webhook message -> media downloaded via the Graph API
           -> transcribed with OpenAI Whisper (Spanish) -> the transcription is
           fed into the existing Sofia reply pipeline as if it were text.
OUTBOUND: when the inbound turn was audio, the generated reply text is
           synthesized with OpenAI TTS (Spanish) and sent as a WhatsApp audio
           message INSTEAD of the text reply. Text-in -> text-out is untouched.

Provider choice: OpenAI is used for both transcription (whisper-1) and TTS
(gpt-4o-mini-tts) because OPENAI_API_KEY is already present in the WhatsApp
service env (/etc/sahjony-fallback/import-export.env) — no new secrets needed.

VOICE NOTE (honest): Juan's chosen Sofia voice (avocado_v2:vdc_NOID21) is a
Meta Shortwave voice ID. It does NOT exist on OpenAI and cannot be used here.
SOFIA_TTS_VOICE defaults to "nova" — OpenAI's female voice with the strongest
Spanish rendering. It is not Cuban-accented; no OpenAI TTS voice is.

Fail-closed everywhere: missing key, download failure, transcription failure,
or TTS failure produces NO reply. The inbound turn is always recorded by the
caller before this module runs, so nothing is ever silently lost.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_SPEECH_URL = "https://api.openai.com/v1/audio/speech"

WHISPER_MODEL = os.getenv("SOFIA_WHISPER_MODEL", "whisper-1")
TTS_MODEL = os.getenv("SOFIA_TTS_MODEL", "gpt-4o-mini-tts")
# See VOICE NOTE above: Shortwave voice IDs do not work with OpenAI TTS.
TTS_VOICE = os.getenv("SOFIA_TTS_VOICE", "nova")
TTS_INSTRUCTIONS = os.getenv(
    "SOFIA_TTS_INSTRUCTIONS",
    "Habla español de forma cálida, clara y natural, como una ejecutiva amable.",
)

MAX_AUDIO_BYTES = 20 * 1024 * 1024
HTTP_TIMEOUT_SECS = 60


def audio_pipeline_ready() -> bool:
    """True when the OpenAI key needed for Whisper + TTS is configured."""
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def extract_audio_media_id(msg: dict[str, Any]) -> str | None:
    """Return the Graph API media id for a Cloud API audio message, else None."""
    if not isinstance(msg, dict) or msg.get("type") != "audio":
        return None
    audio = msg.get("audio") or {}
    if not isinstance(audio, dict):
        return None
    media_id = str(audio.get("id") or "").strip()
    return media_id or None


def _openai_headers() -> dict[str, str]:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return {"Authorization": f"Bearer {key}"}


def _graph_base(graph_api_version: str) -> str:
    version = (graph_api_version or "").strip()
    if not version:
        raise RuntimeError("WhatsApp Graph API version is not configured")
    return f"https://graph.facebook.com/{version}"


async def download_whatsapp_media(
    graph_api_version: str,
    access_token: str,
    media_id: str,
) -> tuple[bytes, str]:
    """Download a Cloud API media object. Returns (audio_bytes, mime_type)."""
    base = _graph_base(graph_api_version)
    token = (access_token or "").strip()
    if not token or not media_id:
        raise RuntimeError("WhatsApp media download is not configured")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECS) as client:
        meta = await client.get(f"{base}/{media_id}", headers=headers)
        meta.raise_for_status()
        info = meta.json()
        url = str(info.get("url") or "")
        mime_type = str(info.get("mime_type") or "audio/ogg")
        if not url:
            raise RuntimeError("WhatsApp media URL missing")
        data = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        data.raise_for_status()
        audio = data.content
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise RuntimeError("WhatsApp audio payload empty or too large")
    return audio, mime_type


async def transcribe_audio(audio_bytes: bytes, filename: str = "voice-note.ogg") -> str:
    """Transcribe voice-note bytes to Spanish text with OpenAI Whisper."""
    if not audio_bytes:
        raise RuntimeError("Empty audio payload")
    headers = _openai_headers()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECS) as client:
        response = await client.post(
            OPENAI_TRANSCRIPTIONS_URL,
            headers=headers,
            data={"model": WHISPER_MODEL, "language": "es", "response_format": "text"},
            files={"file": (filename, audio_bytes, "audio/ogg")},
        )
        response.raise_for_status()
    return response.text.strip()


async def synthesize_speech(text: str) -> bytes:
    """Synthesize Spanish speech (MP3) for a Sofia reply with OpenAI TTS."""
    clean = (text or "").strip()[:4096]
    if not clean:
        raise RuntimeError("Empty reply text")
    headers = _openai_headers()
    headers["Content-Type"] = "application/json"
    payload: dict[str, Any] = {
        "model": TTS_MODEL,
        "voice": TTS_VOICE,
        "input": clean,
        "response_format": "mp3",
    }
    # `instructions` is only accepted by gpt-4o-mini-tts; other TTS models
    # reject unknown fields, so gate it.
    if TTS_MODEL == "gpt-4o-mini-tts":
        payload["instructions"] = TTS_INSTRUCTIONS
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECS) as client:
        response = await client.post(OPENAI_SPEECH_URL, headers=headers, json=payload)
        response.raise_for_status()
        audio = response.content
    if not audio:
        raise RuntimeError("TTS returned empty audio")
    return audio


async def upload_media(
    graph_api_version: str,
    phone_number_id: str,
    access_token: str,
    audio_bytes: bytes,
    mime_type: str = "audio/mpeg",
) -> str:
    """Upload audio bytes to the Cloud API media endpoint. Returns media id."""
    base = _graph_base(graph_api_version)
    token = (access_token or "").strip()
    if not token or not phone_number_id or not audio_bytes:
        raise RuntimeError("WhatsApp media upload is not configured")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECS) as client:
        response = await client.post(
            f"{base}/{phone_number_id}/media",
            headers=headers,
            data={"messaging_product": "whatsapp"},
            files={"file": ("sofia-reply.mp3", audio_bytes, mime_type)},
        )
        response.raise_for_status()
        media_id = str(response.json().get("id") or "")
    if not media_id:
        raise RuntimeError("WhatsApp media upload returned no id")
    return media_id


def bridge_message_is_audio(msg: dict[str, Any]) -> bool:
    """Best-effort voice-note detection for Hermes bridge poller messages.

    The bridge's audio schema is not documented in this repo, so this only
    detects explicit audio markers. Anything unrecognized is NOT treated as
    audio (conservative: never misclassify an image or doc as a voice note).
    """
    if not isinstance(msg, dict):
        return False
    msg_type = str(msg.get("type") or "").strip().lower()
    if msg_type in {"audio", "ptt", "voice", "voicenote", "voice_note"}:
        return True
    mime = str(msg.get("mimetype") or msg.get("mimeType") or msg.get("mime_type") or "").strip().lower()
    return mime.startswith("audio/")
