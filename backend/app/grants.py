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


def find_contact_by_identifier(session: Session, identifier: str) -> Contact | None:
    if not identifier:
        return None
    return session.exec(select(Contact).where(Contact.identifier == identifier)).first()


def is_allowed_contact(session: Session, identifier: str) -> bool:
    """True if `identifier` is a contact with an allowed messaging grant (RFC 0002 §4)."""
    contact = find_contact_by_identifier(session, identifier)
    if contact is None:
        return False
    grant = session.exec(
        select(AccessGrant)
        .where(AccessGrant.contact_id == contact.id)
        .where(AccessGrant.grant_type == GrantType.messaging)
        .where(AccessGrant.allowed == True)  # noqa: E712
    ).first()
    return grant is not None


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
