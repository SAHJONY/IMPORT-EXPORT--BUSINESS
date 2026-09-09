from insforge_backend import _record_key


def test_command_id_precedes_account_id():
    row = {"command_id": "waq_123", "account_id": "default"}
    assert _record_key(row) == "command_id:waq_123"


def test_notification_id_precedes_account_id():
    row = {"notification_id": "ntf_123", "account_id": "default"}
    assert _record_key(row) == "notification_id:ntf_123"
