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
        pytest.fail(
            f"Tests must run with SHADOWNET_ENVIRONMENT=test, got '{settings.environment}'"
        )


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
    from nacl.signing import SigningKey

    from app import identity as identity_module
    from app.database import get_session
    from app.main import app

    @asynccontextmanager
    async def test_lifespan(_app):
        key = SigningKey.generate()
        identity_module._signing_key = key
        identity_module._verify_key = key.verify_key
        yield
        identity_module._signing_key = None
        identity_module._verify_key = None

    def override_session():
        yield db_session

    # noinspection PyTypeChecker
    app.router.lifespan_context = test_lifespan
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
