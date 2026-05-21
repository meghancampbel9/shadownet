"""Notification helpers (webhook dispatch).

RFC-0007 compliant webhook format with retry schedule and spec headers.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac as hmac_mod
import json
import logging
import secrets
import time
import uuid
from typing import Any

from httpx import AsyncClient

from app.config import settings

logger = logging.getLogger(__name__)

RETRY_SCHEDULE_SECONDS = (0, 5, 30, 300, 1800)
_SIDECAR_INSTANCE_ID: str = secrets.token_hex(8)

_degraded_urls: set[str] = set()
_failure_counts: dict[str, int] = {}


# ── Webhook Notifications (RFC-0007 format) ────────────────────────────────


def _build_webhook_headers(body_bytes: bytes, secret: str) -> dict[str, str]:
    """Build RFC-0007 compliant webhook headers.

    Also includes X-Webhook-Signature for compatibility with generic webhook
    receivers (e.g. hermes-agent gateway) that don't recognize the spec headers.
    """
    ts = str(int(time.time()))
    sig = hmac_mod.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Shadownet-Sidecar-Sig": f"sha256={sig}",
        "X-Shadownet-Sidecar-Ts": ts,
        "X-Shadownet-Sidecar-Id": _SIDECAR_INSTANCE_ID,
        "X-Webhook-Signature": sig,
    }


async def _post_webhook_with_retry(payload: dict, url: str) -> None:
    """Post webhook with spec retry schedule."""
    if not url:
        return
    if url in _degraded_urls:
        logger.debug("URL %s is degraded; skipping webhook", url)
        return

    body = json.dumps(payload).encode()
    secret = settings.notification_webhook_secret

    for attempt, delay in enumerate(RETRY_SCHEDULE_SECONDS):
        if delay > 0:
            await asyncio.sleep(delay)

        try:
            headers: dict[str, str]
            if secret:
                headers = _build_webhook_headers(body, secret)
            else:
                headers = {"Content-Type": "application/json"}

            async with AsyncClient(timeout=10) as client:
                resp = await client.post(url, content=body, headers=headers)
                if 200 <= resp.status_code < 300:
                    _failure_counts.pop(url, None)
                    if url in _degraded_urls:
                        _degraded_urls.discard(url)
                        logger.info("Webhook URL %s recovered from degraded state", url)
                    logger.info("Webhook sent: %s (attempt %d)", payload.get("event"), attempt + 1)
                    return
                logger.warning(
                    "Webhook HTTP %d from %s (attempt %d/%d)",
                    resp.status_code,
                    url,
                    attempt + 1,
                    len(RETRY_SCHEDULE_SECONDS),
                )
        except Exception as exc:
            logger.warning(
                "Webhook to %s failed (attempt %d/%d): %s",
                url,
                attempt + 1,
                len(RETRY_SCHEDULE_SECONDS),
                exc,
            )

    count = _failure_counts.get(url, 0) + 1
    _failure_counts[url] = count
    if count >= 5:
        _degraded_urls.add(url)
        logger.warning("Webhook URL %s marked degraded after %d consecutive failures", url, count)


def _build_spec_event(
    event: str,
    *,
    intent_id: str = "",
    contact_id: str = "",
    interaction: str = "",
    message_id: str = "",
) -> dict:
    """Build an RFC-0007 webhook event body (notification only, no content)."""
    return {
        "shadownet:v": "0.1",
        "event_id": str(uuid.uuid4()),
        "event": event,
        "occurredAt": int(time.time()),
        "data": {
            "intentId": intent_id,
            "contactId": contact_id,
            "interaction": interaction,
            "messageId": message_id,
        },
    }


# data_types that are purely terminal and need no notification at all.
_SILENT_DATA_TYPES = frozenset({"acknowledgment", "ack", "thank_you"})

# data_types where the agent should act autonomously (no user delivery).
_AGENT_ONLY_DATA_TYPES = frozenset(
    {
        "coordination_request",
        "meeting_proposal",
        "meeting_request",
        "meetup_request",
        "coffee_proposal",
        "schedule_request",
        "planning_request",
    }
)


async def notify_message_received(
    contact: Any, data_type: str, data: dict, interaction_id: str
) -> None:
    contact_name = contact.name if hasattr(contact, "name") else str(contact)
    contact_id = contact.id if hasattr(contact, "id") else ""

    if data_type in _SILENT_DATA_TYPES:
        logger.info("Skipping webhook for terminal data_type=%s from %s", data_type, contact_name)
        return

    if data_type in _AGENT_ONLY_DATA_TYPES:
        url = settings.notification_negotiate_url or settings.notification_webhook_url
    else:
        url = settings.notification_webhook_url

    if not url:
        logger.debug("No notification_webhook_url configured; skipping")
        return

    try:
        from app.inbox_stream import publish as publish_inbox_event

        publish_inbox_event(
            {
                "event": "message_received",
                "requires_action": data_type not in _AGENT_ONLY_DATA_TYPES,
                "contact": contact_name,
                "data_type": data_type,
                "interaction_id": interaction_id,
                "data": data,
            }
        )
    except ImportError:
        pass

    webhook_payload = {
        "shadownet:v": "0.1",
        "event": "inbox.message",
        "event_id": str(uuid.uuid4()),
        "occurredAt": int(time.time()),
        "contact": contact_name,
        "contact_id": contact_id,
        "data_type": data_type,
        "interaction_id": interaction_id,
        "data": data,
    }

    asyncio.create_task(_post_webhook_with_retry(webhook_payload, url))


async def notify_interaction_updated(contact: Any, interaction_id: str, status: str) -> None:
    url = settings.notification_webhook_url
    if not url:
        return

    contact_id = contact.id if hasattr(contact, "id") else ""
    spec_payload = _build_spec_event(
        "task.update",
        intent_id=interaction_id,
        contact_id=contact_id,
    )

    asyncio.create_task(_post_webhook_with_retry(spec_payload, url))
