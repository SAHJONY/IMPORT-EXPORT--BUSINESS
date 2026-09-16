"""Tests for Sofia's MY CUBA CASH business track.

Covers: track classifier accuracy (>=20 spec-derived samples, including the
ambiguous cases), PATCH allowlist enforcement, secret hygiene (header-only,
never in URL/logs, fail-closed without it), intake-inquiry and update-intent
detection, prompt-block content, and the generate_sofia_reply wiring helper.
"""
import asyncio
import json

import httpx
import pytest

from sofia_track_classifier import (
    TRACK_ASK,
    TRACK_IMPORT_EXPORT,
    TRACK_MY_CUBA_CASH,
    classify_track,
)
from sofia_my_cuba_cash_track import (
    IMPORT_EXPORT_TRACK_GUARD,
    MY_CUBA_CASH_SYSTEM_BLOCK,
    ZERO_CUSTODY_LINE,
)
import sofia_cubacash_intake_client as client


# ---------------------------------------------------------------------------
# 1. Classifier accuracy
# ---------------------------------------------------------------------------

CLASSIFIER_CASES = [
    # (message, expected_track)
    ("Hola, quiero enviar dinero a mi familia en Cuba", TRACK_MY_CUBA_CASH),
    ("¿Cuánto cuesta enviar 100 dólares a Cuba?", TRACK_MY_CUBA_CASH),
    ("¿Aceptan Western Union?", TRACK_MY_CUBA_CASH),
    ("Quiero información del piloto de $25", TRACK_MY_CUBA_CASH),
    ("Necesito pagarle a un proveedor, soy MIPYME", TRACK_MY_CUBA_CASH),
    ("Mi familia necesita divisas", TRACK_MY_CUBA_CASH),
    ("¿Qué tasa manejan?", TRACK_MY_CUBA_CASH),
    ("¿Hacen recargas a Cuba?", TRACK_MY_CUBA_CASH),
    ("¿Cuál es la comisión por enviar dinero?", TRACK_MY_CUBA_CASH),
    ("divisas para mi familia", TRACK_MY_CUBA_CASH),
    ("divisas para pagar a mi proveedor", TRACK_MY_CUBA_CASH),
    ("I want to send money to Cuba", TRACK_MY_CUBA_CASH),
    ("Je veux envoyer de l'argent à Cuba", TRACK_MY_CUBA_CASH),
    ("Necesito cotizar la importación de 500 sillas", TRACK_IMPORT_EXPORT),
    ("Busco proveedores en China", TRACK_IMPORT_EXPORT),
    ("¿Cuánto sale el flete de un contenedor?", TRACK_IMPORT_EXPORT),
    ("Quiero ser partner y referir clientes", TRACK_IMPORT_EXPORT),
    ("¿Me ayudas con la aduana?", TRACK_IMPORT_EXPORT),
    ("tengo una MIPYME", TRACK_ASK),
    ("¿Cuánto cuesta la comisión?", TRACK_ASK),
    ("¿Cuál es el precio?", TRACK_ASK),
    ("Hola", TRACK_ASK),
    ("Buenos días", TRACK_ASK),
    ("Quiero enviar dinero y también importar ropa", TRACK_ASK),
]


@pytest.mark.parametrize("message,expected", CLASSIFIER_CASES)
def test_classifier_accuracy(message, expected):
    decision = classify_track(message)
    assert decision.track == expected, f"{message!r} -> {decision.track} ({decision.signals})"


def test_classifier_confidence_floor():
    decision = classify_track("Hola, quiero enviar dinero a mi familia en Cuba")
    assert decision.confidence >= 0.70
    ambiguous = classify_track("Quiero enviar dinero y también importar ropa")
    assert ambiguous.track == TRACK_ASK
    assert ambiguous.confidence < 0.70


def test_classifier_never_guesses_on_empty():
    assert classify_track("").track == TRACK_ASK
    assert classify_track("...").track == TRACK_ASK


def test_mipyme_clarifying_question_spanish():
    decision = classify_track("tengo una MIPYME")
    assert decision.track == TRACK_ASK
    assert decision.clarifying_question is not None
    assert "MIPYME" in decision.clarifying_question
    assert "divisas" in decision.clarifying_question


def test_clarifying_question_follows_user_language():
    decision = classify_track("Hello")
    assert decision.track == TRACK_ASK
    assert decision.language == "en"
    assert "MY CUBA CASH" in (decision.clarifying_question or "")


def test_phrase_masking_prevents_double_count():
    # "pago a proveedor" is a MY CUBA CASH phrase; bare "proveedor" must not
    # also score for import/export.
    decision = classify_track("quiero hacer un pago a proveedor para mi mipyme")
    assert decision.track == TRACK_MY_CUBA_CASH
    assert not any("proveedor" in s and s.startswith("word:") for s in decision.signals)


# ---------------------------------------------------------------------------
# 2. PATCH allowlist
# ---------------------------------------------------------------------------

def test_update_allows_notes():
    assert client.validate_intake_update({"notes": "cliente confirmó proveedor"}) == {
        "notes": "cliente confirmó proveedor"
    }


@pytest.mark.parametrize("status", ["COLLECTING", "READY_FOR_REVIEW", "ON_HOLD", "CANCELLED"])
def test_update_allows_listed_statuses(status):
    assert client.validate_intake_update({"intake_status": status}) == {"intake_status": status}


@pytest.mark.parametrize("updates", [
    {"payment_status": "PAID"},
    {"requested_amount": 100},
    {"payment_evidence": "x"},
    {"remittance_intent": "x"},
    {"intake_status": "CONVERTED"},
    {"intake_status": "SHIPPED"},
    {"unknown_field": 1},
    {},
])
def test_update_blocks_disallowed(updates):
    with pytest.raises(ValueError):
        client.validate_intake_update(updates)


def test_update_notes_must_be_string():
    with pytest.raises(ValueError):
        client.validate_intake_update({"notes": 123})


# ---------------------------------------------------------------------------
# 3. Secret hygiene
# ---------------------------------------------------------------------------

def _mock_transport(handler):
    return httpx.MockTransport(handler)


def test_secret_sent_only_as_header(monkeypatch):
    monkeypatch.setenv(client.SECRET_ENV_VAR, "super-secret-value")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        return httpx.Response(200, json={"intakes": []})

    def fake_client():
        return httpx.AsyncClient(transport=_mock_transport(handler))

    monkeypatch.setattr(client, "_client", fake_client)
    asyncio.run(client.fetch_intakes("+12816628581"))
    assert seen["headers"].get(client.SECRET_HEADER) == "super-secret-value"
    assert "super-secret-value" not in seen["url"]


def test_secret_never_in_errors(monkeypatch):
    monkeypatch.setenv(client.SECRET_ENV_VAR, "super-secret-value")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    def fake_client():
        return httpx.AsyncClient(transport=_mock_transport(handler))

    monkeypatch.setattr(client, "_client", fake_client)
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(client.fetch_intakes("+12816628581"))
    assert "super-secret-value" not in str(excinfo.value)


def test_missing_secret_fails_closed_before_http(monkeypatch):
    monkeypatch.delenv(client.SECRET_ENV_VAR, raising=False)
    called = []

    def fake_client():
        called.append(True)
        raise AssertionError("no HTTP should happen without a secret")

    monkeypatch.setattr(client, "_client", fake_client)
    with pytest.raises(RuntimeError):
        asyncio.run(client.fetch_intakes("+12816628581"))
    assert called == []


def test_allowlist_rejects_other_paths():
    with pytest.raises(ValueError):
        client._assert_allowed_path("/api/admin/users")
    with pytest.raises(ValueError):
        client._assert_allowed_path("/api/sofia/intaksextra")
    # These are fine:
    client._assert_allowed_path("/api/sofia/intakes")
    client._assert_allowed_path("/api/sofia/intakes/abc123")


def test_e164_validation():
    with pytest.raises(ValueError):
        asyncio.run(client.fetch_intakes("not-a-phone"))


# ---------------------------------------------------------------------------
# 4. Intent detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "¿cómo va mi solicitud?",
    "¿Cuál es el estado de mi trámite?",
    "quiero seguimiento de mi caso",
    "dónde va mi solicitud",
])
def test_intake_inquiry_detected(text):
    assert client.looks_like_intake_inquiry(text)


@pytest.mark.parametrize("text", [
    "quiero enviar dinero a Cuba",
    "¿cuánto cuesta el piloto?",
    "hola",
    "busco proveedores",
])
def test_intake_inquiry_not_detected(text):
    assert not client.looks_like_intake_inquiry(text)


@pytest.mark.parametrize("text,expected", [
    ("por favor cancela mi solicitud", ("intake_status", "CANCELLED")),
    ("quiero cancelar mi trámite", ("intake_status", "CANCELLED")),
    ("pon mi caso en espera", ("intake_status", "ON_HOLD")),
    ("reanuda mi solicitud por favor", ("intake_status", "COLLECTING")),
    ("agrega una nota: el cliente enviará la licencia mañana",
     ("notes", "el cliente enviará la licencia mañana")),
])
def test_update_intent_detected(text, expected):
    assert client.detect_update_intent(text) == expected


@pytest.mark.parametrize("text", [
    "hola",
    "¿cuánto cuesta enviar dinero?",
    "quiero enviar dinero a Cuba",
    "agrega una nota",  # no note content -> ask, don't invent
])
def test_update_intent_not_detected(text):
    assert client.detect_update_intent(text) is None


def test_format_intake_summary_grounded():
    summary = client.format_intake_summary([
        {"id": "abc", "intake_status": "COLLECTING", "updated_at": "2026-09-16T10:00:00Z",
         "notes": "licencia en trámite", "payment_status": "SHOULD_BE_SCRUBBED"},
    ])
    assert "abc" in summary and "COLLECTING" in summary
    assert "SHOULD_BE_SCRUBBED" not in summary


# ---------------------------------------------------------------------------
# 5. Prompt blocks
# ---------------------------------------------------------------------------

def test_my_cuba_cash_block_content():
    assert "Sofia · MY CUBA CASH" in MY_CUBA_CASH_SYSTEM_BLOCK
    assert ZERO_CUSTODY_LINE in MY_CUBA_CASH_SYSTEM_BLOCK
    assert "1.25%" in MY_CUBA_CASH_SYSTEM_BLOCK
    assert "1.75%" in MY_CUBA_CASH_SYSTEM_BLOCK
    assert "2.50%" in MY_CUBA_CASH_SYSTEM_BLOCK
    assert "$25" in MY_CUBA_CASH_SYSTEM_BLOCK
    assert "NEVER" in MY_CUBA_CASH_SYSTEM_BLOCK
    # Topic boundary: trade topics named only in the boundary clause
    for term in ("suppliers", "freight", "partner"):
        assert term in MY_CUBA_CASH_SYSTEM_BLOCK


def test_import_export_guard_content():
    assert "remesas" in IMPORT_EXPORT_TRACK_GUARD or "remittance" in IMPORT_EXPORT_TRACK_GUARD.lower()
    assert "MY CUBA CASH" in IMPORT_EXPORT_TRACK_GUARD
    assert "divisas" in IMPORT_EXPORT_TRACK_GUARD


# ---------------------------------------------------------------------------
# 6. Runtime wiring helper
# ---------------------------------------------------------------------------

def _import_runtime():
    import sofia_whatsapp_runtime as runtime
    return runtime


def test_track_resolution_ask_short_circuits_first_message(monkeypatch):
    runtime = _import_runtime()

    async def go():
        return await runtime._resolve_business_track(
            "tengo una MIPYME",
            sender_phone="12816628581",
            lead_id="lead_x",
            transcript="",
            owner_context=False,
        )

    result = asyncio.run(go())
    assert result["action"] == "short_circuit"
    assert "MIPYME" in result["reply"]
    assert result["audit"]["business_track"] == TRACK_ASK


def test_track_resolution_ask_with_history_continues(monkeypatch):
    runtime = _import_runtime()

    async def go():
        return await runtime._resolve_business_track(
            "tengo una MIPYME",
            sender_phone="12816628581",
            lead_id="lead_x",
            transcript="customer: hola\nsofia: ¡Hola! ¿En qué te ayudo?",
            owner_context=False,
        )

    result = asyncio.run(go())
    assert result["action"] == "continue"
    assert "EXACTLY ONE clarifying question" in result["prompt_addition"]


def test_track_resolution_my_cuba_cash_with_intake_context(monkeypatch):
    runtime = _import_runtime()

    async def fake_fetch(phone):
        assert phone == "+12816628581"
        return [{"id": "int_1", "intake_status": "COLLECTING",
                 "updated_at": "2026-09-16T10:00:00Z", "notes": "ok"}]

    monkeypatch.setattr(runtime, "fetch_intakes", fake_fetch)

    async def go():
        return await runtime._resolve_business_track(
            "¿cómo va mi solicitud?",
            sender_phone="12816628581",
            lead_id="lead_x",
            transcript="customer: quiero enviar dinero a mi familia en Cuba",
            owner_context=False,
        )

    result = asyncio.run(go())
    assert result["action"] == "continue"
    assert "Sofia · MY CUBA CASH" in result["prompt_addition"]
    assert "int_1" in result["prompt_addition"]
    assert "COLLECTING" in result["prompt_addition"]
    assert result["audit"]["business_track"] == TRACK_MY_CUBA_CASH


def test_track_resolution_update_with_readback(monkeypatch):
    runtime = _import_runtime()
    seen = {}

    async def fake_fetch(phone):
        return [{"id": "int_9", "intake_status": "COLLECTING"}]

    async def fake_apply(intake_id, updates, sender_phone_e164):
        seen["args"] = (intake_id, updates, sender_phone_e164)
        assert set(updates) <= {"notes", "intake_status"}
        return {"ok": True, "record": {"id": intake_id, "intake_status": "CANCELLED"}}

    monkeypatch.setattr(runtime, "fetch_intakes", fake_fetch)
    monkeypatch.setattr(runtime, "apply_intake_update", fake_apply)

    async def go():
        return await runtime._resolve_business_track(
            "por favor cancela mi solicitud",
            sender_phone="12816628581",
            lead_id="lead_x",
            transcript="customer: quiero enviar dinero a mi familia en Cuba",
            owner_context=False,
        )

    result = asyncio.run(go())
    assert result["action"] == "continue"
    assert seen["args"][0] == "int_9"
    assert seen["args"][1] == {"intake_status": "CANCELLED"}
    assert "VERIFIED INTAKE UPDATE" in result["prompt_addition"]
    assert result["audit"]["cubacash_update"] == "ok"


def test_track_resolution_multiple_intakes_asks_which(monkeypatch):
    runtime = _import_runtime()

    async def fake_fetch(phone):
        return [{"id": "a", "intake_status": "COLLECTING"},
                {"id": "b", "intake_status": "ON_HOLD"}]

    monkeypatch.setattr(runtime, "fetch_intakes", fake_fetch)

    async def go():
        return await runtime._resolve_business_track(
            "cancela mi solicitud",
            sender_phone="12816628581",
            lead_id="lead_x",
            transcript="customer: quiero enviar dinero a mi familia en Cuba",
            owner_context=False,
        )

    result = asyncio.run(go())
    assert result["action"] == "short_circuit"
    assert "varias solicitudes" in result["reply"]


def test_track_resolution_owner_context_unchanged():
    runtime = _import_runtime()

    async def go():
        return await runtime._resolve_business_track(
            "quiero enviar dinero a Cuba",
            sender_phone="12816628581",
            lead_id="lead_x",
            transcript="",
            owner_context=True,
        )

    result = asyncio.run(go())
    assert result["action"] == "continue"
    assert result["prompt_addition"] == ""
    assert result["audit"]["business_track"] == "owner_context"


def test_track_resolution_import_export_gets_guard():
    runtime = _import_runtime()

    async def go():
        return await runtime._resolve_business_track(
            "necesito cotizar un contenedor",
            sender_phone="12816628581",
            lead_id="lead_x",
            transcript="customer: hola",
            owner_context=False,
        )

    result = asyncio.run(go())
    assert result["action"] == "continue"
    assert "SAHJONY Global Trade" in result["prompt_addition"]
    assert result["audit"]["business_track"] == TRACK_IMPORT_EXPORT


def test_track_switch_mid_conversation_message_wins():
    # Established MY CUBA CASH conversation, user switches to trade topics:
    # the current message's own classification wins.
    runtime = _import_runtime()

    async def go():
        return await runtime._resolve_business_track(
            "ahora quiero importar ropa de Panamá",
            sender_phone="12816628581",
            lead_id="lead_x",
            transcript="customer: quiero enviar dinero a mi familia en Cuba",
            owner_context=False,
        )

    result = asyncio.run(go())
    assert result["action"] == "continue"
    assert result["audit"]["business_track"] == TRACK_IMPORT_EXPORT
    assert result["audit"]["classification_source"] == "message"


def test_track_inherited_from_history_marked_in_audit(monkeypatch):
    runtime = _import_runtime()

    async def fake_fetch(phone):
        return []

    monkeypatch.setattr(runtime, "fetch_intakes", fake_fetch)

    async def go():
        return await runtime._resolve_business_track(
            "¿cómo va mi solicitud?",
            sender_phone="12816628581",
            lead_id="lead_x",
            transcript="customer: quiero enviar dinero a mi familia en Cuba",
            owner_context=False,
        )

    result = asyncio.run(go())
    assert result["audit"]["business_track"] == TRACK_MY_CUBA_CASH
    assert result["audit"]["classification_source"] == "history"
