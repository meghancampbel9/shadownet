"""A2A protocol HTTP+JSON/REST endpoints.

Thin routing layer: authentication, grant check, then store + ack via the
generic handle_inbound function. No domain logic.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session, select

from app.database import get_session
from app.executor import extract_data_part, handle_inbound, task_response
from app.grants import GrantDenied, find_contact_by_endpoint
from app.identity import get_agent_card
from app.models import InteractionContext
from app.notifications import register_push_config
from app.signing import verify_a2a_jwt

logger = logging.getLogger(__name__)

router = APIRouter(tags=["a2a"])


# ── Agent Card ──────────────────────────────────────────────────────────────


@router.get("/.well-known/agent-card.json")
def agent_card():
    return get_agent_card()


# ── Authentication ─────────────────────────────────────────────────────────


def _authenticate_sender(request: Request, session: Session):
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing Bearer token")

    token = auth_header[7:]

    import jwt as _jwt

    try:
        unverified = _jwt.decode(token, options={"verify_signature": False})
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed JWT")

    sender_url = unverified.get("sub", "")
    if not sender_url:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "JWT missing 'sub' claim")

    contact = find_contact_by_endpoint(session, sender_url)
    if contact is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, {"error": "unknown_agent", "sender": sender_url}
        )

    pub_key = contact.agent_public_key
    sender_pub = unverified.get("pub", "")
    if not pub_key:
        if sender_pub:
            contact.agent_public_key = sender_pub
            session.add(contact)
            session.commit()
            pub_key = sender_pub
            logger.info("Auto-populated public key for contact %s", contact.name)
        else:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Contact has no public key and JWT has no 'pub' claim",
            )

    claims = verify_a2a_jwt(token, pub_key)
    if claims is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid JWT signature")

    return contact, claims


# ── A2A Message Send ────────────────────────────────────────────────────────


@router.post("/a2a/message:send")
async def a2a_message_send(request: Request, session: Session = Depends(get_session)):
    body = await request.json()
    contact, claims = _authenticate_sender(request, session)

    from app.grants import enforce_grant

    try:
        enforce_grant(session, contact)
    except GrantDenied as exc:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "error": "grant_denied",
                "required_grant": exc.grant_type,
            },
        )

    data_type, data = extract_data_part(body)
    message_obj = body.get("message", {})
    task_id = message_obj.get("taskId")

    logger.info("A2A message:send from=%s type=%s taskId=%s", contact.name, data_type, task_id)

    result = await handle_inbound(data_type, data, contact, task_id, session)
    return result


# ── Task Endpoints ──────────────────────────────────────────────────────────


@router.get("/a2a/tasks/{task_id}")
def a2a_get_task(task_id: str, request: Request, session: Session = Depends(get_session)):
    contact, _ = _authenticate_sender(request, session)

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
def a2a_cancel_task(task_id: str, request: Request, session: Session = Depends(get_session)):
    contact, _ = _authenticate_sender(request, session)

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


# ── Push Notification Config ───────────────────────────────────────────────


@router.post("/a2a/tasks/{task_id}/pushNotificationConfigs")
async def a2a_create_push_config(
    task_id: str, request: Request, session: Session = Depends(get_session)
):
    contact, _ = _authenticate_sender(request, session)

    ictx = session.get(InteractionContext, task_id)
    if ictx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, {"error": "TaskNotFoundError"})

    body = await request.json()
    config = register_push_config(
        task_id,
        {
            "url": body.get("url", ""),
            "authentication": body.get("authentication"),
            "contact_id": contact.id,
        },
    )
    return config


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
                # TODO: migrate to a proper task manager so notifications are truly fire-and-forget
                # without blocking the webhook response.
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
