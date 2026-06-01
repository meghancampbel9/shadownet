from __future__ import annotations

from shadownet.mcp.tools import (
    ContactsOutput,
    IdentityOutput,
    InboxOutput,
)


def test_identity_tool_shape(app_ready, clean_db):
    from app.mcp_server import identity

    out = IdentityOutput.model_validate(identity())
    assert out.pk.startswith("z6Mk")
    assert out.shadowname


def test_contacts_empty(app_ready, clean_db):
    from app.mcp_server import contacts

    out = ContactsOutput.model_validate(contacts())
    assert out.contacts == ()


def test_inbox_empty(app_ready, clean_db):
    from app.mcp_server import inbox

    out = InboxOutput.model_validate(inbox())
    assert out.items == ()


def test_grant_unknown_contact(app_ready, clean_db):
    from app.mcp_server import grant

    assert grant(name="nobody@x.test", grant="messaging", allowed=True) == {"error": "not_contact"}


def test_grant_unknown_grant(app_ready, clean_db):
    from app.mcp_server import grant

    assert grant(name="nobody@x.test", grant="telepathy", allowed=True) == {
        "error": "unknown_grant"
    }


def test_tool_names_registered(app_ready):
    import asyncio

    from app.mcp_server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    expected = {
        "identity",
        "resolve",
        "contacts",
        "contact_detail",
        "add_contact",
        "grant",
        "set_contact_profile",
        "send",
        "respond",
        "inbox",
        "inbox_wait",
    }
    assert expected <= names
    assert not any(n.startswith("social_") for n in names)
