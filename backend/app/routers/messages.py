from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import get_session
from app.deps import CurrentUser
from app.models import Contact, Message

router = APIRouter(prefix="/messages", tags=["messages"])


class MessageOut(BaseModel):
    id: str
    message_id: str
    context_id: str
    sender: str
    recipient: str
    contact_name: str
    direction: str
    route: str
    intent: str
    body: dict
    created_at: str


@router.get("", response_model=list[MessageOut])
def list_messages(
    user: CurrentUser,
    direction: str | None = None,
    contact_id: str | None = None,
    intent: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    session: Session = Depends(get_session),
):
    stmt = select(Message).order_by(Message.created_at.desc()).offset(offset).limit(limit)
    if direction:
        stmt = stmt.where(Message.direction == direction)
    if contact_id:
        stmt = stmt.where(Message.contact_id == contact_id)
    if intent:
        stmt = stmt.where(Message.intent == intent)

    results = []
    for m in session.exec(stmt).all():
        contact = session.get(Contact, m.contact_id) if m.contact_id else None
        results.append(
            MessageOut(
                id=m.id,
                message_id=m.message_id,
                context_id=m.context_id,
                sender=m.sender,
                recipient=m.recipient,
                contact_name=contact.name if contact else (m.sender or m.recipient),
                direction=m.direction,
                route=m.route,
                intent=m.intent,
                body=json.loads(m.body_json),
                created_at=m.created_at.isoformat(),
            )
        )
    return results
