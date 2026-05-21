"""Tests for the generic A2A communication layer.

Covers: grant enforcement, contact identification, inbound message handling,
and the simplified data model.
"""

from __future__ import annotations

import json

import pytest
from sqlmodel import Session

from app.grants import GrantDenied, enforce_grant, find_contact_by_did
from app.models import AccessGrant, Contact, GrantType, InteractionContext

# ── Grant Enforcement ───────────────────────────────────────────────────────


class TestGrants:
    def test_grant_allowed(self, db_session: Session, contact: Contact):
        grant = AccessGrant(
            contact_id=contact.id,
            grant_type=GrantType.messaging,
            allowed=True,
        )
        db_session.add(grant)
        db_session.commit()
        enforce_grant(db_session, contact)

    def test_grant_denied_no_grant(self, db_session: Session, contact: Contact):
        with pytest.raises(GrantDenied):
            enforce_grant(db_session, contact)

    def test_grant_denied_explicitly_disabled(self, db_session: Session, contact: Contact):
        grant = AccessGrant(
            contact_id=contact.id,
            grant_type=GrantType.messaging,
            allowed=False,
        )
        db_session.add(grant)
        db_session.commit()
        with pytest.raises(GrantDenied):
            enforce_grant(db_session, contact)

    def test_find_contact_by_did(self, db_session: Session, contact: Contact):
        found = find_contact_by_did(db_session, "did:key:z6MkTestAlice")
        assert found is not None
        assert found.id == contact.id

    def test_find_contact_by_did_unknown(self, db_session: Session):
        found = find_contact_by_did(db_session, "did:key:z6MkUnknown")
        assert found is None

    def test_find_contact_by_did_full(self, db_session: Session, contact: Contact):
        found = find_contact_by_did(db_session, "did:key:z6MkTestAlice")
        assert found is not None
        assert found.name == "Alice"


# ── Data Model ──────────────────────────────────────────────────────────────


class TestDataModel:
    def test_contact_metadata(self, db_session: Session):
        c = Contact(
            name="Bob",
            agent_endpoint="http://bob:8340",
            metadata_json=json.dumps({"relationship": "colleague", "shared_interests": ["AI"]}),
        )
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)
        meta = json.loads(c.metadata_json)
        assert meta["relationship"] == "colleague"
        assert "AI" in meta["shared_interests"]

    def test_contact_did_fields(self, db_session: Session):
        c = Contact(
            name="Carol",
            agent_endpoint="http://carol:8340",
            did="did:key:z6MkCarol",
            shadowname="carol",
            public_key_jwk=json.dumps({"kty": "OKP", "crv": "Ed25519"}),
        )
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)
        assert c.did == "did:key:z6MkCarol"
        assert c.shadowname == "carol"
        jwk = json.loads(c.public_key_jwk)
        assert jwk["kty"] == "OKP"

    def test_interaction_context_stores_data(self, db_session: Session, contact: Contact):
        ictx = InteractionContext(
            data_type="custom_request",
            contact_id=contact.id,
            direction="inbound",
            status="received",
            context_data=json.dumps({"key": "value"}),
        )
        db_session.add(ictx)
        db_session.commit()
        db_session.refresh(ictx)
        assert ictx.data_type == "custom_request"
        assert ictx.direction == "inbound"
        data = json.loads(ictx.context_data)
        assert data["key"] == "value"

    def test_interaction_intent_id(self, db_session: Session, contact: Contact):
        ictx = InteractionContext(
            data_type="message",
            contact_id=contact.id,
            direction="inbound",
            status="received",
            intent_id="urn:uuid:abc-123",
            context_data=json.dumps({"text": "hi"}),
        )
        db_session.add(ictx)
        db_session.commit()
        db_session.refresh(ictx)
        assert ictx.intent_id == "urn:uuid:abc-123"

    def test_interaction_outbound(self, db_session: Session, contact: Contact):
        ictx = InteractionContext(
            data_type="message",
            contact_id=contact.id,
            direction="outbound",
            status="sent",
            context_data=json.dumps({"text": "hello"}),
        )
        db_session.add(ictx)
        db_session.commit()
        db_session.refresh(ictx)
        assert ictx.direction == "outbound"
        assert ictx.status == "sent"


# ── A2A Protocol Helpers ────────────────────────────────────────────────────


class TestA2AHelpers:
    def test_build_envelope(self):
        from app.executor import build_envelope

        env = build_envelope({"type": "test_type", "key": "val"})
        assert "message" in env
        assert env["message"]["role"] == "ROLE_AGENT"
        parts = env["message"]["parts"]
        assert len(parts) == 1
        assert parts[0]["type"] == "shadownet/v1+envelope"
        payload = parts[0]["data"]["payload"]
        assert payload["type"] == "test_type"
        assert payload["key"] == "val"
        assert "interaction" not in parts[0]["data"]

    def test_build_envelope_with_intent(self):
        from app.executor import build_envelope

        env = build_envelope({"type": "test"}, intent_id="my-intent-id")
        data = env["message"]["parts"][0]["data"]
        assert data["intentId"] == "urn:uuid:my-intent-id"
        assert "interaction" not in data

    def test_build_envelope_with_interaction(self):
        from app.executor import build_envelope

        env = build_envelope({"type": "test"}, interaction="urn:shadownet:interaction:abc")
        data = env["message"]["parts"][0]["data"]
        assert data["interaction"] == "urn:shadownet:interaction:abc"

    def test_extract_data_part_envelope(self):
        from app.executor import ENVELOPE_PART_TYPE, extract_data_part

        body = {
            "message": {
                "parts": [
                    {
                        "type": ENVELOPE_PART_TYPE,
                        "mediaType": "application/json",
                        "data": {
                            "shadownet:v": "0.1",
                            "intentId": "urn:uuid:123",
                            "payload": {"type": "foo", "bar": 1},
                        },
                    }
                ]
            }
        }
        dtype, data, iid = extract_data_part(body)
        assert dtype == "foo"
        assert data["bar"] == 1
        assert iid == "urn:uuid:123"

    def test_extract_data_part_legacy(self):
        from app.executor import extract_data_part

        body = {
            "message": {
                "parts": [{"data": {"type": "foo", "bar": 1}, "mediaType": "application/json"}]
            }
        }
        dtype, data, iid = extract_data_part(body)
        assert dtype == "foo"
        assert data["bar"] == 1
        assert iid == ""

    def test_extract_text_part(self):
        from app.executor import extract_data_part

        body = {"message": {"parts": [{"text": "hello"}]}}
        dtype, data, iid = extract_data_part(body)
        assert dtype == "message"
        assert data["text"] == "hello"
        assert iid == ""

    def test_message_response(self):
        from app.executor import data_part, message_response

        resp = message_response(data_part("ack", {"received": True}))
        assert "message" in resp
        assert resp["message"]["role"] == "ROLE_AGENT"
        parts = resp["message"]["parts"]
        assert parts[0]["data"]["type"] == "ack"

    def test_task_response(self):
        from app.executor import task_response

        resp = task_response("task-1", "TASK_STATE_COMPLETED")
        assert resp["task"]["id"] == "task-1"
        assert resp["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
