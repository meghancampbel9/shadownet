from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

logger = logging.getLogger(__name__)

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.database_url, connect_args=connect_args)


if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def init_db() -> None:
    # v0.1 → v0.2 is a breaking schema change with no production data. If a
    # legacy database is present, drop it and recreate against the new models.
    legacy = {"interaction_contexts"}
    existing = set(inspect(engine).get_table_names())
    if legacy & existing:
        logger.warning("Dropping legacy v0.1 schema %s and recreating for v0.2", legacy & existing)
        with engine.begin() as conn:
            for table in legacy & existing:
                conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
        SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
