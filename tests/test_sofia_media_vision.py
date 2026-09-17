"""Tests for Sofia's media-vision capability ("eyes").

Covers: track-aware prompt selection, evaluator ok/failure paths (vision
backend mocked), video-frame path (ffmpeg mocked), size cap, the
no-certification guardrail caveat, media ingest registration, and the
runtime's MEDIA EVIDENCE prompt injection.
"""
import asyncio
import json
import os

import pytest

import sofia_media_evaluator as ev
import whatsapp_api as wa
from sofia_whatsapp_runtime import _build_media_evidence_block

FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64

EVAL_JSON = json.dumps({
    "summary": "Se ve un sedán gris con la pintura en buen estado.",
    "details": ["Parachoques delantero sin daños visibles"],
    "condition_notes": "Buen estado general aparente.",
    "red_flags": [],
    "deal_relevance": "El vehículo parece apto para una inspección en persona.",
    "limitations": ["No se ve el odómetro"],
})


def _run(coro):
    return asyncio.run(coro)


def _patch_vision_ok(monkeypatch, payload=EVAL_JSON):
    async def fake_complete(system, image_payloads):
        return payload, {"provider": "nvidia_nim", "configured": True,
                         "model": "test-model", "status_code": 200}
    monkeypatch.setattr(ev, "_vision_complete", fake_complete)
    monkeypatch.setattr(ev, "vision_configured", lambda: True)


# ---------------------------------------------------------------------------
# Track-aware prompts
# ---------------------------------------------------------------------------

def test_track_prompt_car_sale_mentions_vin_and_odometer():
    prompt = ev._track_system_prompt("car_sale", "es", 1, "")
    assert "VIN" in prompt
    assert "dmetro" in prompt or "odometer" in prompt.lower()


def test_track_prompt_cubacash_forbids_invented_amounts():
    prompt = ev._track_system_prompt("my_cuba_cash", "es", 1, "")
    assert "never invent an amount" in prompt.lower()


def test_track_prompt_import_export_covers_documents():
    prompt = ev._track_system_prompt("import_export", "es", 1, "")
    assert "packing list" in prompt.lower() or "invoice" in prompt.lower()


def test_track_prompt_unknown_falls_back_to_default():
    prompt = ev._track_system_prompt("ask", "es", 1, "")
    assert "business proposal" in prompt.lower()


def test_track_prompt_video_frame_note():
    prompt = ev._track_system_prompt("car_sale", "es", 4, "")
    assert "4 still frames" in prompt


# ---------------------------------------------------------------------------
# Evaluator: ok path
# ---------------------------------------------------------------------------

def test_evaluate_media_ok_path(monkeypatch):
    _patch_vision_ok(monkeypatch)
    monkeypatch.setattr(ev, "_downscale_image", lambda data: (data, "image/jpeg", False))
    result = _run(ev.evaluate_media(
        media_bytes=FAKE_JPEG, media_kind="image", track="car_sale",
        user_text="mira este carro", language="es"))
    assert result["ok"] is True
    assert "sedán gris" in result["summary"]
    assert result["details"] == ["Parachoques delantero sin daños visibles"]
    assert result["frames_evaluated"] == 1
    assert result["media_kind"] == "image"


def test_evaluate_media_guardrail_caveat_in_summary_es(monkeypatch):
    _patch_vision_ok(monkeypatch)
    monkeypatch.setattr(ev, "_downscale_image", lambda data: (data, "image/jpeg", False))
    result = _run(ev.evaluate_media(
        media_bytes=FAKE_JPEG, media_kind="image", track="car_sale", language="es"))
    assert "no constituyen una certificación vinculante" in result["summary"]
    assert result["caveat"] in result["summary"]


def test_evaluate_media_guardrail_caveat_in_summary_en(monkeypatch):
    _patch_vision_ok(monkeypatch)
    monkeypatch.setattr(ev, "_downscale_image", lambda data: (data, "image/jpeg", False))
    result = _run(ev.evaluate_media(
        media_bytes=FAKE_JPEG, media_kind="image", track="car_sale", language="en"))
    assert "not a binding condition certification" in result["summary"]


def test_evaluate_media_unstructured_response_fallback(monkeypatch):
    _patch_vision_ok(monkeypatch, payload="Se ve bien, sin daños obvios.")
    monkeypatch.setattr(ev, "_downscale_image", lambda data: (data, "image/jpeg", False))
    result = _run(ev.evaluate_media(
        media_bytes=FAKE_JPEG, media_kind="image", track="ask", language="es"))
    assert result["ok"] is True
    assert "unstructured_model_response" in result["limitations"]
    assert "no constituyen una certificación vinculante" in result["summary"]


# ---------------------------------------------------------------------------
# Evaluator: failure paths (never faked)
# ---------------------------------------------------------------------------

def test_evaluate_media_not_configured(monkeypatch):
    monkeypatch.setattr(ev, "vision_configured", lambda: False)
    result = _run(ev.evaluate_media(
        media_bytes=FAKE_JPEG, media_kind="image", track="car_sale"))
    assert result["ok"] is False
    assert result["reason"] == "vision_not_configured"


def test_evaluate_media_too_large(monkeypatch):
    monkeypatch.setattr(ev, "vision_configured", lambda: True)
    big = b"\xff\xd8\xff" + b"\x00" * ev.MAX_MEDIA_BYTES
    result = _run(ev.evaluate_media(
        media_bytes=big, media_kind="image", track="car_sale"))
    assert result["ok"] is False
    assert result["reason"] == "too_large"


def test_evaluate_media_unsupported_kind(monkeypatch):
    monkeypatch.setattr(ev, "vision_configured", lambda: True)
    result = _run(ev.evaluate_media(
        media_bytes=b"data", media_kind="audio", track="car_sale"))
    assert result["ok"] is False
    assert result["reason"] == "unsupported_media_kind"


def test_evaluate_media_empty_bytes(monkeypatch):
    monkeypatch.setattr(ev, "vision_configured", lambda: True)
    result = _run(ev.evaluate_media(
        media_bytes=b"", media_kind="image", track="car_sale"))
    assert result["ok"] is False
    assert result["reason"] == "empty_media"


def test_evaluate_media_backend_error(monkeypatch):
    async def fake_complete(system, image_payloads):
        return "", {"provider": "nvidia_nim", "configured": True, "status_code": 503}
    monkeypatch.setattr(ev, "_vision_complete", fake_complete)
    monkeypatch.setattr(ev, "vision_configured", lambda: True)
    monkeypatch.setattr(ev, "_downscale_image", lambda data: (data, "image/jpeg", False))
    result = _run(ev.evaluate_media(
        media_bytes=FAKE_JPEG, media_kind="image", track="car_sale"))
    assert result["ok"] is False
    assert "vision_backend_error" in result["reason"]


def test_evaluate_media_transport_exception(monkeypatch):
    async def fake_complete(system, image_payloads):
        raise RuntimeError("boom")
    monkeypatch.setattr(ev, "_vision_complete", fake_complete)
    monkeypatch.setattr(ev, "vision_configured", lambda: True)
    monkeypatch.setattr(ev, "_downscale_image", lambda data: (data, "image/jpeg", False))
    result = _run(ev.evaluate_media(
        media_bytes=FAKE_JPEG, media_kind="image", track="car_sale"))
    assert result["ok"] is False
    assert result["reason"].startswith("vision_transport_error")


def test_evaluate_media_unrecognized_image_format(monkeypatch):
    monkeypatch.setattr(ev, "vision_configured", lambda: True)
    result = _run(ev.evaluate_media(
        media_bytes=b"not-an-image-at-all", media_kind="image", track="car_sale"))
    assert result["ok"] is False
    assert result["reason"] == "unrecognized_image_format"


# ---------------------------------------------------------------------------
# Video path (ffmpeg mocked)
# ---------------------------------------------------------------------------

def test_evaluate_video_frame_path_mocked(monkeypatch):
    _patch_vision_ok(monkeypatch)
    monkeypatch.setattr(ev, "_extract_video_frames",
                        lambda data, max_frames=6: ([b"frame1", b"frame2"], None))
    result = _run(ev.evaluate_media(
        media_bytes=b"fake-video-bytes", media_kind="video", track="car_sale",
        language="es"))
    assert result["ok"] is True
    assert result["frames_evaluated"] == 2
    assert result["media_kind"] == "video"


def test_evaluate_video_no_ffmpeg_honest_failure(monkeypatch):
    monkeypatch.setattr(ev, "vision_configured", lambda: True)
    monkeypatch.setattr(ev, "_extract_video_frames",
                        lambda data, max_frames=6: ([], "ffmpeg_not_available"))
    result = _run(ev.evaluate_media(
        media_bytes=b"fake-video-bytes", media_kind="video", track="car_sale"))
    assert result["ok"] is False
    assert "video_unavailable" in result["reason"]


# ---------------------------------------------------------------------------
# Media ingest: register_inbound_media
# ---------------------------------------------------------------------------

class _FakeBackend:
    def __init__(self, fail_insert=False):
        self.inserted = []
        self.fail_insert = fail_insert

    async def select(self, table, *, params=None):
        return []

    async def insert(self, table, row):
        if self.fail_insert:
            raise RuntimeError("no such table")
        self.inserted.append((table, row))
        return [row]


def test_register_inbound_media_spools_bytes_and_metadata(monkeypatch, tmp_path):
    backend = _FakeBackend()
    monkeypatch.setattr(wa, "get_backend", lambda: backend)
    monkeypatch.setattr(wa, "SOFIA_MEDIA_SPOOL_DIR", str(tmp_path))
    result = _run(wa.register_inbound_media(
        message_id="wamid.test123", phone="+15551234567", media_kind="image",
        mime_type="image/jpeg", media_bytes=FAKE_JPEG, caption="mi carro"))
    assert result["ok"] is True
    assert result["byte_size"] == len(FAKE_JPEG)
    assert result["media_ref"] and os.path.exists(result["media_ref"])
    assert result["metadata_stored"] is True
    tables = [t for t, _ in backend.inserted]
    assert "whatsapp_media" in tables


def test_register_inbound_media_tolerates_missing_table(monkeypatch, tmp_path):
    backend = _FakeBackend(fail_insert=True)
    monkeypatch.setattr(wa, "get_backend", lambda: backend)
    monkeypatch.setattr(wa, "SOFIA_MEDIA_SPOOL_DIR", str(tmp_path))
    result = _run(wa.register_inbound_media(
        message_id="wamid.test456", phone="+15551234567", media_kind="video",
        media_bytes=b"fake-video"))
    # Bytes still spooled; metadata flag honestly reports the miss.
    assert result["ok"] is True
    assert result["metadata_stored"] is False
    assert os.path.exists(result["media_ref"])


def test_register_inbound_media_rejects_oversize(monkeypatch, tmp_path):
    monkeypatch.setattr(wa, "SOFIA_MEDIA_SPOOL_DIR", str(tmp_path))
    big = b"\x00" * (ev.MAX_MEDIA_BYTES + 1)
    result = _run(wa.register_inbound_media(
        message_id="wamid.big", phone="+1555", media_kind="image", media_bytes=big))
    assert result["ok"] is False
    assert result["reason"] == "too_large"


def test_register_inbound_media_rejects_unknown_kind(monkeypatch, tmp_path):
    monkeypatch.setattr(wa, "SOFIA_MEDIA_SPOOL_DIR", str(tmp_path))
    result = _run(wa.register_inbound_media(
        message_id="wamid.x", phone="+1555", media_kind="sticker", media_bytes=b"z"))
    assert result["ok"] is False
    assert result["reason"] == "unsupported_media_kind"


def test_register_inbound_media_no_bytes_no_url(monkeypatch, tmp_path):
    monkeypatch.setattr(wa, "SOFIA_MEDIA_SPOOL_DIR", str(tmp_path))
    result = _run(wa.register_inbound_media(
        message_id="wamid.y", phone="+1555", media_kind="image"))
    assert result["ok"] is False
    assert result["reason"] == "no_media_bytes"


# ---------------------------------------------------------------------------
# Runtime: MEDIA EVIDENCE prompt injection
# ---------------------------------------------------------------------------

def test_media_evidence_block_references_seen_content_es():
    block = _build_media_evidence_block([{
        "ok": True, "media_kind": "image", "frames_evaluated": 1,
        "summary": "Se ve un sedán gris.\n\nNota: las fotos por sí solas no constituyen una certificación vinculante del estado.",
        "details": [], "condition_notes": "Buen estado aparente.",
        "red_flags": ["Óxido visible en el guardafango"], "deal_relevance": "Relevante.",
        "limitations": [],
    }], "es")
    assert "Veo en las fotos" in block
    assert "sedán gris" in block
    assert "Óxido visible" in block
    assert "certificación vinculante" in block


def test_media_evidence_block_honest_failure_note_en():
    block = _build_media_evidence_block(
        [{"ok": False, "reason": "vision_not_configured"}], "en")
    assert "could NOT be analyzed" in block
    assert "in English" in block


def test_media_evidence_block_never_overclaims():
    block = _build_media_evidence_block([{
        "ok": True, "media_kind": "image", "frames_evaluated": 1,
        "summary": "Resumen.", "details": [], "condition_notes": "",
        "red_flags": [], "deal_relevance": "", "limitations": [],
    }], "es")
    assert "never claim more than the evaluation supports" in block
    assert "binding certification" in block


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_evaluator_health_reports_vision_model():
    h = ev.health()
    assert h["service"] == "sofia-media-evaluator"
    assert h["vision_model"]
    assert "max_media_bytes" in h
