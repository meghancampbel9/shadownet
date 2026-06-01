from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from shadownet.errors import ShadownetError
from sqlmodel import Session, select

from app.database import get_session
from app.deps import CurrentUser
from app.models import AccessGrant, Contact, GrantType
from app.protocol import get_credential_cache, resolve_recipient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contacts", tags=["contacts"])


class ContactCreate(BaseModel):
    identifier: str  # shadowname (alice@host) or shadow:// connection URI
    name: str | None = None
    label: str = ""
    notes: str = ""
    profile: dict = {}


class ContactUpdate(BaseModel):
    name: str | None = None
    label: str | None = None
    notes: str | None = None
    profile: dict | None = None


class GrantUpdate(BaseModel):
    allowed: bool


class CredentialOut(BaseModel):
    kind: str
    issuer: str
    org: str
    expiresAt: str


class ContactOut(BaseModel):
    id: str
    identifier: str
    name: str
    public_key: str
    agent_endpoint: str
    label: str
    notes: str
    profile: dict
    allowed: bool
    grants: dict[str, bool]
    credentials: list[CredentialOut]
    added_at: str
    last_seen: str | None
    created_at: str
    updated_at: str


def _credentials_for(identifier: str) -> list[CredentialOut]:
    out: list[CredentialOut] = []
    for cred in get_credential_cache().for_sender(identifier):
        p = cred.payload
        out.append(
            CredentialOut(
                kind=p.kind,
                issuer=p.iss,
                org=p.org,
                expiresAt=datetime.fromtimestamp(p.exp, tz=timezone.utc).isoformat(),
            )
        )
    return out


def _contact_to_out(contact: Contact, session: Session) -> ContactOut:
    grant = session.exec(
        select(AccessGrant)
        .where(AccessGrant.contact_id == contact.id)
        .where(AccessGrant.grant_type == GrantType.messaging)
    ).first()
    allowed = grant.allowed if grant else True
    return ContactOut(
        id=contact.id,
        identifier=contact.identifier,
        name=contact.name,
        public_key=contact.public_key,
        agent_endpoint=contact.agent_endpoint,
        label=contact.label,
        notes=contact.notes,
        profile=json.loads(contact.profile_json),
        allowed=allowed,
        grants={"messaging": allowed},
        credentials=_credentials_for(contact.identifier),
        added_at=contact.added_at.isoformat(),
        last_seen=contact.last_seen.isoformat() if contact.last_seen else None,
        created_at=contact.created_at.isoformat(),
        updated_at=contact.updated_at.isoformat(),
    )


@router.get("", response_model=list[ContactOut])
def list_contacts(user: CurrentUser, session: Session = Depends(get_session)):
    return [_contact_to_out(c, session) for c in session.exec(select(Contact)).all()]


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def add_contact(
    body: ContactCreate, user: CurrentUser, session: Session = Depends(get_session)
):
    try:
        identifier, endpoint, public_key = await run_in_threadpool(
            resolve_recipient, body.identifier
        )
    except ShadownetError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not resolve contact: {exc}")

    if session.exec(select(Contact).where(Contact.identifier == identifier)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Contact already exists")

    contact = Contact(
        identifier=identifier,
        name=body.name or identifier,
        public_key=public_key,
        agent_endpoint=endpoint,
        label=body.label,
        notes=body.notes,
        profile_json=json.dumps(body.profile),
    )
    session.add(contact)
    session.flush()
    session.add(AccessGrant(contact_id=contact.id, grant_type=GrantType.messaging, allowed=True))
    session.commit()
    session.refresh(contact)
    return _contact_to_out(contact, session)


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: str, user: CurrentUser, session: Session = Depends(get_session)):
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    return _contact_to_out(contact, session)


@router.put("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: str,
    body: ContactUpdate,
    user: CurrentUser,
    session: Session = Depends(get_session),
):
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    if body.name is not None:
        contact.name = body.name
    if body.label is not None:
        contact.label = body.label
    if body.notes is not None:
        contact.notes = body.notes
    if body.profile is not None:
        contact.profile_json = json.dumps(body.profile)
    contact.updated_at = datetime.now(timezone.utc)
    session.add(contact)
    session.commit()
    session.refresh(contact)
    return _contact_to_out(contact, session)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(contact_id: str, user: CurrentUser, session: Session = Depends(get_session)):
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    for g in session.exec(select(AccessGrant).where(AccessGrant.contact_id == contact_id)).all():
        session.delete(g)
    session.delete(contact)
    session.commit()


@router.put("/{contact_id}/grant", response_model=ContactOut)
def update_grant(
    contact_id: str,
    body: GrantUpdate,
    user: CurrentUser,
    session: Session = Depends(get_session),
):
    contact = session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    existing = session.exec(
        select(AccessGrant)
        .where(AccessGrant.contact_id == contact_id)
        .where(AccessGrant.grant_type == GrantType.messaging)
    ).first()
    if existing:
        existing.allowed = body.allowed
        session.add(existing)
    else:
        session.add(
            AccessGrant(contact_id=contact_id, grant_type=GrantType.messaging, allowed=body.allowed)
        )
    session.commit()
    return _contact_to_out(contact, session)
