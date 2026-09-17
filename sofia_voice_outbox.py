"""Sofia voice outbox — text → WhatsApp voice message (ogg/opus audio).

Two free TTS options, best-first:

1. ``edge`` (primary) — Microsoft neural voices via the free edge-tts
   endpoint. Most natural Latin-American Spanish, zero VPS footprint, no API
   key. Requires outbound internet.
2. ``piper`` (fallback) — fully offline Piper TTS on the VPS. More robotic
   but works with no network. Needs the ``piper`` binary and a downloaded
   voice model (see docs/sofia-voice.md).

``SOFIA_TTS_BACKEND``: ``auto`` (default — edge, then piper), ``edge``,
``piper``, or ``off``.

Voice replies are capped at ~60 seconds (``SOFIA_VOICE_MAX_CHARS``, default
900). Longer replies stay as text — ``synthesize_speech`` reports
``error_code="too_long"`` so the caller keeps the text reply.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from typing import Any

TTS_BACKEND = os.getenv("SOFIA_TTS_BACKEND", "auto").strip().lower()
MAX_VOICE_CHARS = int(os.getenv("SOFIA_VOICE_MAX_CHARS", "900"))
PIPER_VOICE_MODEL = os.getenv("SOFIA_PIPER_VOICE", "").strip()  # path to .onnx

VOICES = {
    "es": os.getenv("SOFIA_TTS_VOICE_ES", "es-MX-DaliaNeural"),
    "en": os.getenv("SOFIA_TTS_VOICE_EN", "en-US-AriaNeural"),
}

OUTPUT_MIME = "audio/ogg"  # WhatsApp voice-message format (opus in ogg)


def pick_voice(language: str) -> str:
    """Voice for a reply language. Spanish default (Cuba market)."""
    return VOICES.get((language or "es").lower()[:2], VOICES["es"])


def tts_configured() -> bool:
    """True when at least one TTS backend could work."""
    if TTS_BACKEND == "off":
        return False
    if TTS_BACKEND in ("auto", "edge"):
        try:
            import edge_tts  # noqa: F401
            return True
        except Exception:
            pass
    if TTS_BACKEND in ("auto", "piper"):
        return bool(shutil.which("piper") and PIPER_VOICE_MODEL and os.path.exists(PIPER_VOICE_MODEL))
    return False


def estimate_duration_s(text: str) -> float:
    """Rough Spanish/English speech estimate: ~14 chars/second."""
    return len(text or "") / 14.0


def _ffmpeg_to_ogg(source_path: str) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not installed")
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as out:
        out_path = out.name
    try:
        proc = subprocess.run(
            [ffmpeg, "-y", "-v", "error", "-i", source_path,
             "-c:a", "libopus", "-b:a", "48k", "-ar", "24000", out_path],
            capture_output=True, timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr.decode()[:200]}")
        with open(out_path, "rb") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


async def _synthesize_edge(text: str, voice: str) -> tuple[bytes, float]:
    """edge-tts → mp3 → ogg/opus. Raises on failure."""
    import edge_tts

    def _run() -> tuple[bytes, float]:
        async def _gen() -> None:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(mp3_path)

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            mp3_path = tmp.name
        try:
            asyncio.run(_gen())
            ogg = _ffmpeg_to_ogg(mp3_path)
            return ogg, estimate_duration_s(text)
        finally:
            try:
                os.unlink(mp3_path)
            except OSError:
                pass

    return await asyncio.to_thread(_run)


async def _synthesize_piper(text: str, language: str) -> tuple[bytes, float]:
    """Piper offline TTS → wav → ogg/opus. Raises on failure."""
    piper_bin = shutil.which("piper")
    if not piper_bin:
        raise RuntimeError("piper binary not installed")
    if not PIPER_VOICE_MODEL or not os.path.exists(PIPER_VOICE_MODEL):
        raise RuntimeError("SOFIA_PIPER_VOICE model not set or missing")

    def _run() -> tuple[bytes, float]:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            proc = subprocess.run(
                [piper_bin, "--model", PIPER_VOICE_MODEL, "--output_file", wav_path],
                input=text.encode("utf-8"), capture_output=True, timeout=180,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"piper failed: {proc.stderr.decode()[:200]}")
            return _ffmpeg_to_ogg(wav_path), estimate_duration_s(text)
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    return await asyncio.to_thread(_run)


async def synthesize_speech(
    text: str,
    *,
    language: str = "es",
    backend: str | None = None,
) -> dict[str, Any]:
    """Synthesize a WhatsApp voice reply.

    Returns ``{"ok": True, "audio_bytes", "mime", "duration_s", "voice",
    "backend"}`` or ``{"ok": False, "error", "error_code"}``.
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text", "error_code": "empty_text"}
    if len(text) > MAX_VOICE_CHARS:
        return {
            "ok": False,
            "error": f"reply too long for voice ({len(text)} chars, cap {MAX_VOICE_CHARS})",
            "error_code": "too_long",
        }

    chosen = (backend or TTS_BACKEND).strip().lower()
    if chosen == "off":
        return {"ok": False, "error": "TTS disabled", "error_code": "tts_off"}

    voice = pick_voice(language)
    attempts: list[str] = []
    if chosen == "auto":
        attempts = ["edge", "piper"]
    elif chosen in ("edge", "piper"):
        attempts = [chosen]
    else:
        return {"ok": False, "error": f"unknown backend {chosen!r}", "error_code": "bad_backend"}

    last_error = ""
    for attempt in attempts:
        try:
            if attempt == "edge":
                audio, duration = await _synthesize_edge(text, voice)
            else:
                audio, duration = await _synthesize_piper(text, language)
            return {
                "ok": True,
                "audio_bytes": audio,
                "mime": OUTPUT_MIME,
                "duration_s": round(duration, 1),
                "voice": voice,
                "backend": attempt,
            }
        except Exception as exc:
            last_error = f"{attempt}: {type(exc).__name__}: {str(exc)[:200]}"
    return {"ok": False, "error": last_error or "all TTS backends failed", "error_code": "tts_failed"}
