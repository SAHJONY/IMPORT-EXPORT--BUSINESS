import asyncio
import pytest
from fastapi import HTTPException
import google_contacts_api as api


PERSON={"resourceName":"people/c123","etag":"e1","names":[{"displayName":"Ana Pérez","givenName":"Ana","familyName":"Pérez","metadata":{"primary":True}}],"emailAddresses":[{"value":"ana.personal@example.com","type":"home","metadata":{"primary":True}},{"value":"ana@company.example","type":"work"}],"phoneNumbers":[{"value":"+1 305 555 0100","type":"mobile","metadata":{"primary":True}}],"organizations":[{"name":"Example Trading","title":"Buyer"}]}


def test_google_contact_keeps_emails_private_and_out_of_crm():
    row=api._contact(PERSON)
    assert [x["value"] for x in row["emails"]]==["ana.personal@example.com","ana@company.example"]
    assert row["owner_private"] is True
    assert row["public_visibility"] is False
    assert row["crm_member"] is False
    assert row["suggested_context"]=="business"


def test_sofia_secret_can_read_but_not_promote(monkeypatch):
    monkeypatch.setenv("SOFIA_OWNER_CONTACTS_SECRET","s"*40)
    assert api._auth(None,"s"*40)=="sofia"
    with pytest.raises(HTTPException) as blocked:
        api._auth(None,"s"*40,owner_only=True)
    assert blocked.value.status_code==403


def test_personal_contact_cannot_be_promoted(monkeypatch):
    monkeypatch.setattr(api,"_auth",lambda *_args,**_kwargs:"owner")
    with pytest.raises(HTTPException) as blocked:
        asyncio.run(api.promote("c123",api.Promote(context="personal"),authorization="Bearer owner"))
    assert blocked.value.status_code==409


def test_google_contacts_health_does_not_expose_secrets(monkeypatch):
    monkeypatch.setattr(api,"_auth",lambda *_args,**_kwargs:"owner")
    monkeypatch.setattr(api,"_config",lambda:("client","secret","refresh"))
    result=api.health(authorization="Bearer owner")
    assert result["emails_included"] is True
    assert result["automatic_crm_import"] is False
    assert "refresh" not in str(result).lower()
