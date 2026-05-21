from __future__ import annotations

from pathlib import Path

import pytest


def pytest_configure(config):
    import app.config as _cfg
    from app.config import Settings

    # noinspection PyArgumentList
    _cfg.settings = Settings(_env_file=Path(__file__).parent.parent / ".env.test")


@pytest.fixture(autouse=True, scope="session")
def require_test_env():
    from app.config import settings

    if settings.environment != "test":
        pytest.fail(f"Tests must run with SHADOWNET_ENVIRONMENT=test, got '{settings.environment}'")


@pytest.fixture()
def db_session():
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture()
def contact(db_session):
    from app.models import Contact

    c = Contact(
        name="Alice",
        agent_endpoint="http://alice:8340",
        agent_public_key="AAAA",
        did="did:key:z6MkTestAlice",
        label="friend",
    )
    db_session.add(c)
    db_session.commit()
    db_session.refresh(c)
    return c


@pytest.fixture()
def client(db_session):
    from contextlib import asynccontextmanager

    from fastapi.testclient import TestClient
    from shadownet.crypto.ed25519 import Ed25519KeyPair

    from app import identity as identity_module
    from app.database import get_session
    from app.main import app

    @asynccontextmanager
    async def test_lifespan(_app):
        keypair = Ed25519KeyPair.generate()
        identity_module._keypair = keypair
        yield
        identity_module._keypair = None

    def override_session():
        yield db_session

    # noinspection PyTypeChecker
    app.router.lifespan_context = test_lifespan
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
