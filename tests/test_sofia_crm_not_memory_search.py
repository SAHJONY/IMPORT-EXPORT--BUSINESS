import inspect
import whatsapp_api as wa
import sofia_whatsapp_runtime as rt


def test_inbound_routes_through_governed_hermes_entrypoint():
    source = inspect.getsource(wa._process_inbound)
    assert "await _generate_ai_reply(text, contact_name)" in source
    assert "await generate_sofia_reply(text, contact_name)" not in source


def test_customer_prompt_forbids_openclaw_memory_as_crm_dependency():
    source = inspect.getsource(rt.generate_sofia_reply)
    assert "CRM is an application data source, not OpenClaw file memory" in source
    assert "openclaw memory index" in source
