import asyncio
import inspect
import whatsapp_api as wa


def test_generate_ai_reply_is_hard_routed_through_hermes():
    source = inspect.getsource(wa._generate_ai_reply)
    assert 'generate_hermes_whatsapp_reply' in source
    assert 'api.openai.com' not in source
    assert 'OPENAI_API_KEY' not in source


def test_generate_ai_reply_fails_closed_if_hermes_errors(monkeypatch):
    async def fake_hermes(text, contact_name):
        raise RuntimeError('offline')
    monkeypatch.setitem(wa._generate_ai_reply.__globals__, 'generate_hermes_whatsapp_reply', fake_hermes)
    assert asyncio.run(wa._generate_ai_reply('hola', 'Cliente')) == ''


def test_health_contract_declares_hermes_cognition_and_openclaw_transport():
    source = inspect.getsource(__import__('whatsapp_cloud_primary_api').whatsapp_health_hostinger_authority)
    assert 'hostinger_openclaw' in source
    assert 'hermes' in source.lower()
