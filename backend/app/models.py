from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class GrantType:
    messaging = "messaging"


class Route:
    inbox = "inbox"
    stranger_review = "stranger_review"
    outbound = "outbound"


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
    identifier: str = Field(index=True)  # wire id: shadowname or z6Mk public key
    name: str = ""
    public_key: str = ""  # multibase Ed25519 (z6Mk...)
    agent_endpoint: str = ""
    label: str = ""
    notes: str = ""
    profile_json: str = "{}"  # RFC 0002 §6 ContactProfile (local-only)
    metadata_json: str = "{}"
    added_at: datetime = Field(default_factory=_utcnow)
    last_seen: datetime | None = None
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


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: str = Field(default_factory=_new_id, primary_key=True)
    message_id: str = Field(index=True)  # wire A2A messageId
    context_id: str = Field(default="", index=True)
    sender: str = ""  # envelope `from`
    recipient: str = ""  # envelope `to`
    direction: str = "inbound"  # inbound | outbound
    route: str = Route.inbox  # inbox | stranger_review | outbound
    intent: str = ""  # body.intent URI
    body_json: str = "{}"  # {text?, intent?, data?}
    contact_id: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class ReplayEntry(SQLModel, table=True):
    __tablename__ = "replay_entries"

    id: str = Field(default_factory=_new_id, primary_key=True)
    sender: str = Field(index=True)
    message_id: str = Field(index=True)
    expires_at: datetime = Field(default_factory=_utcnow)


class OutboundContext(SQLModel, table=True):
    __tablename__ = "outbound_contexts"

    id: str = Field(default_factory=_new_id, primary_key=True)
    context_id: str = Field(index=True)
    peer: str = Field(index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class OnboardToken(SQLModel, table=True):
    __tablename__ = "onboard_tokens"

    id: str = Field(default_factory=_new_id, primary_key=True)
    subject: str = ""  # the Subject (user id) this token acts for
    kind: str = "access"  # access | refresh | handoff
    token: str = Field(index=True, unique=True)
    family_id: str = Field(default_factory=_new_id, index=True)
    revoked: bool = False
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)
