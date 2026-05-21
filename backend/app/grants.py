from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.models import AccessGrant, Contact, GrantType

logger = logging.getLogger(__name__)


class GrantDenied(Exception):
    def __init__(self, action: str, grant_type: str = GrantType.messaging):
        self.action = action
        self.grant_type = grant_type
        super().__init__(f"Grant '{grant_type}' not allowed for action '{action}'")


def find_contact_by_endpoint(session: Session, endpoint: str) -> Contact | None:
    normalized = endpoint.rstrip("/")
    stmt = select(Contact).where(Contact.agent_endpoint == endpoint)
    result = session.exec(stmt).first()
    if result is None:
        stmt = select(Contact).where(Contact.agent_endpoint == normalized)
        result = session.exec(stmt).first()
    if result is None:
        stmt = select(Contact).where(Contact.agent_endpoint == normalized + "/")
        result = session.exec(stmt).first()
    return result


def find_contact_by_did(session: Session, did: str) -> Contact | None:
    if not did:
        return None
    stmt = select(Contact).where(Contact.did == did)
    return session.exec(stmt).first()


def enforce_grant(session: Session, contact: Contact) -> None:
    """Raise GrantDenied if the contact is not allowed to communicate."""
    stmt = (
        select(AccessGrant)
        .where(AccessGrant.contact_id == contact.id)
        .where(AccessGrant.grant_type == GrantType.messaging)
        .where(AccessGrant.allowed == True)  # noqa: E712
    )
    grant = session.exec(stmt).first()
    if grant is None:
        logger.warning("Grant denied: contact=%s", contact.name)
        raise GrantDenied("communicate")
    logger.debug("Grant allowed: contact=%s", contact.name)
