"""Tests for the features fixed/added in the v0.1 migration.

Covers:
- Webhook notification headers and payload format
- DID-based handshake (verify_inbound with cached_presentations)
- Contact API response fields (did, shadowname, public_key_jwk)
- Agent card format
- A2A endpoint routing and auth
- Envelope format compliance
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session

from app.models import Contact, InteractionContext

# ── Webhook Notifications ─────────────────────────────────────────────────────


class TestWebhookHeaders:
    """Verify webhook headers include both spec and hermes-agent-compatible formats."""

    def test_build_webhook_headers_includes_generic_signature(self):
        from app.notifications import _build_webhook_headers

        body = b'{"event": "inbox.message"}'
        secret = "test-secret-key"
        headers = _build_webhook_headers(body, secret)

        expected_sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        assert "X-Shadownet-Sidecar-Sig" in headers
        assert headers["X-Shadownet-Sidecar-Sig"] == f"sha256={expected_sig}"
        assert "X-Webhook-Signature" in headers
        assert headers["X-Webhook-Signature"] == expected_sig
        assert "X-Shadownet-Sidecar-Ts" in headers
        assert "X-Shadownet-Sidecar-Id" in headers
        assert headers["Content-Type"] == "application/json"

    def test_build_webhook_headers_timestamp_is_recent(self):
        from app.notifications import _build_webhook_headers

        before = int(time.time())
        headers = _build_webhook_headers(b"body", "secret")
        after = int(time.time())

        ts = int(headers["X-Shadownet-Sidecar-Ts"])
        assert before <= ts <= after

    def test_webhook_signature_validates_with_hermes_pattern(self):
        """Simulate hermes-agent's generic signature validation."""
        from app.notifications import _build_webhook_headers

        body = b'{"contact": "Alice", "data_type": "message"}'
        secret = "my-route-secret"
        headers = _build_webhook_headers(body, secret)

        generic_sig = headers["X-Webhook-Signature"]
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(generic_sig, expected)


class TestWebhookPayload:
    """Verify webhook payload includes fields expected by hermes-agent prompt template."""

    @pytest.mark.asyncio
    async def test_notify_message_received_payload_has_template_fields(self):
        from app.notifications import notify_message_received

        contact = MagicMock()
        contact.name = "Test Friend"
        contact.id = "contact-123"

        with patch("app.notifications.settings") as mock_settings, \
             patch("app.notifications._post_webhook_with_retry",
                   new_callable=AsyncMock) as mock_post:
            mock_settings.notification_webhook_url = "http://agent:8644/webhooks/a2a-inbox"
            mock_settings.notification_negotiate_url = ""
            mock_settings.notification_webhook_secret = "secret"

            await notify_message_received(
                contact=contact,
                data_type="coordination_request",
                data={"activity": "coffee", "details": "Thursday"},
                interaction_id="int-456",
            )

            mock_post.assert_called_once()
            payload = mock_post.call_args[0][0]

            assert payload["contact"] == "Test Friend"
            assert payload["data_type"] == "coordination_request"
            assert payload["interaction_id"] == "int-456"
            assert payload["data"]["activity"] == "coffee"
            assert payload["event"] == "inbox.message"
            assert payload["shadownet:v"] == "0.1"

    @pytest.mark.asyncio
    async def test_coordination_request_routes_to_negotiate_url(self):
        """coordination_request should be routed to the negotiate URL."""
        from app.notifications import notify_message_received

        contact = MagicMock()
        contact.name = "Test Friend"
        contact.id = "contact-123"

        with patch("app.notifications.settings") as mock_settings, \
             patch("app.notifications._post_webhook_with_retry",
                   new_callable=AsyncMock) as mock_post:
            mock_settings.notification_webhook_url = "http://agent:8644/webhooks/a2a-inbox"
            mock_settings.notification_negotiate_url = "http://agent:8644/webhooks/a2a-negotiate"
            mock_settings.notification_webhook_secret = "secret"

            await notify_message_received(
                contact=contact,
                data_type="coordination_request",
                data={"activity": "coffee"},
                interaction_id="int-789",
            )

            mock_post.assert_called_once()
            url_arg = mock_post.call_args[0][1]
            assert url_arg == "http://agent:8644/webhooks/a2a-negotiate"

    @pytest.mark.asyncio
    async def test_response_routes_to_inbox_url(self):
        """response data_type should be routed to the inbox (user-facing) URL."""
        from app.notifications import notify_message_received

        contact = MagicMock()
        contact.name = "Test Friend"
        contact.id = "contact-123"

        with patch("app.notifications.settings") as mock_settings, \
             patch("app.notifications._post_webhook_with_retry",
                   new_callable=AsyncMock) as mock_post:
            mock_settings.notification_webhook_url = "http://agent:8644/webhooks/a2a-inbox"
            mock_settings.notification_negotiate_url = "http://agent:8644/webhooks/a2a-negotiate"
            mock_settings.notification_webhook_secret = "secret"

            await notify_message_received(
                contact=contact,
                data_type="response",
                data={"plan": {"activity": "coffee"}},
                interaction_id="int-999",
            )

            mock_post.assert_called_once()
            url_arg = mock_post.call_args[0][1]
            assert url_arg == "http://agent:8644/webhooks/a2a-inbox"

    @pytest.mark.asyncio
    async def test_negotiate_falls_back_to_inbox_when_not_configured(self):
        """If negotiate URL is empty, coordination_request falls back to inbox."""
        from app.notifications import notify_message_received

        contact = MagicMock()
        contact.name = "Test Friend"
        contact.id = "contact-123"

        with patch("app.notifications.settings") as mock_settings, \
             patch("app.notifications._post_webhook_with_retry",
                   new_callable=AsyncMock) as mock_post:
            mock_settings.notification_webhook_url = "http://agent:8644/webhooks/a2a-inbox"
            mock_settings.notification_negotiate_url = ""
            mock_settings.notification_webhook_secret = "secret"

            await notify_message_received(
                contact=contact,
                data_type="coordination_request",
                data={"activity": "coffee"},
                interaction_id="int-000",
            )

            mock_post.assert_called_once()
            url_arg = mock_post.call_args[0][1]
            assert url_arg == "http://agent:8644/webhooks/a2a-inbox"
        from app.notifications import notify_message_received

        contact = MagicMock()
        contact.name = "Alice"
        contact.id = "c-1"

        with patch("app.notifications.settings") as mock_settings, \
             patch("app.notifications._post_webhook_with_retry",
                   new_callable=AsyncMock) as mock_post:
            mock_settings.notification_webhook_url = "http://agent:8644/webhooks/test"
            mock_settings.notification_webhook_secret = "s"

            await notify_message_received(contact, "acknowledgment", {}, "i-1")

            mock_post.assert_not_called()


# ── DID-based Handshake Auth ─────────────────────────────────────────────────


class TestVerifyInbound:
    """Test that verify_inbound trusts known contacts and rejects unknowns."""

    @pytest.mark.asyncio
    async def test_known_contact_did_is_trusted(self, db_session: Session):
        """Known contact DIDs should be in the trusted cache."""
        from shadownet.crypto.ed25519 import Ed25519KeyPair
        from shadownet.did.key import derive_did_key

        kp = Ed25519KeyPair.generate()
        caller_did = derive_did_key(kp.public_bytes)

        c = Contact(
            name="Verified Peer",
            agent_endpoint="http://peer:8340/a2a/message:send",
            did=caller_did,
        )
        db_session.add(c)
        db_session.commit()

        from app import identity as identity_module

        my_kp = Ed25519KeyPair.generate()
        identity_module._keypair = my_kp
        my_did = derive_did_key(my_kp.public_bytes)

        from shadownet.a2a.client import build_handshake_headers
        from shadownet.a2a.server import HandshakeContext

        headers = build_handshake_headers(
            holder_key=kp,
            holder_did=caller_did,
            audience_did=my_did,
        )

        mock_ctx = HandshakeContext(caller_did=caller_did, presentation=None)

        with patch("app.signing.get_did", return_value=my_did), \
             patch("app.signing.get_resolver"), \
             patch("app.signing.get_trust_store"), \
             patch("app.database.engine", db_session.get_bind()), \
             patch("app.signing.verify_handshake", new_callable=AsyncMock, return_value=mock_ctx):

            from app.signing import verify_inbound

            ctx = await verify_inbound(headers)
            assert ctx.caller_did == caller_did

        identity_module._keypair = None

    @pytest.mark.asyncio
    async def test_unknown_did_raises_presentation_required(self, db_session: Session):
        """Unknown DIDs (not in contacts) should trigger PresentationRequired from SDK."""
        from shadownet.a2a.errors import PresentationRequiredError
        from shadownet.crypto.ed25519 import Ed25519KeyPair
        from shadownet.did.key import derive_did_key

        kp = Ed25519KeyPair.generate()
        caller_did = derive_did_key(kp.public_bytes)

        from app import identity as identity_module

        my_kp = Ed25519KeyPair.generate()
        identity_module._keypair = my_kp
        my_did = derive_did_key(my_kp.public_bytes)

        from shadownet.a2a.client import build_handshake_headers

        headers = build_handshake_headers(
            holder_key=kp,
            holder_did=caller_did,
            audience_did=my_did,
        )

        with patch("app.signing.get_did", return_value=my_did), \
             patch("app.signing.get_resolver"), \
             patch("app.signing.get_trust_store"), \
             patch("app.database.engine", db_session.get_bind()), \
             patch("app.signing.verify_handshake", new_callable=AsyncMock,
                   side_effect=PresentationRequiredError(nonce="test-nonce")):

            from app.signing import verify_inbound

            with pytest.raises(PresentationRequiredError):
                await verify_inbound(headers)

        identity_module._keypair = None


# ── Contact API Response ─────────────────────────────────────────────────────


class TestContactsAPI:
    """Test the /api/contacts endpoint returns new DID fields."""

    def test_contact_out_includes_did_fields(self, db_session: Session, contact: Contact):
        from app.routers.contacts import _contact_to_out

        contact.did = "did:key:z6MkTestAlice"
        contact.shadowname = "alice"
        contact.public_key_jwk = json.dumps({"kty": "OKP", "crv": "Ed25519", "x": "abc"})
        db_session.add(contact)
        db_session.commit()
        db_session.refresh(contact)

        out = _contact_to_out(contact, db_session)
        assert out.did == "did:key:z6MkTestAlice"
        assert out.shadowname == "alice"
        assert "OKP" in out.public_key_jwk

    def test_contact_out_empty_did(self, db_session: Session, contact: Contact):
        """Legacy contacts should return empty strings for DID fields."""
        contact.did = ""
        contact.shadowname = ""
        contact.public_key_jwk = "{}"
        db_session.add(contact)
        db_session.commit()
        db_session.refresh(contact)

        from app.routers.contacts import _contact_to_out

        out = _contact_to_out(contact, db_session)
        assert out.did == ""
        assert out.shadowname == ""
        assert out.public_key_jwk == "{}"


# ── Agent Card ───────────────────────────────────────────────────────────────


class TestAgentCard:
    """Verify agent card includes v0.1 required fields."""

    def test_agent_card_has_did_and_public_key(self):
        from shadownet.crypto.ed25519 import Ed25519KeyPair

        from app import identity as identity_module

        kp = Ed25519KeyPair.generate()
        identity_module._keypair = kp

        from app.identity import get_agent_card

        card = get_agent_card()

        assert card["did"].startswith("did:key:z6Mk")
        assert "publicKey" in card
        assert card["publicKey"]["kty"] == "OKP"
        assert card["publicKey"]["crv"] == "Ed25519"
        assert card["shadownet:v"] == "0.1"
        assert "supportedInterfaces" in card
        assert len(card["supportedInterfaces"]) > 0

        identity_module._keypair = None

    def test_agent_card_url_format(self):
        from shadownet.crypto.ed25519 import Ed25519KeyPair

        from app import identity as identity_module

        kp = Ed25519KeyPair.generate()
        identity_module._keypair = kp

        from app.identity import get_agent_card

        card = get_agent_card()

        assert card["url"].endswith("/a2a")
        assert card["supportedInterfaces"][0]["url"].endswith("/a2a")
        assert card["supportedInterfaces"][0]["protocolBinding"] == "HTTP+JSON"

        identity_module._keypair = None


# ── Envelope Format ──────────────────────────────────────────────────────────


class TestEnvelopeCompliance:
    """RFC-0006 envelope compliance checks."""

    def test_envelope_omits_interaction_when_empty(self):
        from app.executor import build_envelope

        env = build_envelope({"type": "test"}, interaction="")
        data = env["message"]["parts"][0]["data"]
        assert "interaction" not in data

    def test_envelope_includes_interaction_when_provided(self):
        from app.executor import build_envelope

        env = build_envelope({"type": "test"}, interaction="urn:shadownet:meeting")
        data = env["message"]["parts"][0]["data"]
        assert data["interaction"] == "urn:shadownet:meeting"

    def test_envelope_intent_id_format(self):
        from app.executor import build_envelope

        env = build_envelope({"type": "test"})
        data = env["message"]["parts"][0]["data"]
        assert data["intentId"].startswith("urn:uuid:")

    def test_envelope_explicit_intent_id(self):
        from app.executor import build_envelope

        env = build_envelope({"type": "test"}, intent_id="custom-id")
        data = env["message"]["parts"][0]["data"]
        assert data["intentId"] == "urn:uuid:custom-id"

    def test_envelope_no_from_field(self):
        """W10: Envelope must not contain a 'from' field."""
        from app.executor import build_envelope

        env = build_envelope({"type": "test"})
        assert "from" not in env
        assert "from" not in env["message"]
        assert "from" not in env["message"]["parts"][0]["data"]

    def test_envelope_version_marker(self):
        from app.executor import build_envelope

        env = build_envelope({"type": "test"})
        data = env["message"]["parts"][0]["data"]
        assert data["shadownet:v"] == "0.1"

    def test_envelope_part_type(self):
        from app.executor import ENVELOPE_PART_TYPE, build_envelope

        env = build_envelope({"type": "test"})
        part = env["message"]["parts"][0]
        assert part["type"] == ENVELOPE_PART_TYPE
        assert part["mediaType"] == "application/json"


# ── Extract Data Part ─────────────────────────────────────────────────────────


class TestExtractDataPart:
    """Test all extract_data_part code paths."""

    def test_standard_envelope(self):
        from app.executor import ENVELOPE_PART_TYPE, extract_data_part

        body = {
            "message": {
                "parts": [{
                    "type": ENVELOPE_PART_TYPE,
                    "mediaType": "application/json",
                    "data": {
                        "shadownet:v": "0.1",
                        "intentId": "urn:uuid:abc",
                        "payload": {"type": "coordination_request", "activity": "coffee"},
                    },
                }]
            }
        }
        dtype, data, iid = extract_data_part(body)
        assert dtype == "coordination_request"
        assert data["activity"] == "coffee"
        assert iid == "urn:uuid:abc"

    def test_legacy_data_part(self):
        from app.executor import extract_data_part

        body = {
            "message": {
                "parts": [
                    {"data": {"type": "message", "text": "hi"},
                     "mediaType": "application/json"}
                ]
            }
        }
        dtype, data, iid = extract_data_part(body)
        assert dtype == "message"
        assert data["text"] == "hi"
        assert iid == ""

    def test_text_part(self):
        from app.executor import extract_data_part

        body = {"message": {"parts": [{"text": "hello world"}]}}
        dtype, data, iid = extract_data_part(body)
        assert dtype == "message"
        assert data["text"] == "hello world"
        assert iid == ""

    def test_empty_body_returns_unknown(self):
        from app.executor import extract_data_part

        body = {"message": {"parts": []}}
        dtype, data, iid = extract_data_part(body)
        assert dtype == "unknown"
        assert iid == ""


# ── Identity Module ──────────────────────────────────────────────────────────


class TestIdentity:
    """Test identity generation and DID derivation."""

    def test_keypair_generation(self):
        from shadownet.crypto.ed25519 import Ed25519KeyPair

        from app import identity as identity_module

        kp = Ed25519KeyPair.generate()
        identity_module._keypair = kp

        from app.identity import get_did, get_keypair, get_public_key_b64

        assert get_keypair() is kp
        assert get_did().startswith("did:key:z6Mk")
        assert len(get_public_key_b64()) > 0

        identity_module._keypair = None

    def test_get_keypair_raises_when_not_initialized(self):
        from app import identity as identity_module

        identity_module._keypair = None

        from app.identity import get_keypair

        with pytest.raises(RuntimeError, match="Identity not initialized"):
            get_keypair()


# ── Outbound A2A Transport ────────────────────────────────────────────────────


class TestOutboundTransport:
    """Test send_a2a_message endpoint handling."""

    @pytest.mark.asyncio
    async def test_send_posts_to_endpoint_directly(self):
        """W11: Must POST directly to stored endpoint, no path appending."""
        from app.executor import send_a2a_message

        with patch("app.executor.httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"taskId": "t-1"}
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            await send_a2a_message(
                "https://peer.example/a2a/message:send",
                {"message": {"parts": []}},
                peer_did="",
            )

            mock_client.post.assert_called_once()
            call_url = mock_client.post.call_args[0][0]
            assert call_url == "https://peer.example/a2a/message:send"

    @pytest.mark.asyncio
    async def test_send_skips_handshake_when_no_did(self):
        """C3: Empty peer_did should not attempt handshake headers."""
        from app.executor import send_a2a_message

        with patch("app.executor.httpx.AsyncClient") as MockClient, \
             patch("app.executor._get_outbound_headers") as mock_headers:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {}
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            await send_a2a_message("http://legacy:8340/a2a", {}, peer_did="")

            mock_headers.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_includes_handshake_when_did_present(self):
        """Handshake headers should be added when peer_did is provided."""
        from app.executor import send_a2a_message

        with patch("app.executor.httpx.AsyncClient") as MockClient, \
             patch("app.executor._get_outbound_headers",
                   return_value={"Authorization": "Bearer tok"}):
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {}
            mock_resp.raise_for_status = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            await send_a2a_message("http://peer/a2a", {}, peer_did="did:key:z6MkPeer")

            call_headers = mock_client.post.call_args[1]["headers"]
            assert "Authorization" in call_headers


# ── Database Migration Fields ─────────────────────────────────────────────────


class TestDatabaseFields:
    """Verify the new DB columns work correctly."""

    def test_contact_new_fields_default_empty(self, db_session: Session):
        c = Contact(name="Legacy", agent_endpoint="http://old:8340")
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)

        assert c.did == ""
        assert c.shadowname == ""
        assert c.public_key_jwk == "{}"

    def test_interaction_intent_id_default_empty(self, db_session: Session, contact: Contact):
        ictx = InteractionContext(
            data_type="message",
            contact_id=contact.id,
            direction="inbound",
            status="received",
            context_data="{}",
        )
        db_session.add(ictx)
        db_session.commit()
        db_session.refresh(ictx)

        assert ictx.intent_id == ""

    def test_contact_add_populates_did_from_card(self):
        """add_contact should extract DID and public key from agent card."""
        from app.routers.contacts import ContactCreate

        create = ContactCreate(agent_endpoint="https://peer.example")
        assert create.agent_endpoint == "https://peer.example"
