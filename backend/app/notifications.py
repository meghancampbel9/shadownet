"""Notification helpers (webhook, push notifications).

All user-facing notifications are dispatched as structured JSON to a
configurable webhook URL.  The host agent decides how to deliver them.
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import logging
import uuid
from typing import Any

from httpx import AsyncClient

from app.config import settings

logger = logging.getLogger(__name__)


# ── Push Notification Storage ──────────────────────────────────────────────

_push_configs: dict[str, list[dict]] = {}


def register_push_config(task_id: str, config: dict) -> dict:
    entry = {
        "id": str(uuid.uuid4()),
        "taskId": task_id,
        "url": config.get("url", ""),
        "authentication": config.get("authentication"),
        **{k: v for k, v in config.items() if k not in ("url", "authentication")},
    }
    if task_id not in _push_configs:
        _push_configs[task_id] = []
    _push_configs[task_id].append(entry)
    logger.info("Push config registered for task %s -> %s", task_id, entry["url"])
    return entry


async def fire_push_notifications(task_id: str, status_state: str) -> None:
    configs = _push_configs.get(task_id, [])
    if not configs:
        return

    payload: dict[str, Any] = {
        "statusUpdate": {
            "taskId": task_id,
            "status": {"state": status_state, "timestamp": ""},
            "metadata": {},
        }
    }

    async with AsyncClient(timeout=15) as client:
        for config in configs:
            url = config.get("url", "")
            if not url:
                continue
            try:
                headers = {"Content-Type": "application/json"}
                auth = config.get("authentication")
                if auth:
                    scheme = auth.get("scheme", "Bearer")
                    creds = auth.get("credentials", "")
                    if creds:
                        headers["Authorization"] = f"{scheme} {creds}"
                await client.post(url, json=payload, headers=headers)
                logger.info("Push notification sent to %s for task %s", url, task_id)
            except Exception as exc:
                logger.warning("Push notification to %s failed: %s", url, exc)


# ── Webhook Notifications ──────────────────────────────────────────────────


async def _post_webhook(payload: dict, url_override: str = "") -> None:
    url = url_override or settings.notification_webhook_url
    if not url:
        logger.debug("No notification_webhook_url configured; skipping")
        return
    try:
        body = json.dumps(payload).encode()
        headers: dict[str, str] = {"Content-Type": "application/json"}
        secret = settings.notification_webhook_secret
        if secret:
            sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = sig
        async with AsyncClient(timeout=10) as client:
            await client.post(url, content=body, headers=headers)
        logger.info("Webhook notification sent: %s", payload.get("event"))
    except Exception as exc:
        logger.warning("Webhook notification to %s failed: %s", url, exc)


# data_types that are purely terminal and need no notification at all.
_SILENT_DATA_TYPES = frozenset({"acknowledgment", "ack", "thank_you"})

# data_types where the agent should act autonomously (no user delivery).
# These fire to a separate webhook route so the agent can negotiate
# silently without the user seeing intermediate messages.
# Includes common LLM-invented variants that social_send normalization
# should already catch, but we double-check here as a safety net.
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
    if data_type in _SILENT_DATA_TYPES:
        logger.info("Skipping webhook for terminal data_type=%s from %s", data_type, contact_name)
        return

    url = settings.notification_webhook_url
    if not url:
        logger.debug("No notification_webhook_url configured; skipping")
        return

    if data_type in _AGENT_ONLY_DATA_TYPES:
        url = url.replace("/a2a-inbox", "/a2a-negotiate")

    payload = {
        "event": "message_received",
        "requires_action": data_type not in _AGENT_ONLY_DATA_TYPES,
        "contact": contact_name,
        "data_type": data_type,
        "interaction_id": interaction_id,
        "data": data,
    }
    from app.inbox_stream import publish as publish_inbox_event

    publish_inbox_event(payload)
    await _post_webhook(payload, url_override=url)


async def notify_interaction_updated(
    contact: Any, interaction_id: str, status: str, data: dict | None = None
) -> None:
    contact_name = contact.name if hasattr(contact, "name") else str(contact)
    await _post_webhook(
        {
            "event": "interaction_updated",
            "requires_action": False,
            "contact": contact_name,
            "interaction_id": interaction_id,
            "status": status,
            "data": data or {},
        }
    )
