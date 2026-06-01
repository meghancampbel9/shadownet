from __future__ import annotations

import time
from pathlib import Path

import pytest


def pytest_configure(config):
    import app.config as _cfg
    from app.config import Settings

    _cfg.settings = Settings(_env_file=Path(__file__).parent.parent / ".env.test")


@pytest.fixture(autouse=True, scope="session")
def app_ready():
    """Fresh DB + identity + receiver pipeline for the whole test session."""
    from app.config import settings

    if settings.environment != "test":
        pytest.fail(f"Tests must run with SHADOWNET_ENVIRONMENT=test, got '{settings.environment}'")

    db_path = Path("/tmp/shadownet-test/test.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for f in db_path.parent.glob("test.db*"):
        f.unlink()

    from app import protocol
    from app.database import init_db
    from app.identity import init_identity

    init_db()
    init_identity()
    protocol.init()
    yield


@pytest.fixture(autouse=True)
def clean_db():
    """Truncate per-test mutable tables."""
    from sqlmodel import Session, delete

    from app.database import engine
    from app.models import (
        AccessGrant,
        Contact,
        Message,
        OnboardToken,
        OutboundContext,
        ReplayEntry,
        User,
    )

    with Session(engine) as s:
        for model in (
            AccessGrant,
            Contact,
            Message,
            OnboardToken,
            OutboundContext,
            ReplayEntry,
            User,
        ):
            s.exec(delete(model))
        s.commit()
    yield


@pytest.fixture()
def peer_key():
    from shadownet.crypto.ed25519 import Ed25519KeyPair

    return Ed25519KeyPair.generate()


@pytest.fixture()
def our_subject():
    from app.identity import get_subject

    return get_subject()


def build_inbound(
    peer_key,
    recipient,
    *,
    text="hello",
    intent=None,
    data=None,
    context_id=None,
    creds=(),
):
    """Construct the A2A message:send body a peer would POST to us."""
    from shadownet.a2a import build_and_sign_message, build_outbound_message
    from shadownet.envelope import MAX_LIFETIME_SECONDS, EnvelopeBody, EnvelopePayload
    from shadownet.identifiers import encode_public_key

    peer_id = encode_public_key(peer_key.public_bytes)
    now = int(time.time())
    payload = EnvelopePayload(
        v="0.2",
        sender=peer_id,
        recipient=recipient,
        iat=now,
        exp=now + MAX_LIFETIME_SECONDS,
        msg_hash="sha256:placeholder",
        body=EnvelopeBody(text=text, intent=intent, data=data),
        creds=tuple(creds),
    )
    msg = build_outbound_message(body_text=text, context_id=context_id)
    built = build_and_sign_message(msg, payload, peer_key)
    return {"message": built.message}, built.message["messageId"], peer_id


@pytest.fixture(scope="session")
def client():
    # Session-scoped: the FastMCP StreamableHTTP session manager can only run
    # once per process, so the app lifespan must be entered a single time.
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
