"""Group-send addressing guards for the Hermes direct-send path.

Covers the pure helpers in whatsapp_api.py (_is_valid_group_jid,
_resolve_group_target, _load_groups_registry) by extracting and executing them
in isolation (no FastAPI/Supabase imports needed), plus source-inspection
guards for the enqueue branch, the groups endpoint wiring, the workflow, and
the registry file. The 1:1 digit path must stay byte-for-byte intact.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _helpers(tmp_path, registry):
    source = (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")
    reg_file = tmp_path / "whatsapp_groups.json"
    reg_file.write_text(json.dumps(registry), encoding="utf-8")

    def _slice(name):
        start = source.index(f"def {name}(")
        end = len(source)
        for marker in ("\ndef ", "\nclass ", "\n@app."):
            idx = source.find(marker, start + 10)
            if idx != -1:
                end = min(end, idx)
        return source[start:end]

    preamble = (
        "from __future__ import annotations\n"
        "import json, os\n"
        "from typing import Any\n"
        "class HTTPException(Exception):\n"
        "    def __init__(self, status_code=400, detail=''):\n"
        "        super().__init__(detail)\n"
        "        self.status_code = status_code\n"
        "        self.detail = detail\n"
        f"_GROUPS_REGISTRY_PATH = {str(reg_file)!r}\n"
        "_groups_registry_cache = None\n"
    )
    ns: dict = {}
    exec(
        preamble
        + _slice("_load_groups_registry")
        + _slice("_is_valid_group_jid")
        + _slice("_resolve_group_target"),
        ns,
    )
    return ns


@pytest.fixture()
def helpers(tmp_path):
    registry = {
        "version": 1,
        "groups": [
            {"alias": "rosmel-ventas-cuba", "jid": "120363041234567@g.us", "name": "Rosmel group"},
            {"alias": "pending-jid", "jid": None, "name": "No JID yet"},
        ],
    }
    return _helpers(tmp_path, registry)


def test_group_jid_validation(helpers):
    valid = helpers["_is_valid_group_jid"]
    assert valid("120363041234567@g.us")
    assert not valid("123@g.us")  # too short
    assert not valid("abc@g.us")  # non-digits
    assert not valid("120363041234567@c.us")  # wrong domain
    assert not valid("120363041234567")  # missing domain
    assert not valid("")


def test_resolve_raw_group_jid(helpers):
    jid, alias = helpers["_resolve_group_target"]("group:120363041234567@g.us")
    assert jid == "120363041234567@g.us"
    assert alias is None


def test_resolve_group_alias(helpers):
    jid, alias = helpers["_resolve_group_target"]("group:alias:rosmel-ventas-cuba")
    assert jid == "120363041234567@g.us"
    assert alias == "rosmel-ventas-cuba"


def test_resolve_group_alias_case_insensitive(helpers):
    jid, _ = helpers["_resolve_group_target"]("group:alias:Rosmel-Ventas-Cuba")
    assert jid == "120363041234567@g.us"


def test_resolve_unknown_alias_fails_closed(helpers):
    with pytest.raises(Exception) as exc:
        helpers["_resolve_group_target"]("group:alias:nope")
    assert exc.value.status_code == 400


def test_resolve_alias_without_jid_fails_closed(helpers):
    with pytest.raises(Exception) as exc:
        helpers["_resolve_group_target"]("group:alias:pending-jid")
    assert exc.value.status_code == 400


def test_resolve_malformed_group_jid_fails_closed(helpers):
    for bad in ("group:notajid", "group:123@c.us", "group:alias:"):
        with pytest.raises(Exception) as exc:
            helpers["_resolve_group_target"](bad)
        assert exc.value.status_code == 400


def test_non_group_recipient_untouched(helpers):
    assert helpers["_resolve_group_target"]("5352985393") == (None, None)
    assert helpers["_resolve_group_target"]("+53 5 2985393") == (None, None)


def test_enqueue_branches_group_vs_individual():
    source = (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")
    # Group rows are namespaced so the worker can never confuse them with phones.
    assert 'recipient = f"group:{group_jid}"' in source
    assert '"recipient_type": recipient_type' in source or "'recipient_type': recipient_type" in source or '"recipient_type":' in source
    # The 1:1 digit path is preserved exactly.
    assert 'if not 8 <= len(digits) <= 15:' in source
    assert "recipient = digits" in source
    assert '"recipient": recipient,' in source
    # Recipient field is wide enough for group tokens.
    assert "max_length=64" in source


def test_groups_endpoint_wired():
    api = (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")
    assert 'def hermes_groups_list' in api
    assert '"/whatsapp/hermes/groups"' in api
    primary = (ROOT / "whatsapp_cloud_primary_api.py").read_text(encoding="utf-8")
    assert "hermes_groups_list," in primary
    assert 'app.add_api_route("/whatsapp/hermes/groups", hermes_groups_list, methods=["GET"])' in primary


def test_workflow_accepts_group_addressing():
    wf = (ROOT / ".github/workflows/hostinger-hermes-whatsapp-send.yml").read_text(encoding="utf-8")
    assert "group:alias:" in wf
    assert "@g.us" in wf
    assert "INVALID_GROUP_JID" in wf
    assert "RECIPIENT_TYPE" in wf
    # Group-specific ban notice: groups are visible to every member.
    assert "visible to EVERY group member" in wf
    # Existing governance intact.
    assert "default: 'true'" in wf
    assert "cancel-in-progress: false" in wf
    assert "spam detection" in wf
    assert "DIRECT_SEND_CONFIRMED" in wf


def test_registry_file_is_valid():
    registry = json.loads((ROOT / "whatsapp_groups.json").read_text(encoding="utf-8"))
    assert registry["version"] == 1
    assert isinstance(registry["groups"], list)
    required = {"alias", "jid", "name", "purpose", "agent", "region", "admin_status"}
    for entry in registry["groups"]:
        assert required <= set(entry), f"entry missing fields: {entry.get('alias')}"
        assert entry["admin_status"] in {"admin", "member", "unknown"}
        if entry["jid"] is not None:
            local, _, domain = str(entry["jid"]).rpartition("@")
            assert domain == "g.us" and local.isdigit()


def _group_helpers():
    source = (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")
    start = source.index("def _bridge_group_jid(")
    end = source.index("def _bridge_sender_phone(")
    ns: dict = {}
    exec("from __future__ import annotations\n" + source[start:end], ns)
    return ns


def test_bridge_group_jid_extraction():
    fn = _group_helpers()["_bridge_group_jid"]
    assert fn({"chatId": "120363041234567@g.us", "senderId": "5351234567@c.us"}) == "120363041234567@g.us"
    assert fn({"chatId": "5351234567@c.us"}) == ""
    assert fn({"senderId": "120363041234567@g.us"}) == "120363041234567@g.us"
    assert fn({}) == ""


def test_group_inbound_is_record_only():
    source = (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")
    handler = source[source.index("async def _handle_bridge_message("):source.index("async def _sofia_bridge_poller(")]
    # Group branch records the message and returns BEFORE any reply logic.
    assert "group_jid = _bridge_group_jid(msg)" in handler
    assert "if group_jid:" in handler
    group_branch = handler[handler.index("if group_jid:"):handler.index("phone = _bridge_sender_phone(msg)")]
    assert "_register_inbound_message(" in group_branch
    assert "generate_sofia_reply" not in group_branch
    assert "_enqueue_hermes_message" not in group_branch


def test_groups_activity_endpoint_wired():
    api = (ROOT / "whatsapp_api.py").read_text(encoding="utf-8")
    assert "def hermes_groups_activity" in api
    assert '"/whatsapp/hermes/groups/activity"' in api
    assert "@g.us" in api[api.index("def hermes_groups_activity"):api.index("def hermes_groups_activity") + 2500]
    primary = (ROOT / "whatsapp_cloud_primary_api.py").read_text(encoding="utf-8")
    assert "hermes_groups_activity," in primary
    assert 'app.add_api_route("/whatsapp/hermes/groups/activity", hermes_groups_activity, methods=["GET"])' in primary


def test_templates_file_is_valid():
    templates = json.loads((ROOT / "whatsapp_group_templates.json").read_text(encoding="utf-8"))
    assert templates["version"] == 1
    assert isinstance(templates["templates"], list)
    for tpl in templates["templates"]:
        assert {"id", "text", "use", "allowed_fill"} <= set(tpl)
        assert 1 <= len(tpl["text"]) <= 1000
