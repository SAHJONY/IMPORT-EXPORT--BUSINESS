import asyncio

import sofia_hermes_whatsapp_environment as hermes


def _snapshot(count=11753):
    return {
        "verified": True,
        "status": "ok",
        "record_count": count,
        "target": 15600,
        "remaining_shortfall": 15600 - count,
        "source_scope": "public_registry_and_official_actor_lists_research",
        "ownership_policy": "evidence_only",
        "binding_actions": False,
    }


def test_cuba_crm_question_is_answered_from_verified_snapshot(monkeypatch):
    async def fake_snapshot():
        return _snapshot()
    async def should_not_generate(*_args, **_kwargs):
        raise AssertionError("general model path should not run for a direct Cuba CRM inventory question")

    monkeypatch.setattr(hermes, "_cuba_crm_snapshot", fake_snapshot)
    monkeypatch.setattr(hermes, "generate_sofia_reply", should_not_generate)
    monkeypatch.setattr(hermes, "environment_enabled", lambda: True)
    monkeypatch.setattr(hermes, "nim_configured", lambda: True)

    reply = asyncio.run(hermes.generate_hermes_whatsapp_reply(
        "¿Cuántos leads tenemos del sector privado cubano en el CRM?", "Juan"
    ))
    assert "11,753 registros" in reply
    assert "no hay leads" not in reply.lower()


def test_false_empty_cuba_claim_is_blocked_after_generation(monkeypatch):
    async def fake_snapshot():
        return _snapshot()
    async def bad_generator(*_args, **_kwargs):
        return "En este momento no hay leads ni oportunidades registradas para el sector privado cubano en nuestro CRM."
    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(hermes, "_cuba_crm_snapshot", fake_snapshot)
    monkeypatch.setattr(hermes, "generate_sofia_reply", bad_generator)
    monkeypatch.setattr(hermes, "_audit", fake_audit)
    monkeypatch.setattr(hermes, "environment_enabled", lambda: True)
    monkeypatch.setattr(hermes, "nim_configured", lambda: True)

    reply = asyncio.run(hermes.generate_hermes_whatsapp_reply(
        "Activa negocios con el sector privado de Cuba", "Juan"
    ))
    assert "11,753 registros" in reply
    assert "no hay leads" not in reply.lower()
