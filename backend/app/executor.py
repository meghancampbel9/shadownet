"""A2A protocol helpers and inbound message handler.

Provides shadownet-local envelope builders, an HTTP client for outbound
calls with DID-bound handshake headers, and the generic handle_inbound
function that stores every inbound message and signals the inbox event.
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

logger = logging.getLogger(__name__)

ENVELOPE_PART_TYPE = "shadownet/v1+envelope"


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


# ── shadownet-local envelope builders ──────────────────────────────────────


def build_envelope(
    payload: dict,
    *,
    intent_id: str | None = None,
    interaction: str = "",
) -> dict:
    """Build a shadownet-local wire envelope (RFC-0006).

    The outer wrapper is an A2A message with a single part of type
    shadownet/v1+envelope. Sender identity is conveyed via the session
    token (Authorization header), not in the envelope body.
    """
    envelope_data: dict[str, Any] = {
        "shadownet:v": "0.1",
        "intentId": intent_id
        if intent_id and intent_id.startswith("urn:uuid:")
        else f"urn:uuid:{intent_id or uuid.uuid4()}",
        "payload": payload,
    }
    if interaction:
        envelope_data["interaction"] = interaction

    return {
        "message": {
            "role": "ROLE_AGENT",
            "parts": [
                {
                    "type": ENVELOPE_PART_TYPE,
                    "mediaType": "application/json",
                    "data": envelope_data,
                }
            ],
        }
    }


def build_a2a_message(data_type: str, data: dict, task_id: str | None = None) -> dict:
    """Build envelope wrapping a typed payload for backward compat with MCP tools."""
    payload = {**data, "type": data_type}
    return build_envelope(payload, intent_id=None, interaction="")


# ── Outbound transport ─────────────────────────────────────────────────────


def _get_outbound_headers(peer_did: str) -> dict[str, str]:
    """Build A2A handshake headers for outbound. Uses SDK session token + VP."""
    from app.signing import build_outbound_headers

    return build_outbound_headers(audience_did=peer_did)


async def send_a2a_message(endpoint: str, body: dict, peer_did: str = "") -> dict | None:
    """Send an A2A envelope to a peer endpoint with handshake auth.

    The endpoint is the agent's A2A URL (from their agent card). We POST
    directly to it per the A2A spec.
    """
    url = endpoint.rstrip("/")

    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "A2A-Version": "1.0",
    }

    if peer_did:
        handshake_headers = _get_outbound_headers(peer_did)
        headers.update(handshake_headers)

    delay = settings.agent_retry_base_delay

    for attempt in range(settings.agent_retry_attempts):
        try:
            async with httpx.AsyncClient(timeout=settings.agent_request_timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except (httpx.HTTPError,) as exc:
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


def extract_data_part(body: dict) -> tuple[str, dict, str]:
    """Extract payload from a shadownet-local envelope or legacy A2A message.

    Returns (data_type, payload_dict, intent_id).

    Handles multiple formats:
    1. Top-level `parts` with shadownet envelope (legacy/alternative)
    2. `message.parts` with shadownet envelope (A2A standard wrapper)
    3. `message.parts` with typed data (pre-spec format)
    4. `message.parts` with text (plain text fallback)
    """
    # Check top-level parts (some peers may send without message wrapper)
    parts = body.get("parts", [])
    for part in parts:
        if part.get("type") == ENVELOPE_PART_TYPE:
            envelope_data = part.get("data", {})
            payload = envelope_data.get("payload", {})
            data_type = payload.get("type", "message")
            intent_id = envelope_data.get("intentId", "")
            return data_type, payload, intent_id

    message = body.get("message", {})
    parts = message.get("parts", [])

    # Check message.parts for shadownet envelope
    for part in parts:
        if part.get("type") == ENVELOPE_PART_TYPE:
            envelope_data = part.get("data", {})
            payload = envelope_data.get("payload", {})
            data_type = payload.get("type", "message")
            intent_id = envelope_data.get("intentId", "")
            return data_type, payload, intent_id

    # Fallback: pre-spec typed data parts
    for part in parts:
        if "data" in part:
            data = part["data"]
            if isinstance(data, dict):
                return data.get("type", "unknown"), data, ""

    # Fallback: plain text
    for part in parts:
        if "text" in part:
            return "message", {"text": part["text"]}, ""

    return "unknown", {}, ""


# ── Inbound handler ────────────────────────────────────────────────────────


async def handle_inbound(
    data_type: str,
    data: dict,
    contact: Any,
    task_id: str | None,
    session: Any,
    intent_id: str = "",
) -> dict:
    """Store the inbound message and return an ack. Domain-agnostic."""
    from app.models import InteractionContext

    ictx = InteractionContext(
        a2a_task_id=task_id or "",
        data_type=data_type,
        contact_id=contact.id,
        direction="inbound",
        status="received",
        intent_id=intent_id,
        context_data=json.dumps(data),
    )
    session.add(ictx)
    session.commit()
    session.refresh(ictx)

    logger.info("Stored inbound %s from %s (interaction=%s)", data_type, contact.name, ictx.id)

    from app.mcp_server import notify_inbox

    notify_inbox()

    try:
        from app.inbox_stream import publish as publish_inbox_event

        publish_inbox_event(
            {
                "event": "message_received",
                "contact": contact.name if hasattr(contact, "name") else str(contact),
                "data_type": data_type,
                "interaction_id": ictx.id,
                "data": data,
            }
        )
    except ImportError:
        pass

    received_at = int(datetime.now(timezone.utc).timestamp())
    return {"taskId": ictx.id, "acceptedAt": received_at}
