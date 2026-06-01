"""Outbound envelope dispatch (RFC 0001 §8.3, §8.10) and inbound persistence."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi.concurrency import run_in_threadpool
from shadownet.a2a import (
    BuiltMessage,
    ShadownetWireError,
    TransportRetryExhausted,
    asend_with_retries,
    build_and_sign_message,
    build_outbound_message,
)
from shadownet.envelope import MAX_LIFETIME_SECONDS, EnvelopeBody, EnvelopePayload
from shadownet.errors import ShadownetError
from sqlmodel import Session, select

from app.config import settings
from app.database import engine
from app.identity import get_keypair, get_subject
from app.models import Contact, Message, Route
from app.protocol import own_credentials, record_outbound_context, resolve_recipient

logger = logging.getLogger(__name__)

inbox_event: asyncio.Event = asyncio.Event()


def notify_inbox() -> None:
    """Wake inbox_wait long-pollers after new inbound activity."""
    inbox_event.set()


def _new_id() -> str:
    return uuid.uuid4().hex.upper()


@dataclass(frozen=True)
class SendResult:
    message_id: str
    context_id: str
    status: str  # "accepted" | "rejected"
    error: str | None = None


async def send_message(
    to: str,
    *,
    text: str | None = None,
    intent: str | None = None,
    data: dict[str, Any] | None = None,
    context_id: str | None = None,
) -> SendResult:
    """Resolve, then send a Shadownet envelope via the SDK §8.10 retry-with-remint."""
    try:
        identifier, endpoint, _peer_pk = await run_in_threadpool(resolve_recipient, to)
    except ShadownetError as exc:
        logger.warning("Resolve failed for %s: %s", to, exc)
        return SendResult(_new_id(), context_id or _new_id(), "rejected", "resolve_failed")

    ctx = context_id or _new_id()
    body = EnvelopeBody(text=text, intent=intent, data=data)
    creds = own_credentials()
    keypair = get_keypair()
    subject = get_subject()
    captured: dict[str, str] = {}

    def builder() -> BuiltMessage:
        now = int(time.time())
        payload = EnvelopePayload(
            v="0.2",
            sender=subject,
            recipient=identifier,
            iat=now,
            exp=now + MAX_LIFETIME_SECONDS,
            msg_hash="sha256:placeholder",
            body=body,
            creds=creds,
        )
        built = build_and_sign_message(
            build_outbound_message(body_text=text, context_id=ctx), payload, keypair
        )
        captured["message_id"] = built.message["messageId"]
        return built

    # Foreground send: bound the retry budget by the request timeout so the host
    # LLM is not blocked indefinitely. Long-horizon background delivery is future
    # work (would use the SDK default 24h budget off the request path).
    try:
        await asend_with_retries(
            builder,
            endpoint,
            timeout=settings.agent_request_timeout,
            initial_delay=settings.agent_retry_base_delay,
            total_budget=float(settings.agent_request_timeout),
        )
    except ShadownetWireError as exc:
        code = getattr(exc, "code", "") or "rejected"
        logger.info("Send to %s rejected: %s", identifier, code)
        return SendResult(captured.get("message_id", _new_id()), ctx, "rejected", code)
    except TransportRetryExhausted:
        logger.warning("Send to %s unreachable (retry budget exhausted)", identifier)
        return SendResult(captured.get("message_id", _new_id()), ctx, "rejected", "unreachable")

    record_outbound_context(ctx, identifier)
    _persist_outbound(captured["message_id"], ctx, identifier, body, intent)
    return SendResult(captured["message_id"], ctx, "accepted")


def _persist_outbound(
    message_id: str, context_id: str, recipient: str, body: EnvelopeBody, intent: str | None
) -> None:
    with Session(engine) as s:
        contact = s.exec(select(Contact).where(Contact.identifier == recipient)).first()
        s.add(
            Message(
                message_id=message_id,
                context_id=context_id,
                sender=get_subject(),
                recipient=recipient,
                direction="outbound",
                route=Route.outbound,
                intent=intent or "",
                body_json=body.model_dump_json(exclude_none=True),
                contact_id=contact.id if contact else "",
            )
        )
        s.commit()


def persist_inbound(decision: Any, *, message_id: str, context_id: str) -> Message:
    """Store an accepted inbound envelope by route and wake inbox_wait."""
    envelope: EnvelopePayload = decision.envelope
    body = envelope.body
    with Session(engine) as s:
        contact = s.exec(select(Contact).where(Contact.identifier == decision.sender)).first()
        if contact is not None:
            contact.last_seen = datetime.now(timezone.utc)
            s.add(contact)
        msg = Message(
            message_id=message_id,
            context_id=context_id,
            sender=decision.sender,
            recipient=envelope.recipient,
            direction="inbound",
            route=decision.route,
            intent=body.intent or "",
            body_json=body.model_dump_json(exclude_none=True),
            contact_id=contact.id if contact else "",
        )
        s.add(msg)
        s.commit()
        s.refresh(msg)
    logger.info("Stored inbound %s from %s (route=%s)", message_id, decision.sender, decision.route)
    notify_inbox()
    return msg
