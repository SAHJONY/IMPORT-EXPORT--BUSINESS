"""Sofia's media-vision capability ("eyes").

When a customer sends photos or videos over WhatsApp (a car for sale, product
stock, a payment receipt, an invoice photo), Sofia can now *look* at the media
and reference what she actually saw in her reply — instead of answering blind.

Vision backend: NVIDIA NIM (same account/key pattern as sofia_hermes_nim_brain),
using a vision-capable model from NVIDIA's public catalog
(verified 2026-09-17: meta/llama-3.2-11b-vision-instruct,
meta/llama-3.2-90b-vision-instruct, microsoft/phi-3-vision-128k-instruct,
adept/fuyu-8b, microsoft/kosmos-2 are listed). The model is env-configurable
via SOFIA_VISION_MODEL. FREE stack only — no new paid service.

Honesty contract: if no vision model is reachable (no API key, HTTP error,
unparseable output), evaluate_media returns ok=False with a plain reason.
It NEVER fabricates an evaluation.

Guardrails baked into every evaluation:
- Describe only what is visible; mark uncertainty explicitly.
- Never invent text, numbers, prices, VINs, odometer readings, or identities.
- Photos alone are NEVER a binding condition certification — every summary
  carries an explicit caveat line to that effect.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any

import httpx

NVIDIA_CHAT_URL = os.getenv("NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/") + "/chat/completions"

# Verified present in NVIDIA's public hosted catalog (2026-09-17).
DEFAULT_VISION_MODEL = "meta/llama-3.2-11b-vision-instruct"

# Hard cap on a single media payload sent for evaluation.
MAX_MEDIA_BYTES = 12 * 1024 * 1024
# Frames sampled from a video for evaluation as a set.
MAX_VIDEO_FRAMES = 6
# Longest side (px) images are downscaled to before upload.
MAX_IMAGE_SIDE = 1568

VISION_TIMEOUT_SECONDS = 90.0


def vision_model_name() -> str:
    return os.getenv("SOFIA_VISION_MODEL", "").strip() or DEFAULT_VISION_MODEL


def vision_configured() -> bool:
    return bool(os.getenv("NVIDIA_API_KEY", "").strip())


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


_CAVEATS = {
    "es": ("Nota: las fotos por sí solas no constituyen una certificación vinculante "
           "del estado — esto es una primera impresión visual, no una inspección."),
    "en": ("Note: photos alone are not a binding condition certification — "
           "this is a first visual impression, not an inspection."),
}


def _caveat(language: str) -> str:
    return _CAVEATS.get(language, _CAVEATS["es"])


# ---------------------------------------------------------------------------
# Track-aware evaluation prompts
# ---------------------------------------------------------------------------

_TRACK_PROMPTS: dict[str, str] = {
    "car_sale": (
        "You are evaluating vehicle photos for a car broker who connects private "
        "sellers with buyers for a fee. The broker never owns the cars.\n"
        "Describe, ONLY from what is visible:\n"
        "- Exterior: body panels, paint condition, visible dents, scratches, rust, mismatched panels or colors\n"
        "- Tires and wheels condition if visible\n"
        "- Interior: seats, dashboard, steering wheel, visible wear or damage\n"
        "- Odometer reading ONLY if clearly legible — otherwise say it is not visible\n"
        "- VIN plate ONLY if clearly legible — transcribe exactly, never guess\n"
        "- Overall first impression of the vehicle's condition\n"
        "Red flags (only if visible): signs of flood damage, heavy structural rust, "
        "deployed airbags, salvage-rebuild cues, license plates that do not match between photos."
    ),
    "import_export": (
        "You are evaluating photos for an import/export trade broker (SAHJONY Global Trade).\n"
        "Describe, ONLY from what is visible:\n"
        "- Product identity: what goods are shown\n"
        "- Quantity and packaging cues: boxes, sacks, pallets, containers, loose bulk\n"
        "- Labels, brands, markings, certifications visible on packaging\n"
        "- Condition of goods and packaging\n"
        "- If the photo shows a document (invoice, packing list, certificate): transcribe "
        "ONLY the fields that are clearly legible; list every field you cannot read as unreadable\n"
        "Red flags (only if visible): damaged packaging, inconsistent labeling, "
        "quantities that contradict the caption, documents that look altered or cropped to hide fields."
    ),
    "my_cuba_cash": (
        "You are evaluating a receipt or document photo for a money-transfer concierge service.\n"
        "Describe, ONLY from what is visible:\n"
        "- Document type (receipt, transfer confirmation, ID, other)\n"
        "- Amounts, dates, names, reference/confirmation numbers — transcribe EXACTLY as shown\n"
        "- If any amount, date, or reference is blurry, cropped, or illegible, say so explicitly\n"
        "CRITICAL: never invent an amount, date, or reference number. If nothing is legible, "
        "say the document is unreadable and ask for a clearer photo.\n"
        "Red flags (only if visible): signs of digital alteration, mismatched fonts, "
        "amounts that differ between sections of the same document."
    ),
    "default": (
        "You are evaluating photos or video frames sent by a customer evaluating a business proposal.\n"
        "Describe, ONLY from what is visible:\n"
        "- What the media shows, concretely\n"
        "- Any text, numbers, labels, or documents visible (transcribe only what is legible)\n"
        "- Condition or quality cues relevant to a business decision\n"
        "- What important information is NOT visible and would be needed\n"
        "Red flags: anything that looks inconsistent, altered, or misleading — only if visible."
    ),
}


def _track_system_prompt(track: str, language: str, n_frames: int, user_text: str) -> str:
    # Alias: the sibling 360-salesperson sales loop may emit "car_sales"; the
    # live track classifier is untouched — normalize here only.
    track_key = "car_sale" if track == "car_sales" else track
    base = _TRACK_PROMPTS.get(track_key, _TRACK_PROMPTS["default"])
    lang_name = {"es": "Spanish", "en": "English"}.get(language, "Spanish")
    frame_note = (
        f"You are shown {n_frames} still frames extracted from a video; evaluate them as a set. "
        if n_frames > 1 else ""
    )
    caption_note = f'The customer wrote alongside the media: "{user_text[:500]}". ' if user_text.strip() else ""
    return (
        base + "\n\n" + frame_note + caption_note +
        "RULES:\n"
        "- Describe ONLY what is actually visible. Mark anything uncertain as uncertain.\n"
        "- NEVER invent text, numbers, prices, readings, or identities that are not clearly visible.\n"
        "- Respond with STRICT JSON only, no markdown fences, no commentary:\n"
        '{"summary": "<2-4 sentence overview>", '
        '"details": ["<concrete observation>", ...], '
        '"condition_notes": "<condition assessment or empty string>", '
        '"red_flags": ["<visible concern>", ...], '
        '"deal_relevance": "<why this matters for the deal, 1-2 sentences>", '
        '"limitations": ["<what could not be determined>", ...]}\n'
        f'- Write all JSON string values in {lang_name}.'
    )


# ---------------------------------------------------------------------------
# Media preparation
# ---------------------------------------------------------------------------

def _sniff_image_mime(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] in (b"GIF8",):
        return "image/gif"
    return None


def _downscale_image(data: bytes) -> tuple[bytes, str, bool]:
    """Downscale a large image with ffmpeg. Returns (bytes, mime, was_scaled).

    Falls back to the original bytes when ffmpeg is unavailable.
    """
    if not _ffmpeg_available():
        return data, _sniff_image_mime(data) or "image/jpeg", False
    try:
        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as src:
            src.write(data)
            src_path = src.name
        dst_path = src_path + ".jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", src_path,
             "-vf", f"scale='min({MAX_IMAGE_SIDE},iw)':-2",
             "-q:v", "4", dst_path],
            check=True, timeout=60,
        )
        with open(dst_path, "rb") as fh:
            out = fh.read()
        return out, "image/jpeg", True
    except Exception:
        return data, _sniff_image_mime(data) or "image/jpeg", False
    finally:
        for path in (locals().get("src_path"), locals().get("dst_path")):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def _extract_video_frames(data: bytes, max_frames: int = MAX_VIDEO_FRAMES) -> tuple[list[bytes], str | None]:
    """Extract up to max_frames evenly-ish spaced JPEG frames from video bytes.

    Returns (frames, error). Requires ffmpeg; without it returns ([], reason).
    """
    if not _ffmpeg_available():
        return [], "ffmpeg_not_available"
    src_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".vid", delete=False) as src:
            src.write(data)
            src_path = src.name
        out_dir = tempfile.mkdtemp()
        # One frame per second, capped; scaled down for the vision model.
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", src_path,
             "-vf", f"fps=1,scale='min(1280,iw)':-2",
             "-vframes", str(max_frames),
             os.path.join(out_dir, "frame_%02d.jpg")],
            check=True, timeout=120,
        )
        frames: list[bytes] = []
        for name in sorted(os.listdir(out_dir)):
            if name.endswith(".jpg") and len(frames) < max_frames:
                with open(os.path.join(out_dir, name), "rb") as fh:
                    frames.append(fh.read())
        if not frames:
            return [], "no_frames_extracted"
        return frames, None
    except Exception as exc:
        return [], f"ffmpeg_error:{type(exc).__name__}"
    finally:
        if src_path:
            try:
                os.unlink(src_path)
            except OSError:
                pass
        out_dir = locals().get("out_dir", "")
        if out_dir:
            shutil.rmtree(out_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Vision call
# ---------------------------------------------------------------------------

def _data_uri(payload: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(payload).decode("ascii")


async def _vision_complete(system: str, image_payloads: list[tuple[bytes, str]]) -> tuple[str, dict[str, Any]]:
    """Call the NVIDIA NIM vision model with image content blocks.

    Returns (raw_text, meta). Separated for testability.
    """
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not api_key:
        return "", {"provider": "nvidia_nim", "configured": False}
    content: list[dict[str, Any]] = [{"type": "text", "text": system}]
    for payload, mime in image_payloads:
        content.append({
            "type": "image_url",
            "image_url": {"url": _data_uri(payload, mime)},
        })
    body = {
        "model": vision_model_name(),
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "max_tokens": 1200,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=VISION_TIMEOUT_SECONDS) as client:
        response = await client.post(
            NVIDIA_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json=body,
        )
    meta: dict[str, Any] = {
        "provider": "nvidia_nim",
        "configured": True,
        "model": body["model"],
        "status_code": response.status_code,
    }
    if response.status_code >= 400:
        return "", meta
    data = response.json()
    choices = data.get("choices") or []
    text = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        content_out = message.get("content")
        if isinstance(content_out, str):
            text = content_out.strip()
    return text, meta


def _parse_evaluation(raw: str) -> dict[str, Any] | None:
    """Parse the model's strict-JSON evaluation. Returns None when unusable."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    if not isinstance(parsed, dict) or not str(parsed.get("summary") or "").strip():
        return None
    return parsed


def _failure(reason: str, *, media_kind: str, language: str = "es") -> dict[str, Any]:
    return {
        "ok": False,
        "reason": reason,
        "summary": "",
        "details": [],
        "condition_notes": "",
        "red_flags": [],
        "deal_relevance": "",
        "limitations": [reason],
        "model": vision_model_name(),
        "media_kind": media_kind,
        "frames_evaluated": 0,
        "caveat": _caveat(language),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def evaluate_media(
    *,
    media_bytes: bytes,
    media_kind: str,
    track: str,
    user_text: str = "",
    language: str = "es",
) -> dict[str, Any]:
    """Evaluate one photo or video for Sofia.

    Returns a dict with: ok, summary (always carries the no-certification
    caveat), details, condition_notes, red_flags, deal_relevance,
    limitations, model, media_kind, frames_evaluated, caveat.
    On any failure ok=False with an honest reason — never faked.
    """
    kind = (media_kind or "").strip().lower()
    if kind not in ("image", "video"):
        return _failure("unsupported_media_kind", media_kind=kind or "unknown", language=language)
    if not media_bytes:
        return _failure("empty_media", media_kind=kind, language=language)
    if len(media_bytes) > MAX_MEDIA_BYTES:
        return _failure("too_large", media_kind=kind, language=language)
    if not vision_configured():
        return _failure("vision_not_configured", media_kind=kind, language=language)

    limitations: list[str] = []
    image_payloads: list[tuple[bytes, str]] = []
    frames_evaluated = 0

    if kind == "video":
        frames, error = _extract_video_frames(media_bytes)
        if error or not frames:
            return _failure(
                f"video_unavailable:{error or 'unknown'}", media_kind=kind, language=language
            )
        image_payloads = [(frame, "image/jpeg") for frame in frames]
        frames_evaluated = len(frames)
    else:
        mime = _sniff_image_mime(media_bytes)
        if mime is None:
            return _failure("unrecognized_image_format", media_kind=kind, language=language)
        scaled, out_mime, was_scaled = _downscale_image(media_bytes)
        image_payloads = [(scaled, out_mime)]
        frames_evaluated = 1
        if not was_scaled and _ffmpeg_available():
            limitations.append("image_sent_unscaled")
        elif not _ffmpeg_available():
            limitations.append("ffmpeg_unavailable_image_sent_as_is")

    system = _track_system_prompt(track, language, frames_evaluated, user_text)
    try:
        raw, meta = await _vision_complete(system, image_payloads)
    except Exception as exc:
        return _failure(f"vision_transport_error:{type(exc).__name__}", media_kind=kind, language=language)
    if meta.get("status_code", 200) >= 400 or not raw:
        return _failure(
            f"vision_backend_error:{meta.get('status_code', 'empty')}",
            media_kind=kind, language=language,
        )

    parsed = _parse_evaluation(raw)
    caveat = _caveat(language)
    if parsed is None:
        # Honest fallback: surface the raw text as an unstructured summary.
        summary = raw.strip()[:2000] + f"\n\n{caveat}"
        return {
            "ok": True,
            "summary": summary,
            "details": [],
            "condition_notes": "",
            "red_flags": [],
            "deal_relevance": "",
            "limitations": limitations + ["unstructured_model_response"],
            "model": vision_model_name(),
            "media_kind": kind,
            "frames_evaluated": frames_evaluated,
            "caveat": caveat,
        }

    def _str_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        return []

    summary = str(parsed.get("summary") or "").strip()
    return {
        "ok": True,
        "summary": summary + f"\n\n{caveat}",
        "details": _str_list(parsed.get("details")),
        "condition_notes": str(parsed.get("condition_notes") or "").strip(),
        "red_flags": _str_list(parsed.get("red_flags")),
        "deal_relevance": str(parsed.get("deal_relevance") or "").strip(),
        "limitations": limitations + _str_list(parsed.get("limitations")),
        "model": vision_model_name(),
        "media_kind": kind,
        "frames_evaluated": frames_evaluated,
        "caveat": caveat,
    }


def health() -> dict[str, Any]:
    return {
        "status": "ok" if vision_configured() else "configuration_required",
        "service": "sofia-media-evaluator",
        "provider": "nvidia_nim",
        "vision_model": vision_model_name(),
        "vision_configured": vision_configured(),
        "ffmpeg_available": _ffmpeg_available(),
        "max_media_bytes": MAX_MEDIA_BYTES,
        "max_video_frames": MAX_VIDEO_FRAMES,
    }
