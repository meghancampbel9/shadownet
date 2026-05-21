from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Enums ──────────────────────────────────────────────────────────────────


class GrantType:
    messaging = "messaging"


# ── Tables ─────────────────────────────────────────────────────────────────


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(default_factory=_new_id, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    name: str
    created_at: datetime = Field(default_factory=_utcnow)


class Contact(SQLModel, table=True):
    __tablename__ = "contacts"

    id: str = Field(default_factory=_new_id, primary_key=True)
    name: str
    agent_endpoint: str
    agent_public_key: str = ""
    did: str = ""
    shadowname: str = ""
    public_key_jwk: str = "{}"
    label: str = ""
    notes: str = ""
    metadata_json: str = "{}"
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class AccessGrant(SQLModel, table=True):
    __tablename__ = "access_grants"

    id: str = Field(default_factory=_new_id, primary_key=True)
    contact_id: str = Field(foreign_key="contacts.id", index=True)
    grant_type: str = GrantType.messaging
    allowed: bool = True
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class InteractionContext(SQLModel, table=True):
    __tablename__ = "interaction_contexts"

    id: str = Field(default_factory=_new_id, primary_key=True)
    a2a_task_id: str = Field(default="", index=True)
    intent_id: str = ""
    data_type: str = ""
    contact_id: str = Field(foreign_key="contacts.id", index=True)
    direction: str = "inbound"
    status: str = "received"
    context_data: str = "{}"
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
