"""Sofia 360° salesperson — the agentic loop.

Perceive → Reason → Act → Reflect, running on every customer turn when the
feature flag is enabled.

- PERCEIVE: text from the transcript, voice notes via the voice branch's
  interface, images/video via the media branch's interface. Both are coded
  against documented seams; when those branches are not merged yet, the
  loop degrades gracefully and says so honestly.
- REASON: customer 360 profile (per business) + playbook stage + the
  existing sales brain / agentic sales OS signals.
- ACT: exactly one of — reply (through the existing runtime pipeline),
  draft (approval queue), proposed tool call (recorded, never executed
  autonomously), or escalate (owner brief, never messaged to the customer).
- REFLECT: record_lesson from evidence only — outcome signals, never PII.

FEATURE FLAG: SOFIA_360_SALESPERSON=1 enables the loop. Default OFF.
Live activation needs Juan's explicit approval.

SENSORY SEAMS (sibling branches now merged on main):
- voice:  sofia_voice_inbox.transcribe_audio(audio_bytes, mime_hint=...)
          -> {"ok", "text", "language", ...}
- media:  sofia_media_evaluator.evaluate_media(media_bytes=..., media_kind=...,
          track=..., user_text=..., language=...) -> {"ok", "summary", ...}
- arms:   ai-car-sales-machine agent/tools registry (separate repo) ->
          proposed tool calls are recorded in the audit; the loop never
          imports that repo (no cross-repo coupling).

MERGE ORDER with sibling branches:
1. build/sofia-media-vision  (eyes) — MERGED
2. build/sofia-voice         (voice) — MERGED
3. build/car-arms            (car machine arms, other repo)
4. build/sofia-360-salesperson (this — consumes 1-3 through the seams)
"""

from __future__ import annotations

import os
from typing import Any

from sofia_customer_360 import build_customer_360, classify_turn
from sofia_escalation import build_owner_brief, known_triggers, record_escalation
from sofia_negotiation_guards import validate_outbound
from sofia_sales_playbooks import (
    TRACK_CAR_SALES,
    car_signal_score,
    get_playbook,
    is_minimum_qualified,
    next_qualification_question,
)
from sofia_track_classifier import (
    TRACK_ASK,
    TRACK_IMPORT_EXPORT,
    TRACK_MY_CUBA_CASH,
    classify_track,
    detect_language,
)

FLAG_ENV = "SOFIA_360_SALESPERSON"

# car_sales routing inside the loop activates only with the flag (which
# itself needs Juan's approval). Live classifier is untouched.
CAR_SIGNAL_THRESHOLD = 0.66


def flag_enabled() -> bool:
    return os.getenv(FLAG_ENV, "").strip().lower() in ("1", "true", "yes")


def should_use_360(*, owner_context: bool = False) -> bool:
    """True when an inbound customer turn should run the 360 loop."""
    return flag_enabled() and not owner_context


# ---------------------------------------------------------------------------
# Sensory seams — the sibling branches (media-vision, voice) are merged;
# these call their real documented interfaces with graceful degradation.
# ---------------------------------------------------------------------------

async def transcribe_audio_seam(
    audio_bytes: bytes | None, mime_hint: str = "audio/ogg"
) -> dict[str, Any]:
    """Voice-note transcription via sofia_voice_inbox's documented interface."""
    if not audio_bytes:
        return {"ok": False, "reason": "no_audio", "text": ""}
    try:
        from sofia_voice_inbox import transcribe_audio

        result = await transcribe_audio(audio_bytes, mime_hint=mime_hint)
        return {
            "ok": bool(result.get("ok")),
            "text": str(result.get("text") or ""),
            "language": result.get("language") or "es",
            "confidence": result.get("language_probability"),
            "reason": result.get("error_code") or result.get("error"),
        }
    except ImportError:
        return {"ok": False, "reason": "voice_branch_not_merged", "text": ""}
    except Exception as exc:
        return {"ok": False, "reason": f"transcription_error:{type(exc).__name__}", "text": ""}


async def evaluate_media_seam(
    media_bytes: bytes | None,
    media_kind: str = "image",
    track: str = TRACK_IMPORT_EXPORT,
    user_text: str = "",
    language: str = "es",
) -> dict[str, Any]:
    """Image/video evaluation via sofia_media_evaluator's documented interface."""
    if not media_bytes:
        return {"ok": False, "reason": "no_media"}
    try:
        from sofia_media_evaluator import evaluate_media

        result = await evaluate_media(
            media_bytes=media_bytes,
            media_kind=media_kind,
            track=track,
            user_text=user_text,
            language=language,
        )
        return dict(result)
    except ImportError:
        return {"ok": False, "reason": "media_branch_not_merged"}
    except Exception as exc:
        return {"ok": False, "reason": f"evaluation_error:{type(exc).__name__}"}


# ---------------------------------------------------------------------------
# Track resolution inside the loop (flag-gated; live classifier untouched)
# ---------------------------------------------------------------------------

def resolve_loop_track(text: str, transcript: str = "") -> dict[str, Any]:
    """Resolve the business track for the 360 loop.

    Uses the live classifier first. When it answers "ask" but the car_sales
    signal is strong, the loop treats the turn as car_sales FOR PLAYBOOK
    PURPOSES ONLY — this routing exists solely behind the feature flag and
    does not modify live classification.
    """
    decision = classify_track(text or "")
    if decision.track in (TRACK_IMPORT_EXPORT, TRACK_MY_CUBA_CASH):
        return {
            "track": decision.track,
            "source": "live_classifier",
            "confidence": round(decision.confidence, 2),
            "car_signal": 0.0,
        }
    if decision.track == TRACK_ASK and transcript.strip():
        inherited = classify_track(transcript[-3000:])
        if inherited.track in (TRACK_IMPORT_EXPORT, TRACK_MY_CUBA_CASH):
            return {
                "track": inherited.track,
                "source": "history",
                "confidence": round(inherited.confidence, 2),
                "car_signal": 0.0,
            }
    car_score = car_signal_score(text or "")
    if car_score >= CAR_SIGNAL_THRESHOLD:
        return {
            "track": TRACK_CAR_SALES,
            "source": "car_signals_flag_gated",
            "confidence": round(car_score, 2),
            "car_signal": round(car_score, 2),
        }
    return {
        "track": TRACK_ASK,
        "source": "live_classifier",
        "confidence": round(decision.confidence, 2),
        "car_signal": round(car_score, 2),
    }


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

async def run_sales_turn(
    *,
    text: str,
    contact_name: str | None = None,
    sender_phone: str | None = None,
    audio_bytes: bytes | None = None,
    audio_mime_hint: str = "audio/ogg",
    media_items: list[dict[str, Any]] | None = None,
    owner_context: bool = False,
    listing: dict[str, Any] | None = None,
    verified_amounts: list[Any] | None = None,
) -> dict[str, Any]:
    """Run one perceive → reason → act → reflect cycle.

    Returns {
      "reply": str,                 # Sofia's message ("" when escalated)
      "action_taken": str,          # reply | escalate | draft_only
      "track": str,
      "escalated": bool,
      "brief": dict | None,         # owner brief when escalated
      "proposed_tool_calls": [...], # recorded, never executed
      "audit": {...},
    }
    """
    audit: dict[str, Any] = {"loop": "sofia_360_salesperson", "flag": FLAG_ENV}

    # -- PERCEIVE ---------------------------------------------------------
    perception: dict[str, Any] = {"text": text or ""}
    if audio_bytes:
        stt = await transcribe_audio_seam(audio_bytes, mime_hint=audio_mime_hint)
        perception["audio"] = {k: v for k, v in stt.items() if k != "text"}
        if stt.get("ok") and stt.get("text"):
            perception["text"] = stt["text"]
            perception["text_source"] = "voice_transcription"
        else:
            audit["audio_unavailable"] = stt.get("reason")
    effective_text = perception["text"]

    track_info = resolve_loop_track(effective_text)
    track = track_info["track"]
    audit["track_resolution"] = track_info

    # Media: resolve registration dicts through the runtime's existing
    # media-evaluation path (lazy import — the runtime imports this loop
    # lazily too, so there is no import cycle at module load).
    media_evaluations: list[dict[str, Any]] = []
    if media_items:
        try:
            from sofia_whatsapp_runtime import _evaluate_turn_media

            media_evaluations = await _evaluate_turn_media(
                media_items,
                track=track if track != TRACK_ASK else TRACK_IMPORT_EXPORT,
                text=effective_text,
                language=detect_language(effective_text) or "es",
            )
        except Exception as exc:
            media_evaluations = [{
                "ok": False, "reason": f"media_resolution_failed:{type(exc).__name__}",
            }]
    perception["media_evaluations"] = [
        {k: v for k, v in ev.items() if k != "raw"} for ev in media_evaluations
    ]
    audit["media_evaluated"] = sum(1 for ev in media_evaluations if ev.get("ok"))
    audit["media_failed"] = sum(1 for ev in media_evaluations if not ev.get("ok"))

    # -- REASON -----------------------------------------------------------
    profile: dict[str, Any] = {}
    playbook: dict[str, Any] | None = None
    if track in (TRACK_IMPORT_EXPORT, TRACK_MY_CUBA_CASH, TRACK_CAR_SALES):
        playbook = get_playbook(track)
        try:
            profile = await build_customer_360(
                phone=sender_phone, lead_id=None, business=track
            )
        except Exception:
            profile = {"business": track, "backend_degraded": True}

    state = _state_from_profile(profile, track)
    qualified = is_minimum_qualified(track, state) if playbook else False
    next_q = (
        next_qualification_question(track, state, profile.get("language") or "es")
        if playbook and not qualified
        else None
    )
    audit["reasoning"] = {
        "deal_stage": profile.get("deal_stage"),
        "minimum_qualified": qualified,
        "next_qualification_question": bool(next_q),
    }

    # -- ACT --------------------------------------------------------------
    # Escalation check: explicit triggers supplied by the caller surface
    # here; the loop itself escalates on guardrail failure below.
    escalate_trigger: str | None = None
    if track == TRACK_CAR_SALES and _asks_legality(effective_text):
        escalate_trigger = "legality_question"
    if track == TRACK_CAR_SALES and _asks_shipping(effective_text):
        escalate_trigger = "cross_border_shipping"

    if escalate_trigger:
        brief = build_owner_brief(
            business=track,
            trigger=escalate_trigger,
            profile=profile,
            customer_ask=effective_text,
            contact_name=contact_name,
            phone=sender_phone,
            language=profile.get("language") or "es",
            what_sofia_tried=["Classified the inquiry and checked the playbook triggers."],
        )
        record_result = await record_escalation(brief)
        await _reflect(
            signal="loop_escalated",
            lesson=f"360 loop escalated on {escalate_trigger} for {track}; brief recorded, customer not messaged.",
            metadata={"track": track, "trigger": escalate_trigger},
        )
        return {
            "reply": _escalation_customer_note(profile.get("language") or "es"),
            "action_taken": "escalate",
            "track": track,
            "escalated": True,
            "brief": brief,
            "brief_record": record_result,
            "proposed_tool_calls": [],
            "audit": audit,
        }

    # Normal path: delegate reply generation to the existing runtime
    # pipeline (single source of truth for prompts), then guard it.
    from sofia_whatsapp_runtime import generate_sofia_reply

    reply = await generate_sofia_reply(
        perception["text"] or text,
        contact_name,
        owner_context=owner_context,
        sender_phone=sender_phone,
    )

    guards = validate_outbound(
        reply_text=reply,
        track=track,
        listing=listing,
        verified_amounts=verified_amounts,
        is_first_substantive=not (profile.get("outbound_count") or 0),
    )
    audit["guards"] = guards
    if not guards["ok"]:
        brief = build_owner_brief(
            business=track if track in (TRACK_IMPORT_EXPORT, TRACK_MY_CUBA_CASH, TRACK_CAR_SALES) else TRACK_IMPORT_EXPORT,
            trigger=_guard_trigger(track),
            profile=profile if profile.get("business") == track else None,
            customer_ask=effective_text,
            contact_name=contact_name,
            phone=sender_phone,
            language=profile.get("language") or "es",
            what_sofia_tried=[f"Drafted a reply but guardrails blocked it: {guards['violations'][:3]}"],
        )
        record_result = await record_escalation(brief)
        await _reflect(
            signal="loop_guardrail_block",
            lesson="360 loop blocked its own draft reply on negotiation guardrails and escalated instead of sending.",
            metadata={"violations": guards["violations"][:5]},
        )
        return {
            "reply": "",
            "action_taken": "escalate",
            "track": track,
            "escalated": True,
            "brief": brief,
            "brief_record": record_result,
            "proposed_tool_calls": [],
            "audit": audit,
        }

    await _reflect(
        signal="loop_reply_ok",
        lesson="360 loop completed perceive→reason→act→reflect with guardrails passing.",
        metadata={"track": track, "qualified": qualified},
    )
    return {
        "reply": reply,
        "action_taken": "reply",
        "track": track,
        "escalated": False,
        "brief": None,
        "proposed_tool_calls": _propose_tool_calls(track, state, qualified),
        "audit": audit,
    }


def _state_from_profile(profile: dict[str, Any], track: str) -> dict[str, Any]:
    """Flatten 360 interests/preferences into playbook qualification state."""
    state: dict[str, Any] = {}
    for pref_key, pref_value in (profile.get("preferences") or {}).items():
        state[pref_key] = pref_value
    # Interests become soft state (presence signals, not facts).
    state["_interests"] = [i["keyword"] for i in (profile.get("interests") or [])]
    return state


def _propose_tool_calls(
    track: str, state: dict[str, Any], qualified: bool
) -> list[dict[str, Any]]:
    """Tool calls the loop WOULD make — recorded for the audit trail.

    Never executed autonomously. The car-arms branch (separate repo)
    implements the real registry; this documents intent only.
    """
    if track != TRACK_CAR_SALES or not qualified:
        return []
    return [
        {
            "tool": "match_listings_to_buyer",
            "intent": "Find verified inventory matching the qualified buyer.",
            "executes_autonomously": False,
            "note": "Requires the car-arms branch registry; runs only with Juan's approval.",
        }
    ]


def _asks_legality(text: str) -> bool:
    t = (text or "").lower()
    return any(
        kw in t
        for kw in (
            "legal", "ilegal", "importar", "aduana", "customs",
            "puedo llevar", "se puede importar", "can i import",
        )
    )


def _asks_shipping(text: str) -> bool:
    t = (text or "").lower()
    return any(
        kw in t
        for kw in (
            "enviar el carro", "enviar un carro", "llevar el carro",
            "ship the car", "shipping a car", "flete del carro",
            "transportar el auto",
        )
    )


def _guard_trigger(track: str) -> str:
    if track == TRACK_CAR_SALES:
        return "fee_dispute"
    if track == TRACK_IMPORT_EXPORT:
        return "compliance_flag"
    return "intake_lookup_failed"


def _escalation_customer_note(language: str) -> str:
    if language == "en":
        return (
            "Thanks — this one needs Juan's eyes specifically. "
            "I've flagged it for him and he'll get back to you shortly."
        )
    return (
        "Gracias — esto lo tiene que ver Juan directamente. "
        "Ya se lo pasé y te contactamos en breve."
    )


async def _reflect(*, signal: str, lesson: str, metadata: dict[str, Any] | None = None) -> None:
    """Record a lesson from evidence only — outcome signals, never PII."""
    try:
        from sofia_adaptive_intelligence import record_lesson

        safe_meta = {
            k: v for k, v in (metadata or {}).items()
            if k in ("track", "trigger", "qualified", "violations")
        }
        await record_lesson(lesson=lesson, signal=signal, metadata=safe_meta)
    except Exception:
        pass
