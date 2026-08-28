import pytest
from fastapi import HTTPException

import owner_auth_api


def test_audit_ledgers_are_immutable_for_retention_policy():
    assert owner_auth_api.AUDIT_RETENTION_DAYS >= 365
    for table in owner_auth_api.IMMUTABLE_TABLES:
        with pytest.raises(HTTPException) as exc:
            owner_auth_api._validate_table(table, include_system=True)
        assert exc.value.status_code == 403
