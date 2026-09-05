import asyncio
import whatsapp_api as wa


def test_generate_ai_reply_routes_through_hermes(monkeypatch):
    calls = {}
    async def fake_hermes(text, contact_name):
        calls['args'] = (text, contact_name)
        return 'Hermes governed reply'
    monkeypatch.setattr(wa, 'generate_hermes_whatsapp_reply', fake_hermes)
    result = asyncio.run(wa._generate_ai_reply('Necesito aceite', 'Cliente'))
    assert result == 'Hermes governed reply'
    assert calls['args'] == ('Necesito aceite', 'Cliente')


def test_generate_ai_reply_fails_closed_if_hermes_errors(monkeypatch):
    async def fake_hermes(text, contact_name):
        raise RuntimeError('offline')
    monkeypatch.setattr(wa, 'generate_hermes_whatsapp_reply', fake_hermes)
    assert asyncio.run(wa._generate_ai_reply('hola', 'Cliente')) == ''
