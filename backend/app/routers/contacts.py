from __future__ import annotations

import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.deps import CurrentUser
from app.models import AccessGrant, Contact, GrantType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contacts", tags=["contacts"])


# ── Schemas ────────────────────────────────────────────────────────────────


class ContactCreate(BaseModel):
    agent_endpoint: str
    name: Optional[str] = None
    label: str = ""
    notes: str = ""
    metadata: dict = {}


class ContactUpdate(BaseModel):
    name: Optional[str] = None
    label: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[dict] = None


class GrantUpdate(BaseModel):
    allowed: bool


class ContactOut(BaseModel):
    id: str
    name: str
    agent_endpoint: str
    agent_public_key: str
    did: str
    shadowname: str
    public_key_jwk: str
    label: str
    notes: str
    metadata: dict
    allowed: bool
    grants: dict[str, bool]
    created_at: str
    updated_at: str


# ── Helpers ────────────────────────────────────────────────────────────────


def _contact_to_out(contact: Contact, session: Session) -> ContactOut:
    grant = session.exec(
        select(AccessGrant)
        .where(AccessGrant.contact_id == contact.id)
        .where(AccessGrant.grant_type == GrantType.messaging)
    ).first()
    allowed = grant.allowed if grant else True
    return ContactOut(
        id=contact.id,
        name=contact.name,
        agent_endpoint=contact.agent_endpoint,
        agent_public_key=contact.agent_public_key,
        did=contact.did,
        shadowname=contact.shadowname,
        public_key_jwk=contact.public_key_jwk,
        label=contact.label,
        notes=contact.notes,
        metadata=json.loads(contact.metadata_json),
        allowed=allowed,
        grants={"messaging": allowed},
        created_at=contact.created_at.isoformat(),
        updated_at=contact.updated_at.isoformat(),
    )


async def _fetch_agent_card(endpoint: str) -> dict:
    url = endpoint.rstrip("/") + "/.well-known/agent-card.json"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ContactOut])
def list_contacts(user: CurrentUser, session: Session = Depends(get_session)):
    contacts = session.exec(select(Contact)).all()
    return [_contact_to_out(c, session) for c in contacts]


@router.post("", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
async def add_contact(
    body: ContactCreate,
    user: CurrentUser,
    session: Session = Depends(get_session),
):
    existing = session.exec(
        select(Contact).where(Contact.agent_endpoint == body.agent_endpoint)
    ).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Contact with this endpoint already exists")

    try:
        card = await _fetch_agent_card(body.agent_endpoint)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Could not fetch agent card from {body.agent_endpoint}: {exc}",
        )

    card_name = card.get("name", "")
    provider = card.get("provider", {})
    owner_name = provider.get("organization", "") if isinstance(provider, dict) else ""
    display_name = body.name or owner_name or card_name or "Unknown"
    metadata_val = card.get("metadata", {})
    public_key = metadata_val.get("publicKey", "") if isinstance(metadata_val, dict) else ""

    card_did = card.get("did", "")
    card_public_key_jwk = json.dumps(card.get("publicKey", {})) if card.get("publicKey") else "{}"

    a2a_url = ""
    interfaces = card.get("supportedInterfaces", [])
    if interfaces and isinstance(interfaces, list):
        a2a_url = interfaces[0].get("url", "")
    if not a2a_url:
        a2a_url = card.get("url", "")
    endpoint = a2a_url + "/message:send" if a2a_url else body.agent_endpoint.rstrip("/") + "/a2a/message:send"

    contact = Contact(
        name=display_name,
        agent_endpoint=endpoint,
        agent_public_key=public_key,
        did=card_did,
        public_key_jwk=card_public_key_jwk,
        label=body.label,
        notes=body.notes,
        metadata_json=json.dumps(body.metadata),
    )
    session.add(contact)
    session.commit()
    session.refresh(contact)

    _create_default_grant(session, contact.id)
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
    if body.metadata is not None:
        contact.metadata_json = json.dumps(body.metadata)

    from datetime import datetime, timezone

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
    grants = session.exec(select(AccessGrant).where(AccessGrant.contact_id == contact_id)).all()
    for g in grants:
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


def _create_default_grant(session: Session, contact_id: str) -> None:
    session.add(AccessGrant(contact_id=contact_id, grant_type=GrantType.messaging, allowed=True))
    session.commit()
