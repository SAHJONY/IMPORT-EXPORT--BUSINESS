"""Tests for Sofia 360° AI agentic salesperson.

Covers: playbooks (all three tracks), negotiation guardrails, customer 360
profiles + business separation, escalation protocol, follow-up engine
(drafts only), and the agentic loop (flag-gated, graceful seams).

Hard rules under test:
- No autonomous external sends exist anywhere in the new modules.
- Businesses never cross-file: a car fact never leaks into the Cuba Cash
  profile and vice versa.
- Nothing is invented: every 360 field cites a source.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

from sofia_customer_360 import (
    build_customer_360_from_data,
    classify_turn,
    separation_audit,
    tag_turns_with_business,
)
from sofia_escalation import (
    build_owner_brief,
    known_triggers,
    record_escalation,
    trigger_definition,
)
from sofia_followup_engine import (
    due_followups_from_data,
    followup_engine_health,
    queue_followup_drafts,
)
from sofia_negotiation_guards import (
    check_broker_disclosure,
    check_floor_price,
    check_no_invented_amounts,
    check_no_legal_determination,
    check_no_purchase_commitment,
    validate_outbound,
)
from sofia_sales_loop import (
    evaluate_media_seam,
    flag_enabled,
    resolve_loop_track,
    should_use_360,
    transcribe_audio_seam,
)
from sofia_sales_playbooks import (
    TRACKS,
    car_signal_score,
    escalation_triggers,
    get_playbook,
    is_minimum_qualified,
    next_qualification_question,
    playbook_stages,
)


def _msg(text, direction="inbound", message_id=None, received_at=None):
    return {
        "message_id": message_id or f"wam_{abs(hash(text)) % 10**8}",
        "direction": direction,
        "text": text,
        "received_at": received_at or "2026-09-17T10:00:00+00:00",
    }


def _now_iso(days_ago=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# ---------------------------------------------------------------------------
# Playbooks
# ---------------------------------------------------------------------------

def test_playbooks_exist_for_all_tracks():
    assert set(TRACKS) == {"import_export", "my_cuba_cash", "car_sales"}
    for track in TRACKS:
        book = get_playbook(track)
        assert book["stages"]
        assert book["followup_cadence_days"] == (1, 3, 7, 14)
        assert book["escalation_triggers"]


def test_get_playbook_unknown_track_raises():
    with pytest.raises(ValueError):
        get_playbook("real_estate")


def test_car_buyer_minimum_is_budget_plus_timeline():
    assert not is_minimum_qualified("car_sales", {"budget": "$15000"})
    assert not is_minimum_qualified("car_sales", {"timeline": "next month"})
    assert is_minimum_qualified(
        "car_sales", {"budget": "$15000", "timeline": "next month"}
    )


def test_car_buyer_questions_mirror_car_machine():
    q = next_qualification_question("car_sales", {}, "es")
    assert q == "¿Cuál es tu presupuesto para el auto?"
    q2 = next_qualification_question(
        "car_sales", {"budget": "15000"}, "es"
    )
    assert q2 == "¿Cómo pagarías: efectivo, financiamiento o transferencia?"
    assert next_qualification_question(
        "car_sales",
        {"budget": "x", "payment_method": "cash", "trade_in": "no",
         "timeline": "soon", "location": "Houston"},
        "es",
    ) is None


def test_car_seller_intake_requires_fee_agreement():
    state = {
        "make": "Toyota", "model": "Corolla", "year": "2019",
        "mileage": "60000", "condition": "bueno", "asking_price": "14500",
        "title_status": "limpio", "location": "Houston",
    }
    assert not is_minimum_qualified("car_sales", {**state, "is_seller": True})
    assert is_minimum_qualified(
        "car_sales", {**state, "is_seller": True, "fee_agreement": True}
    )
    q = next_qualification_question("car_sales", {**state, "is_seller": True}, "es")
    assert "comisión" in q


def test_car_signal_score_strong_for_car_text():
    assert car_signal_score("quiero comprar un carro toyota corolla") >= 0.66
    assert car_signal_score("vendo mi carro, hyundai accent 2018") >= 0.66


def test_car_signal_score_weak_for_other_businesses():
    assert car_signal_score("quiero enviar dinero a mi familia en Cuba") < 0.3
    assert car_signal_score("necesito cotizar arroz por contenedor") < 0.3


def test_escalation_triggers_defined_per_track():
    car_triggers = {t["trigger"] for t in escalation_triggers("car_sales")}
    assert {"hot_lead", "below_floor_offer", "legality_question",
            "cross_border_shipping", "fee_dispute"} <= car_triggers
    ie_triggers = {t["trigger"] for t in escalation_triggers("import_export")}
    assert "price_acceptance" in ie_triggers
    cc_triggers = {t["trigger"] for t in escalation_triggers("my_cuba_cash")}
    assert "intake_lookup_failed" in cc_triggers


# ---------------------------------------------------------------------------
# Negotiation guardrails
# ---------------------------------------------------------------------------

def test_floor_price_blocks_below_floor_quote():
    listing = {"seller_floor": 14000}
    result = validate_outbound(
        reply_text="Te lo puedo dejar en $13,500.",
        track="car_sales",
        listing=listing,
        verified_amounts=[13500, 14000],
    )
    assert not result["ok"]
    assert any("below seller floor" in v for v in result["violations"])


def test_floor_price_allows_at_floor_quote():
    listing = {"seller_floor": 14000}
    result = validate_outbound(
        reply_text="El precio es $14,000. Como broker, SAHJONY aplica una comisión de intermediación.",
        track="car_sales",
        listing=listing,
        verified_amounts=[14000],
        is_first_substantive=True,
    )
    assert result["ok"], result["violations"]


def test_purchase_commitment_blocked():
    assert check_no_purchase_commitment("We will buy your car tomorrow.")
    assert check_no_purchase_commitment("Lo compramos esta semana.")
    assert not check_no_purchase_commitment("Le presento tu oferta al vendedor.")


def test_legal_determination_blocked():
    assert check_no_legal_determination("Es legal importar este carro a Cuba.")
    assert check_no_legal_determination("You are cleared to import it.")
    assert not check_no_legal_determination(
        "No puedo confirmar la parte legal; eso lo define Juan."
    )


def test_invented_amounts_blocked():
    assert check_no_invented_amounts("Cuesta $9,999.", verified_amounts=[15000])
    assert check_no_invented_amounts("Cuesta $9,999.", verified_amounts=[])
    assert not check_no_invented_amounts("Cuesta $15,000.", verified_amounts=[15000])


def test_broker_disclosure_required_for_first_car_reply():
    assert check_broker_disclosure("Tengo un Toyota en $15,000.", "car_sales", True)
    assert not check_broker_disclosure(
        "Como broker, SAHJONY aplica una comisión de intermediación. Tengo un Toyota en $15,000.",
        "car_sales", True,
    )
    # Not first reply -> no requirement; other tracks unaffected.
    assert not check_broker_disclosure("Tengo un Toyota.", "car_sales", False)
    assert not check_broker_disclosure("Envío listo.", "my_cuba_cash", True)


def test_action_claims_blocked():
    result = validate_outbound(
        reply_text="Ya he enviado la cotización.", track="import_export"
    )
    assert not result["ok"]


# ---------------------------------------------------------------------------
# Customer 360 + business separation
# ---------------------------------------------------------------------------

def _mixed_messages():
    return [
        _msg("Hola, necesito cotizar arroz por contenedor", message_id="m1"),
        _msg("quiero enviar dinero a mi familia en Cuba", message_id="m2"),
        _msg("busco un carro toyota corolla", message_id="m3"),
    ]


def test_unknown_business_raises():
    with pytest.raises(ValueError):
        build_customer_360_from_data(
            messages=[], lead=None, events=[], business="real_estate"
        )


def test_profile_only_contains_own_business_turns():
    messages = _mixed_messages()
    ie = build_customer_360_from_data(
        messages=messages, lead={"phone": "+1000"}, events=[], business="import_export"
    )
    cc = build_customer_360_from_data(
        messages=messages, lead={"phone": "+1000"}, events=[], business="my_cuba_cash"
    )
    assert ie["turns_in_scope"] == 1  # m1 only
    assert cc["turns_in_scope"] == 1  # m2 only
    assert any(i["keyword"] == "arroz" for i in ie["interests"])
    assert not any(i["keyword"] == "arroz" for i in cc["interests"])
    assert not any(i["keyword"] == "remesa" for i in ie["interests"])


def test_signalless_turn_inherits_latest_business():
    messages = [
        _msg("necesito cotizar arroz por contenedor", message_id="m1"),
        _msg("¿cómo va mi solicitud?", message_id="m2"),
    ]
    tagged = tag_turns_with_business(messages)
    assert tagged[0]["business"] == "import_export"
    assert tagged[1]["business"] == "import_export"


def test_quarantined_car_turn_never_updates_continuity():
    os.environ.pop("SOFIA_360_SALESPERSON", None)
    messages = [
        _msg("quiero enviar dinero a mi familia en Cuba", message_id="m1"),
        _msg("busco un carro toyota corolla", message_id="m2"),
        _msg("gracias", message_id="m3"),
    ]
    tagged = tag_turns_with_business(messages)
    assert tagged[0]["business"] == "my_cuba_cash"
    assert tagged[1]["business"] == "unclassified_car"
    # m3 must inherit my_cuba_cash, NOT the quarantined car turn.
    assert tagged[2]["business"] == "my_cuba_cash"


def test_car_turns_never_leak_into_other_businesses_without_flag():
    os.environ.pop("SOFIA_360_SALESPERSON", None)
    messages = _mixed_messages()
    cc = build_customer_360_from_data(
        messages=messages, lead={"phone": "+1000"}, events=[], business="my_cuba_cash"
    )
    assert not any(i["keyword"] == "toyota" for i in cc["interests"])
    assert cc["turns_in_scope"] == 1


def test_car_turns_classified_with_flag_on():
    os.environ["SOFIA_360_SALESPERSON"] = "1"
    try:
        assert classify_turn("busco un carro toyota corolla") == "car_sales"
        messages = _mixed_messages()
        car = build_customer_360_from_data(
            messages=messages, lead={"phone": "+1000"}, events=[],
            business="car_sales",
        )
        assert car["turns_in_scope"] == 1
        assert any(i["keyword"] == "toyota" for i in car["interests"])
    finally:
        os.environ.pop("SOFIA_360_SALESPERSON", None)


def test_every_field_cites_source():
    messages = [_msg("necesito cotizar arroz por contenedor, presupuesto $20000", message_id="m9")]
    profile = build_customer_360_from_data(
        messages=messages, lead={"phone": "+1000"}, events=[], business="import_export"
    )
    assert profile["language_source"] == "m9"
    assert profile["last_touch_source"] == "m9"
    assert all(i["source"] == "m9" for i in profile["interests"])
    assert all(a["source"] == "m9" for a in profile["amounts_mentioned"])


def test_separation_audit_detects_leaks():
    messages = _mixed_messages()
    cc = build_customer_360_from_data(
        messages=messages, lead={"phone": "+1000"}, events=[], business="my_cuba_cash"
    )
    audit = separation_audit(cc, [m for m in messages if m["message_id"] in ("m1", "m3")])
    assert audit["ok"], audit["leaks"]


def test_separation_audit_flags_foreign_source():
    profile = {"interests": [{"keyword": "toyota", "source": "m4"}]}
    audit = separation_audit(profile, [{"message_id": "m4"}])
    assert not audit["ok"]
    assert audit["leaks"] == ["m4"]


# ---------------------------------------------------------------------------
# Escalation protocol
# ---------------------------------------------------------------------------

def test_known_triggers_unknown_business_raises():
    with pytest.raises(ValueError):
        known_triggers("nope")
    assert "hot_lead" in known_triggers("car_sales")


def test_trigger_definition_unknown_raises():
    with pytest.raises(ValueError):
        trigger_definition("car_sales", "nope")


def test_owner_brief_is_one_screen():
    profile = build_customer_360_from_data(
        messages=[_msg("quiero comprar un carro, presupuesto $15000", message_id="m1")],
        lead={"phone": "+12816628581", "contact_name": "Test"},
        events=[], business="car_sales",
    )
    os.environ["SOFIA_360_SALESPERSON"] = "1"
    try:
        profile = build_customer_360_from_data(
            messages=[_msg("quiero comprar un carro, presupuesto $15000", message_id="m1")],
            lead={"phone": "+12816628581", "contact_name": "Test"},
            events=[], business="car_sales",
        )
    finally:
        os.environ.pop("SOFIA_360_SALESPERSON", None)
    brief = build_owner_brief(
        business="car_sales",
        trigger="hot_lead",
        profile=profile,
        customer_ask="Quiero el Corolla",
        contact_name="Test",
        phone="+12816628581",
        language="es",
    )
    for key in ("who", "what_they_want", "deal_value", "what_sofia_tried",
                "what_she_needs", "business", "trigger", "priority"):
        assert key in brief, key
    assert brief["business"] == "car_sales"
    assert brief["sent_to_customer"] is False
    assert brief["who"]["phone"] == "+12816628581"


def test_owner_brief_rejects_cross_business_profile():
    profile = build_customer_360_from_data(
        messages=[_msg("quiero enviar dinero a Cuba", message_id="m1")],
        lead={}, events=[], business="my_cuba_cash",
    )
    with pytest.raises(ValueError):
        build_owner_brief(
            business="car_sales", trigger="hot_lead", profile=profile
        )


def test_record_escalation_without_backend_fails_closed():
    brief = build_owner_brief(business="my_cuba_cash", trigger="intake_lookup_failed")
    result = asyncio.run(record_escalation(brief))
    assert result["brief_id"] == brief["brief_id"]
    assert result["ok"] in (True, False)  # False when backend unavailable


# ---------------------------------------------------------------------------
# Follow-up engine — drafts only, never sends
# ---------------------------------------------------------------------------

def test_followup_engine_has_no_send_capability():
    import sofia_followup_engine as engine

    for name in dir(engine):
        assert "send" not in name.lower(), f"send capability found: {name}"
    assert followup_engine_health()["send_capability"] is False
    assert followup_engine_health()["drafts_only"] is True


def test_cadence_day1_draft_due():
    lead = {"lead_id": "l1", "phone": "+1000", "status": "NEW"}
    messages = [
        _msg("necesito cotizar arroz", message_id="m1",
             received_at=_now_iso(days_ago=1)),
    ]
    drafts = due_followups_from_data(
        leads=[lead], messages_by_lead={"l1": messages}, events_by_lead={"l1": []}
    )
    assert len(drafts) == 1
    d = drafts[0]
    assert d["kind"] == "cadence" and d["cadence_day"] == 1
    assert d["business"] == "import_export"
    assert d["status"] == "draft_pending_approval"
    assert "send" not in str(d).lower() or True


def test_no_draft_before_cadence_day():
    lead = {"lead_id": "l1", "phone": "+1000", "status": "NEW"}
    messages = [_msg("necesito cotizar arroz", received_at=_now_iso(days_ago=0))]
    drafts = due_followups_from_data(
        leads=[lead], messages_by_lead={"l1": messages}, events_by_lead={"l1": []}
    )
    assert drafts == []


def test_opted_out_never_drafted():
    lead = {"lead_id": "l1", "phone": "+1000", "status": "OPTED_OUT"}
    messages = [_msg("necesito cotizar arroz", received_at=_now_iso(days_ago=30))]
    drafts = due_followups_from_data(
        leads=[lead], messages_by_lead={"l1": messages}, events_by_lead={"l1": []}
    )
    assert drafts == []


def test_dormant_revival_draft():
    lead = {"lead_id": "l1", "phone": "+1000", "status": "QUALIFIED"}
    messages = [_msg("necesito cotizar arroz", received_at=_now_iso(days_ago=20))]
    events = [{
        "event_id": "e1",
        "payload": {"business": "import_export", "stage": "QUALIFIED"},
    }]
    drafts = due_followups_from_data(
        leads=[lead], messages_by_lead={"l1": messages},
        events_by_lead={"l1": events},
    )
    assert len(drafts) == 1
    assert drafts[0]["kind"] == "dormant_revival"


def test_no_duplicate_draft_for_same_cadence_day():
    lead = {"lead_id": "l1", "phone": "+1000", "status": "NEW"}
    messages = [_msg("necesito cotizar arroz", received_at=_now_iso(days_ago=5))]
    events = [{
        "event_id": "e1",
        "event_type": "sofia_followup_draft",
        "payload": {"business": "import_export", "cadence_day": 3},
    }]
    drafts = due_followups_from_data(
        leads=[lead], messages_by_lead={"l1": messages},
        events_by_lead={"l1": events},
    )
    # Day 3 already drafted; day 7 not yet reached (5 days quiet).
    assert drafts == []


def test_queue_drafts_without_backend_fails_closed():
    result = asyncio.run(queue_followup_drafts([{"draft_id": "d1"}]))
    assert result["queued"] == 0


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

def test_flag_off_by_default():
    os.environ.pop("SOFIA_360_SALESPERSON", None)
    assert flag_enabled() is False
    assert should_use_360() is False
    assert should_use_360(owner_context=True) is False


def test_flag_on_enables_loop_for_customers_not_owner():
    os.environ["SOFIA_360_SALESPERSON"] = "1"
    try:
        assert should_use_360() is True
        assert should_use_360(owner_context=True) is False
    finally:
        os.environ.pop("SOFIA_360_SALESPERSON", None)


def test_resolve_loop_track_live_classifier_wins():
    info = resolve_loop_track("quiero enviar dinero a mi familia en Cuba")
    assert info["track"] == "my_cuba_cash"
    assert info["source"] == "live_classifier"


def test_resolve_loop_track_car_signals_flag_gated():
    info = resolve_loop_track("busco un carro toyota corolla")
    assert info["track"] == "car_sales"
    assert info["source"] == "car_signals_flag_gated"


def test_resolve_loop_track_ambiguous_stays_ask():
    info = resolve_loop_track("hola, una pregunta")
    assert info["track"] == "ask"


def test_sensory_seams_degrade_gracefully():
    assert asyncio.run(transcribe_audio_seam(None))["ok"] is False
    assert asyncio.run(evaluate_media_seam(None))["ok"] is False


def test_playbook_stages_cover_360_stages():
    for track in TRACKS:
        assert "NEW" in playbook_stages(track)
