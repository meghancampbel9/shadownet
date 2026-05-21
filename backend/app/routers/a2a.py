"""A2A protocol HTTP+JSON/REST endpoints.

Thin routing layer: authentication via RFC-0006 handshake, grant check,
then store + ack via the generic handle_inbound function. No domain logic.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from shadownet.a2a.errors import (
    LevelInsufficientError,
    PresentationInvalidError,
    PresentationRequiredError,
)
from sqlmodel import Session, select

from app.database import get_session
from app.executor import extract_data_part, handle_inbound, task_response
from app.grants import GrantDenied, enforce_grant, find_contact_by_did, find_contact_by_endpoint
from app.identity import get_agent_card
from app.models import InteractionContext
from app.signing import verify_inbound

logger = logging.getLogger(__name__)

router = APIRouter(tags=["a2a"])


# ── Agent Card ──────────────────────────────────────────────────────────────


@router.get("/.well-known/agent-card.json")
def agent_card():
    return get_agent_card()


# ── Authentication ─────────────────────────────────────────────────────────


async def _authenticate_sender(request: Request, session: Session):
    headers = dict(request.headers.items())

    try:
        ctx = await verify_inbound(headers)
    except PresentationRequiredError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {
                "error": "presentation_required",
                "nonce": exc.nonce,
                "shadownet:v": "0.1",
            },
        )
    except PresentationInvalidError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": "presentation_invalid", "detail": str(exc), "shadownet:v": "0.1"},
        )
    except LevelInsufficientError as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"error": "level_insufficient", "detail": str(exc), "shadownet:v": "0.1"},
        )

    caller_did = ctx.caller_did
    contact = find_contact_by_did(session, caller_did)
    if contact is None:
        contact = find_contact_by_endpoint(session, caller_did)
    if contact is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"error": "unknown_agent", "sender": caller_did, "shadownet:v": "0.1"},
        )

    return contact, ctx


# ── A2A Message Send ────────────────────────────────────────────────────────


@router.post("/a2a/message:send")
async def a2a_message_send(request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    contact, ctx = await _authenticate_sender(request, session)

    try:
        enforce_grant(session, contact)
    except GrantDenied as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"error": "grant_denied", "required_grant": exc.grant_type, "shadownet:v": "0.1"},
        )

    data_type, data, intent_id = extract_data_part(body)
    message_obj = body.get("message", {})
    task_id = message_obj.get("taskId")

    logger.info(
        "A2A message:send from=%s (did=%s) type=%s", contact.name, ctx.caller_did, data_type
    )

    result = await handle_inbound(data_type, data, contact, task_id, session, intent_id=intent_id)
    return result


# ── Task Endpoints ──────────────────────────────────────────────────────────


@router.get("/a2a/tasks/{task_id}")
async def a2a_get_task(task_id: str, request: Request, session: Session = Depends(get_session)):
    contact, _ = await _authenticate_sender(request, session)

    ictx = session.get(InteractionContext, task_id)
    if ictx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"error": "TaskNotFoundError"})
    if ictx.contact_id != contact.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"error": "TaskNotFoundError"})

    state = _status_to_state(ictx.status)
    ctx_data = json.loads(ictx.context_data)

    artifacts = []
    if ctx_data:
        artifacts.append(
            {
                "artifactId": ictx.id + "-data",
                "name": "context",
                "parts": [{"data": ctx_data, "mediaType": "application/json"}],
            }
        )

    return task_response(ictx.id, state, artifacts=artifacts if artifacts else None)


@router.post("/a2a/tasks/{task_id}:cancel")
async def a2a_cancel_task(task_id: str, request: Request, session: Session = Depends(get_session)):
    contact, _ = await _authenticate_sender(request, session)

    ictx = session.get(InteractionContext, task_id)
    if ictx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"error": "TaskNotFoundError"})

    if ictx.status in ("completed", "cancelled"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"error": "TaskNotCancelableError"})

    ictx.status = "cancelled"
    ictx.updated_at = datetime.now(timezone.utc)
    session.add(ictx)
    session.commit()

    return task_response(ictx.id, "TASK_STATE_CANCELED")


# ── Webhook (receiving push notifications from remote agents) ──────────────


@router.post("/a2a/webhook")
async def a2a_webhook(request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    logger.info("A2A webhook received: %s", json.dumps(body)[:500])

    status_update = body.get("statusUpdate")
    if status_update:
        remote_task_id = status_update.get("taskId")
        new_status = status_update.get("status", {})
        state = new_status.get("state", "")

        ictx = None
        if remote_task_id:
            ictx = session.exec(
                select(InteractionContext)
                .where(InteractionContext.context_data.contains(remote_task_id))
                .order_by(InteractionContext.created_at.desc())
            ).first()

        if ictx:
            if state in ("TASK_STATE_COMPLETED",):
                ictx.status = "completed"
            elif state in ("TASK_STATE_CANCELED",):
                ictx.status = "cancelled"
            elif state in ("TASK_STATE_FAILED",):
                ictx.status = "failed"

            ictx.updated_at = datetime.now(timezone.utc)
            session.add(ictx)
            session.commit()

            from app.models import Contact
            from app.notifications import notify_interaction_updated

            contact = session.get(Contact, ictx.contact_id) if ictx.contact_id else None
            if contact:
                await notify_interaction_updated(contact, ictx.id, ictx.status)

            logger.info("Webhook updated interaction %s to %s", ictx.id, ictx.status)
        else:
            logger.warning("Webhook: no matching interaction for task_id=%s", remote_task_id)

    return {"received": True}


# ── Helpers ─────────────────────────────────────────────────────────────────


_STATUS_STATE_MAP = {
    "received": "TASK_STATE_SUBMITTED",
    "active": "TASK_STATE_WORKING",
    "sent": "TASK_STATE_WORKING",
    "completed": "TASK_STATE_COMPLETED",
    "cancelled": "TASK_STATE_CANCELED",
    "failed": "TASK_STATE_FAILED",
}


def _status_to_state(status_str: str) -> str:
    return _STATUS_STATE_MAP.get(status_str, "TASK_STATE_UNSPECIFIED")
