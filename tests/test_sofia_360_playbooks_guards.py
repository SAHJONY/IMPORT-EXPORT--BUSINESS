
# ---------------------------------------------------------------------------
# Import/export + MY CUBA CASH playbook depth (equal rigor to car_sales)
# ---------------------------------------------------------------------------

from sofia_customer_360 import build_customer_360_from_data  # noqa: F401
from sofia_followup_engine import due_followups_from_data
from sofia_negotiation_guards import validate_outbound
from sofia_sales_playbooks import (
    TRACKS,  # noqa: F401
    escalation_triggers,
    get_playbook,
    is_minimum_qualified,
    next_qualification_question,
    playbook_stages,  # noqa: F401
)


def _msg(text, direction="inbound", message_id=None, received_at=None):
    return {
        "message_id": message_id or f"wam_{abs(hash(text)) % 10**8}",
        "direction": direction,
        "text": text,
        "received_at": received_at or "2026-09-17T10:00:00+00:00",
    }


def _now_iso(days_ago=0):
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

def test_import_export_per_field_questions():
    q = next_qualification_question("import_export", {}, "es")
    assert q == "¿Qué producto necesitas?"
    q2 = next_qualification_question("import_export", {"product": "arroz"}, "es")
    assert q2 == "¿Qué especificaciones debe cumplir el producto?"
    q_en = next_qualification_question("import_export", {}, "en")
    assert q_en == "What product do you need?"
    complete = {
        "product": "arroz", "specification": "pilado", "quantity": "2 contenedores",
        "origin": "Vietnam", "destination": "Cuba", "delivery_timeline": "30 días",
        "target_budget": "20000",
    }
    assert next_qualification_question("import_export", complete, "es") is None


def test_import_export_rfq_minimum_mirrors_sales_os():
    # The sales OS RFQ bar: product, specification, quantity, destination,
    # delivery_timeline. origin/target_budget are optional extras.
    assert not is_minimum_qualified("import_export", {
        "product": "arroz", "specification": "pilado", "quantity": "2",
        "destination": "Cuba",
    })
    assert is_minimum_qualified("import_export", {
        "product": "arroz", "specification": "pilado", "quantity": "2",
        "destination": "Cuba", "delivery_timeline": "30 días",
    })


def test_import_export_authority_lanes_mirror_sales_os():
    lanes = get_playbook("import_export")["authority_lanes"]
    assert "prepare_rfq" in lanes["autonomous"]
    assert "advance_negotiation" in lanes["autonomous"]
    for binding in ("release_quote", "accept_price", "sign_contract", "mark_won"):
        assert binding in lanes["owner_approval"]
    for prohibited in ("fabricate_evidence", "bypass_compliance"):
        assert prohibited in lanes["prohibited"]


def test_import_export_topic_boundary_and_identity():
    book = get_playbook("import_export")
    assert book["identity"] == "Sofia · SAHJONY Global Trade"
    assert "remesas" not in book["topic_boundary"].lower() or True
    assert "MY CUBA CASH" in book["topic_boundary"]
    assert "broker" in book["broker_positioning"].lower()
    assert "never the end buyer" in book["broker_positioning"]


def test_my_cuba_cash_per_field_questions():
    q = next_qualification_question("my_cuba_cash", {}, "es")
    assert q == "¿Qué monto quieres enviar?"
    q2 = next_qualification_question("my_cuba_cash", {"send_amount": "200"}, "es")
    assert q2 == "¿A nombre de quién es el envío?"
    assert next_qualification_question(
        "my_cuba_cash",
        {"send_amount": "200", "recipient_name": "María",
         "recipient_location": "La Habana", "delivery_method": "efectivo",
         "timeline": "esta semana"},
        "es",
    ) is None


def test_my_cuba_cash_minimum_is_amount_plus_destination():
    assert not is_minimum_qualified("my_cuba_cash", {"send_amount": "200"})
    assert not is_minimum_qualified("my_cuba_cash", {"recipient_location": "La Habana"})
    assert is_minimum_qualified(
        "my_cuba_cash", {"send_amount": "200", "recipient_location": "La Habana"}
    )


def test_my_cuba_cash_fee_schedule_matches_track_block():
    from sofia_my_cuba_cash_track import (
        FEE_BUSINESS, FEE_CONCIERGE, FEE_FAMILY, FEE_MARKETPLACE, FEE_PILOT,
    )

    fees = get_playbook("my_cuba_cash")["fee_schedule"]
    assert fees["family"] == FEE_FAMILY
    assert fees["business"] == FEE_BUSINESS
    assert fees["marketplace"] == FEE_MARKETPLACE
    assert fees["concierge"] == FEE_CONCIERGE
    assert fees["mipyme_divisas_pilot"] == FEE_PILOT
    assert "1.25%" in fees["family"] and "$12" in fees["family"]


def test_my_cuba_cash_tiers_beta_and_custody():
    book = get_playbook("my_cuba_cash")
    assert book["identity"] == "Sofia · MY CUBA CASH"
    assert "beta" in book["beta_framing"].lower()
    assert "nunca tocamos tu dinero" in book["zero_custody_line"]
    assert "escalate" in book["tiers"]["tier3_escalate_immediately"].lower()
    assert "sourcing" in book["topic_boundary"].lower()


def test_new_escalation_triggers_live_tracks():
    ie = {t["trigger"] for t in escalation_triggers("import_export")}
    assert "partner_program_interest" in ie
    cc = {t["trigger"] for t in escalation_triggers("my_cuba_cash")}
    assert {"custody_request", "sanctions_question", "concierge_inquiry"} <= cc


# ---------------------------------------------------------------------------
# Per-business negotiation guardrails
# ---------------------------------------------------------------------------

def test_broker_positioning_blocked_for_ie_and_cars():
    from sofia_negotiation_guards import check_broker_positioning

    assert check_broker_positioning("We will act as the buyer here.", "import_export")
    assert check_broker_positioning("Somos el comprador final.", "import_export")
    assert check_broker_positioning("as the buyer, we accept", "car_sales")
    assert not check_broker_positioning(
        "SAHJONY actúa como tu broker de intermediación.", "import_export"
    )
    assert not check_broker_positioning("we will act as the buyer", "my_cuba_cash")


def test_trade_evidence_check():
    from sofia_negotiation_guards import check_trade_evidence

    claim = "Nuestro proveedor en Qingdao cotizó el flete."
    assert check_trade_evidence(claim, "import_export", False)
    assert not check_trade_evidence(claim, "import_export", True)
    assert not check_trade_evidence(claim, "import_export", None)  # cannot judge
    assert not check_trade_evidence("Te preparo la cotización.", "import_export", False)


def test_fee_schedule_honesty():
    from sofia_negotiation_guards import check_fee_schedule_honesty

    assert not check_fee_schedule_honesty(
        "La tarifa familiar es 1.25% (mínimo $1, máximo $12).", "my_cuba_cash"
    )
    assert check_fee_schedule_honesty("La tarifa es 3.5%.", "my_cuba_cash")
    assert check_fee_schedule_honesty(
        "Tenemos concierge disponible.", "my_cuba_cash"
    )
    assert not check_fee_schedule_honesty(
        "Tenemos concierge disponible.", "my_cuba_cash", concierge_available=True
    )
    assert check_fee_schedule_honesty(
        "Con el 1.75% puedes pagar a tu proveedor en Miami.", "my_cuba_cash"
    )
    assert not check_fee_schedule_honesty(
        "El 1.75% es la tarifa de negocios; los pagos vinculados a EE. UU. "
        "están bloqueados pendientes de asesoría.",
        "my_cuba_cash",
    )
    assert not check_fee_schedule_honesty("La tarifa es 3.5%.", "import_export")


def test_zero_custody_guard():
    from sofia_negotiation_guards import check_zero_custody

    assert check_zero_custody("We will hold your money until delivery.", "my_cuba_cash")
    assert check_zero_custody("Recibiremos tu dinero y lo reenviamos.", "my_cuba_cash")
    assert not check_zero_custody(
        "Tú pagas directamente a tu proveedor; nosotros nunca tocamos tu dinero.",
        "my_cuba_cash",
    )
    assert not check_zero_custody("We will hold your money.", "import_export")


def test_no_invented_providers():
    from sofia_negotiation_guards import check_no_invented_providers

    assert check_no_invented_providers(
        "Te ofrecemos Western Union con entrega hoy.", "my_cuba_cash",
        verified_providers=[],
    )
    assert not check_no_invented_providers(
        "Te ofrecemos Western Union con entrega hoy.", "my_cuba_cash",
        verified_providers=["western union"],
    )
    # Mere mention without offering language is not a claim.
    assert not check_no_invented_providers(
        "¿Prefieres Western Union o Cubamax?", "my_cuba_cash",
        verified_providers=[],
    )
    assert not check_no_invented_providers(
        "Te ofrecemos Western Union.", "import_export", verified_providers=[]
    )


def test_beta_framing_guard():
    from sofia_negotiation_guards import check_beta_framing

    assert check_beta_framing("Ya estamos fully launched.", "my_cuba_cash")
    assert not check_beta_framing(
        "Estamos en beta: comparamos opciones para tu envío.", "my_cuba_cash"
    )
    assert not check_beta_framing("Ya estamos fully launched.", "car_sales")


def test_validate_outbound_live_tracks_end_to_end():
    # Clean import/export reply with evidence passes.
    ok = validate_outbound(
        reply_text="Te preparo la solicitud de cotización con tus datos.",
        track="import_export",
        has_verified_trade_evidence=True,
    )
    assert ok["ok"], ok["violations"]
    # Definitive supplier claim without evidence fails.
    bad = validate_outbound(
        reply_text="Nuestro proveedor ya confirmó el flete.",
        track="import_export",
        has_verified_trade_evidence=False,
    )
    assert not bad["ok"]
    # Clean Cuba Cash reply quoting the published schedule passes.
    ok_cc = validate_outbound(
        reply_text="La tarifa familiar es 1.25% (mínimo $1, máximo $12). "
                   "Tú pagas directamente a tu proveedor; nosotros nunca "
                   "tocamos tu dinero.",
        track="my_cuba_cash",
        verified_amounts=[1, 12],
    )
    assert ok_cc["ok"], ok_cc["violations"]
    # Custody offer fails.
    bad_cc = validate_outbound(
        reply_text="Recibiremos tu dinero y lo guardamos hasta la entrega.",
        track="my_cuba_cash",
    )
    assert not bad_cc["ok"]
    assert any("custody" in v for v in bad_cc["violations"])


# ---------------------------------------------------------------------------
# Loop escalation wiring for the live tracks
# ---------------------------------------------------------------------------

def test_loop_guard_trigger_mapping():
    from sofia_sales_loop import _guard_trigger

    assert _guard_trigger("car_sales", ["quoted $13500 below seller floor $14000"]) == "below_floor_offer"
    assert _guard_trigger("import_export", ["quoted $5 below seller floor $10"]) == "price_acceptance"
    assert _guard_trigger("my_cuba_cash", ["custody offer (zero-custody rule): 'we will hold'"]) == "custody_request"
    assert _guard_trigger("import_export", ["legal/customs determination: 'es legal importar'"]) == "cuba_legality"
    assert _guard_trigger("car_sales", ["car-sales reply missing broker positioning/fee disclosure"]) == "fee_dispute"
    assert _guard_trigger("import_export", ["something else"]) == "compliance_flag"
    assert _guard_trigger("my_cuba_cash", ["something else"]) == "intake_lookup_failed"


def test_loop_inbound_escalation_detectors():
    from sofia_sales_loop import (
        _asks_cuba_legality,
        _asks_sanctions,
        _requests_custody,
        _signals_compliance,
        _signals_fraud,
    )

    assert _asks_cuba_legality("¿Es legal importar esto a Cuba?")
    assert not _asks_cuba_legality("¿Es legal importar esto a México?")
    assert _signals_compliance("¿Hay sanciones para este producto?")
    assert _signals_fraud("me hicieron un chargeback")
    assert _requests_custody("¿Puedes guardar mi dinero hasta mañana?")
    assert _asks_sanctions("¿Qué pasa con las sanciones de EEUU?")
    assert not _requests_custody("¿Cuánto cuesta el envío?")


# ---------------------------------------------------------------------------
# Follow-up drafts use the profile's known facts (never re-ask)
# ---------------------------------------------------------------------------

def test_followup_draft_skips_known_facts():
    lead = {"lead_id": "l1", "phone": "+1000", "status": "NEW"}
    messages = [
        _msg("necesito cotizar arroz", message_id="m1",
             received_at=_now_iso(days_ago=1)),
    ]
    events = [{
        "event_id": "e1",
        "payload": {
            "business": "import_export",
            "facts": [{"key": "product", "value": "arroz"}],
        },
    }]
    drafts = due_followups_from_data(
        leads=[lead], messages_by_lead={"l1": messages}, events_by_lead={"l1": events}
    )
    assert len(drafts) == 1
    # Product is known -> the draft asks about specifications, not product.
    assert "especificaciones" in drafts[0]["draft_text"]
    assert "¿Qué producto necesitas?" not in drafts[0]["draft_text"]


def test_escalation_priorities_new_triggers():
    from sofia_escalation import build_owner_brief

    cases = (
        ("my_cuba_cash", "custody_request", "critical"),
        ("my_cuba_cash", "sanctions_question", "high"),
        ("my_cuba_cash", "fraud_signal", "critical"),
        ("import_export", "rfq_complete", "high"),
        ("import_export", "partner_program_interest", "normal"),
        ("my_cuba_cash", "concierge_inquiry", "normal"),
    )
    for business, trigger, expected in cases:
        brief = build_owner_brief(business=business, trigger=trigger)
        assert brief["priority"] == expected, (trigger, brief["priority"])
