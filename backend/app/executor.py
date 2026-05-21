"""A2A protocol helpers and inbound message handler.

Provides message builders for the A2A wire format, an HTTP client for
outbound calls, and the generic handle_inbound function that stores every
inbound message and fires a webhook notification.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.signing import build_a2a_jwt

logger = logging.getLogger(__name__)


# ── A2A response builders ──────────────────────────────────────────────────


def message_response(*parts: dict) -> dict:
    return {
        "message": {
            "messageId": str(uuid.uuid4()),
            "role": "ROLE_AGENT",
            "parts": list(parts),
        }
    }


def data_part(data_type: str, data: dict, media_type: str = "application/json") -> dict:
    return {"data": {**data, "type": data_type}, "mediaType": media_type}


def error_response(error_code: str, **extra: Any) -> dict:
    return message_response(data_part("error", {"error": error_code, **extra}))


def task_response(
    task_id: str,
    state: str,
    artifacts: list[dict] | None = None,
) -> dict:
    result: dict[str, Any] = {
        "task": {
            "id": task_id,
            "status": {
                "state": state,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            },
        }
    }
    if artifacts:
        result["task"]["artifacts"] = artifacts
    return result


# ── A2A protocol helpers ───────────────────────────────────────────────────


def build_a2a_message(data_type: str, data: dict, task_id: str | None = None) -> dict:
    msg: dict = {
        "message": {
            "messageId": str(uuid.uuid4()),
            "role": "ROLE_USER",
            "parts": [{"data": {**data, "type": data_type}, "mediaType": "application/json"}],
        }
    }
    if task_id:
        msg["message"]["taskId"] = task_id
    return msg


def _a2a_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {build_a2a_jwt()}",
        "Content-Type": "application/json",
        "A2A-Version": "1.0",
    }


async def send_a2a_message(endpoint: str, body: dict) -> dict | None:
    url = endpoint.rstrip("/") + "/a2a/message:send"
    headers = _a2a_headers()
    delay = settings.agent_retry_base_delay

    for attempt in range(settings.agent_retry_attempts):
        try:
            async with httpx.AsyncClient(timeout=settings.agent_request_timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning(
                "A2A attempt %d/%d to %s failed: %s",
                attempt + 1,
                settings.agent_retry_attempts,
                url,
                exc,
            )
            if attempt < settings.agent_retry_attempts - 1:
                await asyncio.sleep(delay)
                delay *= 4
    return None


# ── Data extraction ────────────────────────────────────────────────────────


def extract_data_part(body: dict) -> tuple[str, dict]:
    message = body.get("message", {})
    parts = message.get("parts", [])

    for part in parts:
        if "data" in part:
            data = part["data"]
            if isinstance(data, dict):
                return data.get("type", "unknown"), data

    for part in parts:
        if "text" in part:
            return "message", {"text": part["text"]}

    return "unknown", {}


# ── Inbound handler ────────────────────────────────────────────────────────


async def handle_inbound(
    data_type: str,
    data: dict,
    contact: Any,
    task_id: str | None,
    session: Any,
) -> dict:
    """Store the inbound message and return an ack. Domain-agnostic."""
    from app.models import InteractionContext

    ictx = InteractionContext(
        a2a_task_id=task_id or "",
        data_type=data_type,
        contact_id=contact.id,
        direction="inbound",
        status="received",
        context_data=json.dumps(data),
    )
    session.add(ictx)
    session.commit()
    session.refresh(ictx)

    logger.info("Stored inbound %s from %s (interaction=%s)", data_type, contact.name, ictx.id)

    from app.notifications import notify_message_received

    # TODO: migrate to a proper task manager so notifications are truly fire-and-forget
    # without blocking the ack response to the sender.
    await notify_message_received(contact, data_type, data, ictx.id)

    return message_response(
        data_part(
            "ack",
            {
                "received": True,
                "interaction_id": ictx.id,
            },
        )
    )
