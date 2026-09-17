"""Sofia voice inbox — transcribe WhatsApp voice notes with local faster-whisper.

Free, fully offline, no API keys. faster-whisper (CTranslate2) runs on the VPS
CPU. Spanish-first: transcription auto-detects the language with a Spanish
business-context initial prompt biasing toward Spanish; the reply language is
then chosen by ``sofia_track_classifier.detect_language`` on the transcript.

On any failure (missing engine, corrupt audio, empty/low-confidence result)
``transcribe_audio`` returns ``ok=False`` with an error code — Sofia must tell
the customer she could not understand the audio, never invent words.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

WHISPER_MODEL_NAME = os.getenv("SOFIA_WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("SOFIA_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("SOFIA_WHISPER_COMPUTE_TYPE", "int8")
MIN_AVG_LOGPROB = float(os.getenv("SOFIA_WHISPER_MIN_LOGPROB", "-1.0"))
MIN_LANGUAGE_PROBABILITY = float(os.getenv("SOFIA_WHISPER_MIN_LANG_PROB", "0.5"))
MAX_AUDIO_BYTES = int(os.getenv("SOFIA_VOICE_MAX_BYTES", str(15 * 1024 * 1024)))

# Biases auto-detection toward Spanish business conversation (Cuba market).
SPANISH_BIAS_PROMPT = (
    "Conversación comercial por WhatsApp. El cliente habla de comprar o vender carros, "
    "precios, envíos de dinero a Cuba, importaciones y cotizaciones."
)

_MIME_SUFFIX = {
    "audio/ogg": ".ogg",
    "audio/opus": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/webm": ".webm",
}

_model: Any = None
_model_error: str | None = None


def whisper_available() -> bool:
    """True when the faster-whisper package is importable."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _get_model() -> Any:
    """Lazy singleton — model load is expensive (~hundreds of MB)."""
    global _model, _model_error
    if _model is not None:
        return _model
    if _model_error is not None:
        raise RuntimeError(_model_error)
    try:
        from faster_whisper import WhisperModel
        _model = WhisperModel(
            WHISPER_MODEL_NAME,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        return _model
    except Exception as exc:
        _model_error = f"whisper_load_failed: {type(exc).__name__}: {exc}"
        raise RuntimeError(_model_error)


def _transcribe_sync(audio_bytes: bytes, suffix: str, language_hint: str | None) -> dict[str, Any]:
    import tempfile

    model = _get_model()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(audio_bytes)
        tmp.flush()
        segments, info = model.transcribe(
            tmp.name,
            language=language_hint,
            initial_prompt=SPANISH_BIAS_PROMPT,
            vad_filter=True,
        )
        texts: list[str] = []
        logprobs: list[float] = []
        for seg in segments:
            t = (seg.text or "").strip()
            if t:
                texts.append(t)
            try:
                logprobs.append(float(seg.avg_logprob))
            except Exception:
                pass
    text = " ".join(texts).strip()
    avg_logprob = sum(logprobs) / len(logprobs) if logprobs else -99.0
    return {
        "text": text,
        "language": str(getattr(info, "language", "") or ""),
        "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0),
        "avg_logprob": avg_logprob,
        "duration_s": float(getattr(info, "duration", 0.0) or 0.0),
    }


async def transcribe_audio(
    audio_bytes: bytes,
    *,
    mime_hint: str = "audio/ogg",
    language_hint: str | None = None,
) -> dict[str, Any]:
    """Transcribe a WhatsApp voice note.

    Returns ``{"ok": True, "text", "language", "language_probability",
    "avg_logprob", "duration_s", "model"}`` or ``{"ok": False, "error",
    "error_code"}``. Never raises on bad audio — failure is data.
    """
    if not audio_bytes:
        return {"ok": False, "error": "empty audio", "error_code": "empty_audio"}
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        return {"ok": False, "error": "audio too large", "error_code": "audio_too_large"}
    if not whisper_available():
        return {"ok": False, "error": "faster-whisper not installed", "error_code": "engine_missing"}

    suffix = _MIME_SUFFIX.get((mime_hint or "").split(";")[0].strip().lower(), ".ogg")
    try:
        result = await asyncio.to_thread(_transcribe_sync, audio_bytes, suffix, language_hint)
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)[:300], "error_code": "engine_error"}
    except Exception as exc:
        return {"ok": False, "error": f"transcription failed: {type(exc).__name__}", "error_code": "transcription_failed"}

    text = result["text"]
    if not text:
        return {"ok": False, "error": "no speech detected", "error_code": "empty_transcript", **result}
    if result["avg_logprob"] < MIN_AVG_LOGPROB:
        return {"ok": False, "error": "low transcription confidence", "error_code": "low_confidence", **result}
    if result["language_probability"] < MIN_LANGUAGE_PROBABILITY:
        return {"ok": False, "error": "uncertain language detection", "error_code": "low_confidence", **result}
    return {"ok": True, "model": WHISPER_MODEL_NAME, **result}
