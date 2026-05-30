from __future__ import annotations

import pytest
from shadownet.a2a import (
    CredsRequiredError,
    ParseError,
    ReplayError,
)

from tests.conftest import build_inbound


def _add_contact(peer_id: str) -> None:
    from sqlmodel import Session

    from app.database import engine
    from app.models import AccessGrant, Contact, GrantType

    with Session(engine) as s:
        c = Contact(identifier=peer_id, name=peer_id, public_key=peer_id)
        s.add(c)
        s.flush()
        s.add(AccessGrant(contact_id=c.id, grant_type=GrantType.messaging, allowed=True))
        s.commit()


def test_agent_card_self_verifies(app_ready):
    from shadownet.agentcard import verify_self_signed_agent_card

    from app.identity import get_agent_card, get_public_key

    card = get_agent_card()
    verified = verify_self_signed_agent_card(card, get_public_key())
    assert verified.shadow_public_key == get_public_key()
    assert card["shadownet:v"] == "0.2"


def test_inbound_contact_routes_inbox(clean_db, peer_key, our_subject):
    from app.protocol import get_pipeline

    body, _, peer_id = build_inbound(peer_key, our_subject)
    _add_contact(peer_id)
    decision = get_pipeline().receive(body)
    assert decision.route == "inbox"
    assert decision.sender == peer_id


def test_inbound_stranger_no_creds(clean_db, peer_key, our_subject):
    from app.protocol import get_pipeline

    body, _, _ = build_inbound(peer_key, our_subject)
    with pytest.raises(CredsRequiredError):
        get_pipeline().receive(body)


def test_auto_add_on_outbound(clean_db, peer_key, our_subject):
    from app.protocol import get_pipeline, record_outbound_context

    body, _, peer_id = build_inbound(peer_key, our_subject, context_id="CTX-OUT-1")
    record_outbound_context("CTX-OUT-1", peer_id)
    decision = get_pipeline().receive(body)
    assert decision.route == "inbox"
    assert decision.auto_added_contact is True


def test_replay_rejected(clean_db, peer_key, our_subject):
    from app.protocol import get_pipeline

    body, _, peer_id = build_inbound(peer_key, our_subject)
    _add_contact(peer_id)
    get_pipeline().receive(body)
    with pytest.raises(ReplayError):
        get_pipeline().receive(body)


def test_msghash_tamper_rejected(clean_db, peer_key, our_subject):
    from app.protocol import get_pipeline

    body, _, peer_id = build_inbound(peer_key, our_subject, text="original")
    _add_contact(peer_id)
    body["message"]["parts"][0]["text"] = "tampered"
    with pytest.raises(ParseError):
        get_pipeline().receive(body)


def test_credential_stranger_review(peer_key, our_subject):
    import time

    from shadownet.credential import CredentialPayload, mint_credential
    from shadownet.crypto.ed25519 import Ed25519KeyPair
    from shadownet.identifiers import encode_public_key
    from shadownet.provider import ProviderRecord
    from shadownet.receiver import (
        InMemoryContactGraph,
        InMemoryCredentialCache,
        InMemoryReplayCache,
        ReceiverConfig,
        ReceiverPipeline,
    )
    from shadownet.trust import AcceptancePolicy, TrustEntry, TrustStore

    issuer_key = Ed25519KeyPair.generate()
    issuer_pk = encode_public_key(issuer_key.public_bytes)
    issuer_domain = "hub.example"
    peer_id = encode_public_key(peer_key.public_bytes)
    now = int(time.time())
    cred = mint_credential(
        CredentialPayload(
            iss=issuer_domain,
            sub=peer_id,
            kind="org_affiliation",
            org=issuer_domain,
            iat=now,
            exp=now + 3600,
            rev={"epoch": "e1", "idx": 0},
        ),
        issuer_key,
    )
    body, _, _ = build_inbound(peer_key, our_subject, creds=(cred,))

    pipeline = ReceiverPipeline(
        ReceiverConfig(
            subject=our_subject,
            trust_store=TrustStore(
                entries=(TrustEntry(issuer=issuer_domain, accept=("org_affiliation",)),)
            ),
            policy=AcceptancePolicy(),
        ),
        replay_cache=InMemoryReplayCache(),
        contact_graph=InMemoryContactGraph(),
        credential_cache=InMemoryCredentialCache(),
        provider_lookup=lambda d: ProviderRecord(
            domain=d, version="0.2", endpoint="https://hub.example", provider_keys=(issuer_pk,)
        ),
        revocation_check=lambda c: None,
    )
    decision = pipeline.receive(body)
    assert decision.route == "stranger_review"


def test_http_receive_accepts(client, peer_key, our_subject):
    body, _, peer_id = build_inbound(peer_key, our_subject, text="over http")
    _add_contact(peer_id)
    resp = client.post(
        "/a2a/message:send",
        json=body,
        headers={"A2A-Extensions": "urn:shadownet:0.2", "A2A-Version": "1.0"},
    )
    assert resp.status_code == 200
    assert resp.headers["A2A-Extensions"] == "urn:shadownet:0.2"
    assert resp.json()["message"]["role"] == "ROLE_AGENT"


def test_http_receive_tamper_problem_json(client, peer_key, our_subject):
    body, _, peer_id = build_inbound(peer_key, our_subject, text="orig")
    _add_contact(peer_id)
    body["message"]["parts"][0]["text"] = "tampered"
    resp = client.post(
        "/a2a/message:send",
        json=body,
        headers={"A2A-Extensions": "urn:shadownet:0.2", "A2A-Version": "1.0"},
    )
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["type"] == "urn:shadownet:error:parse_error"
    assert "detail" not in resp.json()  # §11 agent opacity


def test_http_receive_missing_extension(client, peer_key, our_subject):
    body, _, _ = build_inbound(peer_key, our_subject)
    resp = client.post("/a2a/message:send", json=body, headers={"A2A-Version": "1.0"})
    assert resp.status_code == 400
    assert resp.json()["type"] == "urn:shadownet:error:parse_error"


def test_agent_card_endpoint(client):
    resp = client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["shadownet:v"] == "0.2"
    assert card["securitySchemes"]["shadownet:pinned-self-signed"] == {}
