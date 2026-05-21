"""MCP server exposing generic agent-to-agent communication tools.

Uses FastMCP for tool definitions and mounts into the FastAPI app
via streamable_http_app().
"""

from __future__ import annotations

import asyncio
import json
import logging

from mcp.server.fastmcp import FastMCP
from sqlmodel import Session, select

from app.database import engine
from app.models import AccessGrant, Contact, InteractionContext, _utcnow

logger = logging.getLogger(__name__)

mcp = FastMCP("shadownet", stateless_http=True)


def _get_session() -> Session:
    return Session(engine)


# ── Tools ──────────────────────────────────────────────────────────────────


@mcp.tool()
def social_contacts(query: str = "") -> str:
    """List contacts in the user's agent network.

    Returns the id, name, endpoint, and metadata for each contact.
    Use the 'id' field when calling social_send() or other tools.
    Optionally filter by name substring.
    """
    with _get_session() as session:
        contacts = session.exec(select(Contact)).all()
        results = []
        for c in contacts:
            if query and query.lower() not in c.name.lower():
                continue
            results.append(
                {
                    "id": c.id,
                    "name": c.name,
                    "agent_endpoint": c.agent_endpoint,
                    "label": c.label,
                    "metadata": json.loads(c.metadata_json),
                }
            )
        return json.dumps(results, indent=2)


@mcp.tool()
def social_contact_detail(contact_id: str) -> str:
    """Get full details on a specific contact including their access grants."""
    with _get_session() as session:
        contact = session.get(Contact, contact_id)
        if contact is None:
            return json.dumps({"error": "Contact not found"})
        grants = session.exec(select(AccessGrant).where(AccessGrant.contact_id == contact_id)).all()
        return json.dumps(
            {
                "id": contact.id,
                "name": contact.name,
                "agent_endpoint": contact.agent_endpoint,
                "label": contact.label,
                "notes": contact.notes,
                "metadata": json.loads(contact.metadata_json),
                "grants": {g.grant_type: g.allowed for g in grants},
            },
            indent=2,
        )


_COORDINATION_KEYWORDS = frozenset(
    {
        "meeting",
        "meetup",
        "meet",
        "coffee",
        "lunch",
        "dinner",
        "drinks",
        "hangout",
        "hang_out",
        "get_together",
        "catch_up",
        "brunch",
        "coordination",
        "coordinate",
        "schedule",
        "planning",
        "plan",
        "proposal",
        "invite",
        "invitation",
    }
)


def _normalize_data_type(data_type: str, content_payload: dict) -> str:
    """Auto-correct meeting-like data_types to 'coordination_request'."""
    if data_type == "coordination_request":
        return data_type
    dt_lower = data_type.lower().replace("-", "_")
    tokens = set(dt_lower.split("_"))
    if tokens & _COORDINATION_KEYWORDS:
        logger.info("Normalized data_type '%s' → 'coordination_request'", data_type)
        return "coordination_request"
    content_str = json.dumps(content_payload).lower()
    for kw in ("meeting", "coffee", "lunch", "dinner", "drinks", "brunch", "meetup"):
        action_words = (
            "propose",
            "plan",
            "schedule",
            "invite",
            "coordinate",
            "want to meet",
            "get together",
        )
        if kw in content_str and any(w in content_str for w in action_words):
            logger.info(
                "Normalized data_type '%s' → 'coordination_request' (content match)",
                data_type,
            )
            return "coordination_request"
    return data_type


def _enrich_confirmation(payload: dict, contact_id: str, session: Session) -> dict:
    """For confirmation/confirmed messages, auto-include the agreed plan."""
    if "plan" in payload:
        return payload
    recent = session.exec(
        select(InteractionContext)
        .where(InteractionContext.contact_id == contact_id)
        .where(InteractionContext.data_type.in_(["response", "coordination_request"]))
        .order_by(InteractionContext.created_at.desc())
        .limit(5)
    ).all()
    for ictx in recent:
        ctx = json.loads(ictx.context_data)
        plan = None
        if "response" in ctx and isinstance(ctx["response"], dict):
            plan = ctx["response"].get("plan")
        elif "plan" in ctx:
            plan = ctx["plan"]
        if plan:
            payload["plan"] = plan
            payload.setdefault("status", "confirmed")
            logger.info("Auto-enriched confirmation with plan from interaction %s", ictx.id)
            break
    return payload


@mcp.tool()
def social_send(contact_id: str, content: str, data_type: str = "message") -> str:
    """Send a message to another agent via the A2A protocol.

    After sending, END your turn. Do NOT call social_inbox — a webhook
    will notify you automatically when the other agent replies.

    Args:
        contact_id: The contact to send to (get from social_contacts).
        content: The message payload — a JSON string for structured data,
                 or plain text for simple messages.
        data_type: For meeting/coordination requests, use "coordination_request"
                   (triggers autonomous agent-to-agent negotiation on the remote
                   side — the other user is NOT notified until both agents agree).
                   Other types: "message", "confirmation", "confirmed".
    """
    with _get_session() as session:
        contact = session.get(Contact, contact_id)
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        from app.executor import build_a2a_message, send_a2a_message

        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            payload = {"text": content}

        data_type = _normalize_data_type(data_type, payload)

        if data_type in ("confirmation", "confirmed"):
            payload = _enrich_confirmation(payload, contact.id, session)

        body = build_a2a_message(data_type, payload)
        msg_id = body["message"]["messageId"]
        endpoint = contact.agent_endpoint

        ictx = InteractionContext(
            data_type=data_type,
            contact_id=contact.id,
            direction="outbound",
            status="sent",
            context_data=json.dumps(payload),
        )
        session.add(ictx)
        session.commit()
        session.refresh(ictx)

    async def _deliver():
        return await send_a2a_message(endpoint, body)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_deliver())
    except RuntimeError:
        pass

    return json.dumps({"sent": True, "message_id": msg_id, "interaction_id": ictx.id})


_COORDINATION_RESPONSE_TYPES = frozenset({"response", "confirmation", "confirmed"})


def _add_coordination_guidance(entry: dict, interaction: InteractionContext) -> dict:
    """Inject next-step instructions for coordination messages."""
    dt = entry["data_type"]
    cid = entry.get("contact_id", "")

    if dt == "response" and interaction.status == "received":
        entry["ACTION_REQUIRED"] = (
            f"Present this plan to your user concisely and ask: '[details]. Confirm?' "
            f"WAIT for the user to say yes/confirm. Then call: "
            f"social_confirm_plan(contact_id='{cid}'). "
            f"Do NOT say 'confirmed' yet — the other person still needs to accept."
        )
    elif dt == "confirmation" and interaction.status == "received":
        entry["ACTION_REQUIRED"] = (
            f"Present this plan to your user and ask: '[details]. Accept?' "
            f"WAIT for the user to reply. Then call: "
            f"social_accept_plan(interaction_id='{interaction.id}'). "
            f"Output: 'Confirmed! Enjoy.'"
        )
    elif dt == "confirmed":
        entry["ACTION_REQUIRED"] = (
            "Tell your user: 'All set! [plan details].' This coordination is complete."
        )

    return entry


@mcp.tool()
def social_inbox(limit: int = 20, data_type: str = "", contact_id: str = "") -> str:
    """Check for inbound messages from other agents.

    Each message has an 'id' you can use with social_respond() to reply.
    Messages with status 'received' have not been responded to yet.
    Coordination messages include an ACTION_REQUIRED field — follow it exactly.

    Args:
        limit: Max number of messages to return (default 20).
        data_type: Filter by message type (e.g. "coordination_request").
        contact_id: Filter by a specific contact.
    """
    with _get_session() as session:
        stmt = (
            select(InteractionContext)
            .where(InteractionContext.direction == "inbound")
            .order_by(InteractionContext.created_at.desc())
            .limit(limit)
        )
        if data_type:
            stmt = stmt.where(InteractionContext.data_type == data_type)
        if contact_id:
            stmt = stmt.where(InteractionContext.contact_id == contact_id)
        interactions = session.exec(stmt).all()
        results = []
        for i in interactions:
            contact = session.get(Contact, i.contact_id) if i.contact_id else None
            entry = {
                "id": i.id,
                "data_type": i.data_type,
                "contact": contact.name if contact else "Unknown",
                "contact_id": i.contact_id,
                "status": i.status,
                "data": json.loads(i.context_data),
                "created_at": i.created_at.isoformat(),
            }
            if i.data_type in _COORDINATION_RESPONSE_TYPES:
                entry = _add_coordination_guidance(entry, i)
            results.append(entry)
        return json.dumps(results, indent=2)


@mcp.tool()
def social_respond(interaction_id: str, content: str, data_type: str = "response") -> str:
    """Reply to an inbound message from another agent.

    Use the 'id' field from social_inbox() results as the interaction_id.
    The reply is sent back to the original sender via A2A.

    Args:
        interaction_id: The id of the inbound message to reply to.
        content: The response payload — a JSON string for structured data,
                 or plain text.
        data_type: A label for the response type (e.g. "response",
                   "availability_response", "confirmation").
    """
    with _get_session() as session:
        ictx = session.get(InteractionContext, interaction_id)
        if ictx is None:
            return json.dumps({"error": "Interaction not found"})

        contact = session.get(Contact, ictx.contact_id) if ictx.contact_id else None
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            payload = {"text": content}

        if data_type in ("confirmation", "confirmed"):
            payload = _enrich_confirmation(payload, ictx.contact_id, session)

        ctx_data = json.loads(ictx.context_data)
        ctx_data["response"] = payload
        ictx.context_data = json.dumps(ctx_data)
        ictx.status = "responded"
        ictx.updated_at = _utcnow()
        session.add(ictx)
        session.commit()

        from app.executor import build_a2a_message, send_a2a_message

        endpoint = contact.agent_endpoint
        task_id = ictx.a2a_task_id or None
        interaction_id = ictx.id

        body = build_a2a_message(data_type, payload, task_id=task_id)

    async def _deliver():
        return await send_a2a_message(endpoint, body)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_deliver())
    except RuntimeError:
        pass

    return json.dumps({"responded": True, "interaction_id": interaction_id})


# ── Purpose-built coordination tools ──────────────────────────────────────


def _fire_and_forget(endpoint: str, body: dict) -> None:
    """Schedule an A2A delivery on the running event loop."""
    from app.executor import send_a2a_message

    async def _deliver():
        return await send_a2a_message(endpoint, body)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_deliver())
    except RuntimeError:
        pass


@mcp.tool()
def social_coordinate(contact_id: str, activity: str, details: str = "") -> str:
    """Start coordinating a meetup (coffee, dinner, meeting, etc.) with a contact.

    Their agent will negotiate a time and place autonomously — the other
    person is NOT notified until both agents agree on a plan. You will
    receive the proposed plan via webhook; present it to your user and
    then call social_confirm_plan() if they approve.

    After calling this, END your turn. Do NOT poll with social_inbox.

    Args:
        contact_id: The contact to coordinate with (from social_contacts).
        activity: What to do — e.g. "coffee", "lunch", "dinner", "meeting".
        details: Any constraints — e.g. "Thursday morning before work",
                 "somewhere in Mitte", "casual vibe".
    """
    with _get_session() as session:
        contact = session.get(Contact, contact_id)
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        from app.executor import build_a2a_message

        payload = {
            "activity": activity,
            "details": details,
        }
        data_type = "coordination_request"

        body = build_a2a_message(data_type, payload)
        endpoint = contact.agent_endpoint

        ictx = InteractionContext(
            data_type=data_type,
            contact_id=contact.id,
            direction="outbound",
            status="sent",
            context_data=json.dumps(payload),
        )
        session.add(ictx)
        session.commit()
        session.refresh(ictx)

    _fire_and_forget(endpoint, body)

    return json.dumps(
        {
            "sent": True,
            "contact": contact.name,
            "activity": activity,
            "message": (
                f"Coordination request sent to {contact.name}. "
                f"Their agent will negotiate a plan. "
                f"You'll be notified when a plan is ready — do NOT poll."
            ),
        }
    )


@mcp.tool()
def social_confirm_plan(contact_id: str) -> str:
    """Confirm an agreed coordination plan and send it to the other person.

    Looks up the most recent agreed plan for this contact and sends a
    confirmation. The other person's agent will then ask them to accept.

    Call this ONLY after your user says "yes" / "confirm" / "ok".
    Output to your user: "Sent confirmation. I'll let you know when they accept."

    Args:
        contact_id: The contact whose plan to confirm (from social_contacts).
    """
    with _get_session() as session:
        contact = session.get(Contact, contact_id)
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        pending = session.exec(
            select(InteractionContext)
            .where(InteractionContext.contact_id == contact.id)
            .where(InteractionContext.data_type == "response")
            .where(InteractionContext.direction == "inbound")
            .order_by(InteractionContext.created_at.desc())
            .limit(1)
        ).first()

        if pending is None:
            return json.dumps({"error": "No pending plan found for this contact"})

        ctx_data = json.loads(pending.context_data)
        plan = None
        if "response" in ctx_data and isinstance(ctx_data["response"], dict):
            plan = ctx_data["response"].get("plan")
        if plan is None:
            plan = ctx_data.get("plan")
        if plan is None:
            plan = ctx_data

        payload = {"status": "confirmed", "plan": plan}

        from app.executor import build_a2a_message

        body = build_a2a_message("confirmation", payload)
        endpoint = contact.agent_endpoint

        pending.status = "responded"
        pending.updated_at = _utcnow()

        ictx = InteractionContext(
            data_type="confirmation",
            contact_id=contact.id,
            direction="outbound",
            status="sent",
            context_data=json.dumps(payload),
        )
        session.add(ictx)
        session.commit()
        session.refresh(ictx)

    _fire_and_forget(endpoint, body)

    return json.dumps(
        {
            "confirmed": True,
            "plan": plan,
            "message": (
                "Confirmation sent. The other person still needs to accept. "
                "Tell your user: 'Sent confirmation. I'll let you know when they accept.'"
            ),
        }
    )


@mcp.tool()
def social_accept_plan(interaction_id: str) -> str:
    """Accept a coordination plan that was proposed to your user.

    Call this ONLY after your user says "yes" / "accept" / "ok" in response
    to a plan proposal. Sends final confirmation back to the initiator.
    Output to your user: "Confirmed! Enjoy."

    Args:
        interaction_id: The id of the inbound confirmation message.
    """
    with _get_session() as session:
        ictx = session.get(InteractionContext, interaction_id)
        if ictx is None:
            return json.dumps({"error": "Interaction not found"})

        contact = session.get(Contact, ictx.contact_id) if ictx.contact_id else None
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        payload = {"status": "confirmed"}

        ctx_data = json.loads(ictx.context_data)
        if "plan" in ctx_data:
            payload["plan"] = ctx_data["plan"]

        ctx_data["response"] = payload
        ictx.context_data = json.dumps(ctx_data)
        ictx.status = "responded"
        ictx.updated_at = _utcnow()
        session.add(ictx)
        session.commit()

        from app.executor import build_a2a_message

        endpoint = contact.agent_endpoint
        task_id = ictx.a2a_task_id or None
        body = build_a2a_message("confirmed", payload, task_id=task_id)

    _fire_and_forget(endpoint, body)

    return json.dumps(
        {
            "accepted": True,
            "message": "Plan accepted and confirmation sent. Tell your user: 'Confirmed! Enjoy.'",
        }
    )


@mcp.tool()
def social_interactions(
    data_type: str = "", status_filter: str = "", direction: str = "", limit: int = 20
) -> str:
    """List all interactions. Optionally filter by data_type, status, or direction."""
    with _get_session() as session:
        stmt = select(InteractionContext).order_by(InteractionContext.created_at.desc())
        if data_type:
            stmt = stmt.where(InteractionContext.data_type == data_type)
        if status_filter:
            stmt = stmt.where(InteractionContext.status == status_filter)
        if direction:
            stmt = stmt.where(InteractionContext.direction == direction)
        interactions = session.exec(stmt.limit(limit)).all()
        results = []
        for i in interactions:
            contact = session.get(Contact, i.contact_id) if i.contact_id else None
            results.append(
                {
                    "id": i.id,
                    "data_type": i.data_type,
                    "contact": contact.name if contact else "Unknown",
                    "contact_id": i.contact_id,
                    "direction": i.direction,
                    "status": i.status,
                    "data": json.loads(i.context_data),
                    "created_at": i.created_at.isoformat(),
                    "updated_at": i.updated_at.isoformat(),
                }
            )
        return json.dumps(results, indent=2)
