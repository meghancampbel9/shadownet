"""MCP server exposing shadownet-local protocol tools.

Uses FastMCP for tool definitions and mounts into the FastAPI app
via streamable_http_app(). All tools follow RFC-0007 naming and schemas.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from sqlmodel import Session, select

from app.config import settings
from app.database import engine
from app.models import AccessGrant, Contact, InteractionContext, _utcnow

logger = logging.getLogger(__name__)

mcp = FastMCP("shadownet", stateless_http=True)

_inbox_event: asyncio.Event = asyncio.Event()

_WEBHOOK_PERSIST_PATH = Path(settings.data_dir) / "webhook.json"


def notify_inbox() -> None:
    """Signal that a new inbox message has arrived (unblocks social_inbox_wait)."""
    _inbox_event.set()


def _get_session() -> Session:
    return Session(engine)


def _validate_webhook_url(url: str) -> str | None:
    """Return error string if URL violates RFC-0007 constraints, else None."""
    if not url:
        return None
    if url.startswith("https://"):
        return None
    if url.startswith("http://localhost") or url.startswith("http://127.0.0.1") or url.startswith("http://[::1]"):
        return None
    return "invalid_webhook_url: must be https:// or http://localhost/127.0.0.1/[::1]"


def _persist_webhook(url: str, secret: str, events: list[str] | None) -> None:
    """Persist webhook config to disk for replay after restart."""
    _WEBHOOK_PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _WEBHOOK_PERSIST_PATH.write_text(
        json.dumps({"url": url, "secret": secret, "events": events})
    )


def load_persisted_webhook() -> None:
    """Restore webhook registration from disk at startup."""
    if _WEBHOOK_PERSIST_PATH.exists():
        try:
            data = json.loads(_WEBHOOK_PERSIST_PATH.read_text())
            settings.notification_webhook_url = data.get("url", "")
            settings.notification_webhook_secret = data.get("secret", "")
        except (json.JSONDecodeError, OSError):
            pass


# ── RFC-0007 Required Tools ────────────────────────────────────────────────


@mcp.tool()
def social_contacts(query: str = "") -> str:
    """List contacts in the user's agent network.

    Returns contacts with id, shadowname, did, displayName, level, and lastSeen.
    Optionally filter by name/shadowname substring.
    """
    with _get_session() as session:
        contacts = session.exec(select(Contact)).all()
        results = []
        for c in contacts:
            if query:
                q = query.lower()
                if q not in c.name.lower() and q not in c.shadowname.lower():
                    continue
            results.append(
                {
                    "id": c.id,
                    "shadowname": c.shadowname,
                    "did": c.did,
                    "displayName": c.name,
                    "level": None,
                    "lastSeen": None,
                }
            )
        return json.dumps({"contacts": results}, indent=2)


@mcp.tool()
def social_contact_detail(id: str) -> str:
    """Get full details on a specific contact including grants and credentials."""
    with _get_session() as session:
        contact = session.get(Contact, id)
        if contact is None:
            return json.dumps({"error": "Contact not found"})
        grants = session.exec(
            select(AccessGrant).where(AccessGrant.contact_id == id)
        ).all()
        grant_list = [g.grant_type for g in grants if g.allowed]
        return json.dumps(
            {
                "id": contact.id,
                "shadowname": contact.shadowname,
                "did": contact.did,
                "endpoint": contact.agent_endpoint,
                "publicKey": json.loads(contact.public_key_jwk),
                "credentials": [],
                "grants": grant_list,
                "notes": contact.notes or None,
            },
            indent=2,
        )


@mcp.tool()
def social_identity() -> str:
    """Return this sidecar's identity (DID, shadowname, public key, credentials)."""
    from app.identity import get_did, get_keypair

    return json.dumps(
        {
            "did": get_did(),
            "shadowname": settings.shadowname or None,
            "publicKey": get_keypair().public_jwk(),
            "credentials": [],
        },
        indent=2,
    )


@mcp.tool()
async def social_resolve(shadowname: str) -> str:
    """Resolve a shadowname to a DID and agent endpoint via SNS.

    Does NOT add to the contact graph. Use social_add_contact to persist.

    Args:
        shadowname: The shadowname to resolve (e.g. "alice@provider.example").
    """
    from app.signing import get_sns_client

    client = get_sns_client()
    if client is None:
        return json.dumps({"error": "SNS not configured", "shadowname": shadowname})

    try:
        record = await client.resolve(shadowname)
        return json.dumps(
            {
                "did": record.did,
                "endpoint": record.endpoint,
                "publicKey": record.public_key.model_dump(),
                "subjectType": record.subject_type,
                "ttl": record.ttl,
            },
            indent=2,
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "shadowname": shadowname})


@mcp.tool()
async def social_add_contact(
    shadowname: str,
    displayName: str = "",
    grants: str = "[]",
) -> str:
    """Add a resolved entity to the contact graph.

    Resolves the shadowname via SNS to get DID + endpoint, then creates
    the contact. Pass grants as a JSON array of grant strings.

    Args:
        shadowname: The shadowname to add (e.g. "alice@provider.example").
        displayName: Human-readable name (defaults to the shadowname's local part).
        grants: JSON array of grant strings to auto-allow (default: ["messaging"]).
    """
    from app.signing import get_sns_client

    try:
        grant_list = json.loads(grants)
    except (json.JSONDecodeError, TypeError):
        grant_list = ["messaging"]

    if not grant_list:
        grant_list = ["messaging"]

    did = ""
    endpoint = ""
    public_key_jwk = "{}"

    client = get_sns_client()
    if client is not None:
        try:
            record = await client.resolve(shadowname)
            did = record.did
            endpoint = record.endpoint
            public_key_jwk = json.dumps(record.public_key.model_dump())
        except Exception as exc:
            return json.dumps({"error": f"SNS resolution failed: {exc}", "shadowname": shadowname})
    else:
        return json.dumps({
            "error": "SNS not configured — cannot resolve shadowname",
            "shadowname": shadowname,
        })

    local_part = shadowname.split("@")[0] if "@" in shadowname else shadowname
    name = displayName or local_part

    with _get_session() as session:
        contact = Contact(
            name=name,
            agent_endpoint=endpoint,
            did=did,
            shadowname=shadowname,
            public_key_jwk=public_key_jwk,
        )
        session.add(contact)

        for g in grant_list:
            grant = AccessGrant(
                contact_id=contact.id,
                grant_type=g,
                allowed=True,
            )
            session.add(grant)

        session.commit()
        session.refresh(contact)

        return json.dumps(
            {
                "id": contact.id,
                "shadowname": contact.shadowname,
                "did": contact.did,
            },
            indent=2,
        )


@mcp.tool()
def social_grant(contactId: str, grant: str = "messaging", allowed: bool = True) -> str:
    """Grant or revoke a per-contact permission.

    Args:
        contactId: The contact to update grants for.
        grant: The grant type string (v0.1: "messaging").
        allowed: Whether to allow (True) or revoke (False).
    """
    with _get_session() as session:
        contact = session.get(Contact, contactId)
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        existing = session.exec(
            select(AccessGrant)
            .where(AccessGrant.contact_id == contactId)
            .where(AccessGrant.grant_type == grant)
        ).first()

        if existing:
            existing.allowed = allowed
            existing.updated_at = _utcnow()
            session.add(existing)
        else:
            new_grant = AccessGrant(
                contact_id=contactId,
                grant_type=grant,
                allowed=allowed,
            )
            session.add(new_grant)

        session.commit()
        return json.dumps({"ok": True})


@mcp.tool()
def social_set_webhook(url: str, secret: str, events: str = "[]") -> str:
    """Register or update the webhook for inbox notifications.

    To unregister, call with url="".
    Secret must be at least 32 characters.

    Args:
        url: The webhook URL (https:// or http://localhost only). Empty to unregister.
        secret: HMAC secret for signature verification (>=32 bytes).
        events: JSON array of event types to subscribe to (default: all events).
    """
    if url == "":
        settings.notification_webhook_url = ""
        settings.notification_webhook_secret = ""
        _persist_webhook("", "", None)
        return json.dumps({"ok": True})

    url_err = _validate_webhook_url(url)
    if url_err:
        return json.dumps({"error": url_err})

    if len(secret) < 32:
        return json.dumps({"error": "secret must be at least 32 bytes"})

    try:
        event_list = json.loads(events) if events else None
    except (json.JSONDecodeError, TypeError):
        event_list = None

    settings.notification_webhook_url = url
    settings.notification_webhook_secret = secret
    _persist_webhook(url, secret, event_list)

    return json.dumps({"ok": True})


# ── Messaging Tools ────────────────────────────────────────────────────────

_COORDINATION_KEYWORDS = frozenset(
    {
        "meeting", "meetup", "meet", "coffee", "lunch", "dinner", "drinks",
        "hangout", "hang_out", "get_together", "catch_up", "brunch",
        "coordination", "coordinate", "schedule", "planning", "plan",
        "proposal", "invite", "invitation",
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
            "propose", "plan", "schedule", "invite", "coordinate",
            "want to meet", "get together",
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
def social_send(
    contactId: str,
    payload: str,
    interaction: str = "",
    intentId: str = "",
) -> str:
    """Send a Shadownet-enveloped message over A2A.

    After sending, END your turn. A webhook or inbox_wait will notify you
    when the other agent replies.

    Args:
        contactId: The contact to send to (from social_contacts).
        payload: The message payload as a JSON object string.
        interaction: Optional interaction URI (must start with urn:). Omit for free-form.
        intentId: Optional existing intent ID. New intent created if absent.
    """
    with _get_session() as session:
        contact = session.get(Contact, contactId)
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        from app.executor import build_envelope, send_a2a_message

        try:
            payload_obj = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            payload_obj = {"text": payload}

        data_type = payload_obj.get("type", "message")
        data_type = _normalize_data_type(data_type, payload_obj)

        if data_type in ("confirmation", "confirmed"):
            payload_obj = _enrich_confirmation(payload_obj, contact.id, session)

        body = build_envelope(
            payload_obj,
            intent_id=intentId or None,
            interaction=interaction,
        )
        envelope_data = body["message"]["parts"][0]["data"]
        intent_id_out = envelope_data["intentId"]

        endpoint = contact.agent_endpoint
        peer_did = contact.did

        ictx = InteractionContext(
            data_type=data_type,
            contact_id=contact.id,
            direction="outbound",
            status="sent",
            intent_id=intent_id_out,
            context_data=json.dumps(payload_obj),
        )
        session.add(ictx)
        session.commit()
        session.refresh(ictx)
        task_id = ictx.id

    async def _deliver():
        return await send_a2a_message(endpoint, body, peer_did=peer_did)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_deliver())
    except RuntimeError:
        pass

    return json.dumps({"intentId": intent_id_out, "taskId": task_id})


@mcp.tool()
def social_inbox(
    since: int = 0,
    interaction: str = "",
    contactId: str = "",
    limit: int = 20,
) -> str:
    """List pending inbound messages or task updates.

    Args:
        since: Unix timestamp — only return items received after this time.
        interaction: Filter by interaction URI.
        contactId: Filter by contact ID.
        limit: Max items to return (default 20).
    """
    from datetime import datetime, timezone

    with _get_session() as session:
        stmt = (
            select(InteractionContext)
            .where(InteractionContext.direction == "inbound")
            .order_by(InteractionContext.created_at.desc())
            .limit(limit)
        )
        if since:
            cutoff = datetime.fromtimestamp(since, tz=timezone.utc)
            stmt = stmt.where(InteractionContext.created_at > cutoff)
        if contactId:
            stmt = stmt.where(InteractionContext.contact_id == contactId)

        interactions = session.exec(stmt).all()
        items = []
        for i in interactions:
            items.append(
                {
                    "id": i.id,
                    "contactId": i.contact_id,
                    "intentId": i.intent_id or f"urn:uuid:{i.id}",
                    "interaction": "",
                    "payload": json.loads(i.context_data),
                    "receivedAt": int(i.created_at.timestamp()),
                }
            )
        return json.dumps({"items": items}, indent=2)


@mcp.tool()
async def social_inbox_wait(timeout_seconds: int = 30, last_event_id: str = "") -> str:
    """Long-poll for inbox events. Blocks until events arrive or timeout.

    Args:
        timeout_seconds: Max seconds to wait (default 30, capped at 90).
        last_event_id: Opaque cursor from previous call. Empty = deliver from now.
    """
    from datetime import datetime, timezone

    timeout = min(timeout_seconds, 90)
    deadline = time.time() + timeout

    cutoff_ts: float | None = None
    if last_event_id:
        try:
            cutoff_ts = float(last_event_id)
        except ValueError:
            try:
                cutoff_ts = datetime.fromisoformat(last_event_id).timestamp()
            except ValueError:
                pass

    while time.time() < deadline:
        with _get_session() as session:
            stmt = (
                select(InteractionContext)
                .where(InteractionContext.direction == "inbound")
                .order_by(InteractionContext.created_at.desc())
                .limit(50)
            )
            if cutoff_ts:
                cutoff_dt = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc)
                stmt = stmt.where(InteractionContext.created_at > cutoff_dt)

            interactions = session.exec(stmt).all()
            if interactions:
                events = []
                high_water: float = 0
                for i in interactions:
                    ts = i.created_at.timestamp()
                    events.append(
                        {
                            "event_id": str(ts),
                            "event": "inbox.message",
                            "occurredAt": int(ts),
                            "data": {
                                "intentId": i.intent_id or f"urn:uuid:{i.id}",
                                "contactId": i.contact_id,
                                "interaction": "",
                                "messageId": i.id,
                            },
                        }
                    )
                    if ts > high_water:
                        high_water = ts
                return json.dumps(
                    {"events": events, "next_event_id": str(high_water)},
                    indent=2,
                )

        _inbox_event.clear()
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait_for(_inbox_event.wait(), timeout=min(remaining, 2.0))
        except asyncio.TimeoutError:
            pass

    high_water_mark = str(time.time())
    return json.dumps({"events": [], "next_event_id": last_event_id or high_water_mark}, indent=2)


@mcp.tool()
def social_respond(intentId: str, payload: str) -> str:
    """Respond within an existing intent.

    Args:
        intentId: The intent ID to respond to (from social_inbox items).
        payload: The response payload as a JSON object string.
    """
    with _get_session() as session:
        ictx = session.exec(
            select(InteractionContext)
            .where(InteractionContext.intent_id == intentId)
            .where(InteractionContext.direction == "inbound")
            .order_by(InteractionContext.created_at.desc())
            .limit(1)
        ).first()

        if ictx is None:
            ictx = session.get(InteractionContext, intentId)

        if ictx is None:
            return json.dumps({"error": "Intent not found"})

        contact = session.get(Contact, ictx.contact_id) if ictx.contact_id else None
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        try:
            payload_obj = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            payload_obj = {"text": payload}

        data_type = payload_obj.get("type", "response")
        payload_obj["type"] = data_type
        if data_type in ("confirmation", "confirmed"):
            payload_obj = _enrich_confirmation(payload_obj, ictx.contact_id, session)

        ctx_data = json.loads(ictx.context_data)
        ctx_data["response"] = payload_obj
        ictx.context_data = json.dumps(ctx_data)
        ictx.status = "responded"
        ictx.updated_at = _utcnow()
        session.add(ictx)
        session.commit()

        from app.executor import build_envelope, send_a2a_message

        endpoint = contact.agent_endpoint
        peer_did = contact.did

        body = build_envelope(payload_obj, intent_id=ictx.intent_id or None)

        response_ictx = InteractionContext(
            data_type=data_type,
            contact_id=contact.id,
            direction="outbound",
            status="sent",
            intent_id=ictx.intent_id,
            context_data=json.dumps(payload_obj),
        )
        session.add(response_ictx)
        session.commit()
        session.refresh(response_ictx)
        task_id = response_ictx.id

    async def _deliver():
        return await send_a2a_message(endpoint, body, peer_did=peer_did)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_deliver())
    except RuntimeError:
        pass

    return json.dumps({"taskId": task_id})


# ── Coordination Tools (bonus, not spec-required) ─────────────────────────


def _fire_and_forget(endpoint: str, body: dict, peer_did: str = "") -> None:
    """Schedule an A2A delivery on the running event loop."""
    from app.executor import send_a2a_message

    async def _deliver():
        return await send_a2a_message(endpoint, body, peer_did=peer_did)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_deliver())
    except RuntimeError:
        pass


@mcp.tool()
def social_coordinate(contactId: str, activity: str, details: str = "") -> str:
    """Start coordinating a meetup (coffee, dinner, meeting, etc.) with a contact.

    Their agent will negotiate a time and place autonomously — the other
    person is NOT notified until both agents agree on a plan.

    After calling this, END your turn. Do NOT poll with social_inbox.

    Args:
        contactId: The contact to coordinate with (from social_contacts).
        activity: What to do — e.g. "coffee", "lunch", "dinner", "meeting".
        details: Any constraints — e.g. "Thursday morning", "downtown".
    """
    with _get_session() as session:
        contact = session.get(Contact, contactId)
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        from app.executor import build_envelope

        payload_obj = {
            "type": "coordination_request",
            "activity": activity,
            "details": details,
        }

        body = build_envelope(payload_obj)
        envelope_data = body["message"]["parts"][0]["data"]
        intent_id = envelope_data["intentId"]
        endpoint = contact.agent_endpoint
        peer_did = contact.did
        contact_name = contact.name

        ictx = InteractionContext(
            data_type="coordination_request",
            contact_id=contact.id,
            direction="outbound",
            status="sent",
            intent_id=intent_id,
            context_data=json.dumps(payload_obj),
        )
        session.add(ictx)
        session.commit()
        session.refresh(ictx)
        task_id = ictx.id

    _fire_and_forget(endpoint, body, peer_did=peer_did)

    return json.dumps(
        {
            "intentId": intent_id,
            "taskId": task_id,
            "message": (
                f"Coordination request sent to {contact_name}. "
                f"Their agent will negotiate a plan. "
                f"You'll be notified when a plan is ready — do NOT poll."
            ),
        }
    )


@mcp.tool()
def social_confirm_plan(contactId: str = "") -> str:
    """Confirm an agreed coordination plan and send it to the other person.

    Call this after your user says "yes" / "confirm" / "ok" to a proposed plan.
    If contactId is omitted, confirms the most recent pending plan.

    Args:
        contactId: Optional. The contact whose plan to confirm.
    """
    with _get_session() as session:
        pending = None
        contact = None

        if contactId:
            contact = session.get(Contact, contactId)
            if contact is None:
                return json.dumps({"error": "Contact not found"})
            pending = session.exec(
                select(InteractionContext)
                .where(InteractionContext.contact_id == contact.id)
                .where(InteractionContext.data_type == "response")
                .where(InteractionContext.direction == "inbound")
                .where(InteractionContext.status == "received")
                .order_by(InteractionContext.created_at.desc())
                .limit(1)
            ).first()

        if pending is None:
            pending = session.exec(
                select(InteractionContext)
                .where(InteractionContext.data_type == "response")
                .where(InteractionContext.direction == "inbound")
                .where(InteractionContext.status == "received")
                .order_by(InteractionContext.created_at.desc())
                .limit(1)
            ).first()
            if pending is not None and contact is None:
                contact = session.get(Contact, pending.contact_id) if pending.contact_id else None

        if pending is None:
            return json.dumps({"error": "No pending plan found"})
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        ctx_data = json.loads(pending.context_data)
        plan = None
        if "response" in ctx_data and isinstance(ctx_data["response"], dict):
            plan = ctx_data["response"].get("plan")
        if plan is None:
            plan = ctx_data.get("plan")
        if plan is None:
            plan = ctx_data

        payload_obj = {"type": "confirmation", "status": "confirmed", "plan": plan}

        from app.executor import build_envelope

        body = build_envelope(payload_obj)
        endpoint = contact.agent_endpoint
        peer_did = contact.did

        pending.status = "responded"
        pending.updated_at = _utcnow()

        ictx = InteractionContext(
            data_type="confirmation",
            contact_id=contact.id,
            direction="outbound",
            status="sent",
            context_data=json.dumps(payload_obj),
        )
        session.add(ictx)
        session.commit()
        session.refresh(ictx)

    _fire_and_forget(endpoint, body, peer_did=peer_did)

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
def social_accept_plan(intentId: str = "") -> str:
    """Accept a coordination plan that was proposed to your user.

    Call this after your user says "yes" / "accept" / "ok" to a plan.
    If intentId is omitted, accepts the most recent pending confirmation.

    Args:
        intentId: Optional. The intent ID of the inbound confirmation message.
    """
    with _get_session() as session:
        ictx = None
        if intentId:
            ictx = session.exec(
                select(InteractionContext)
                .where(InteractionContext.intent_id == intentId)
                .where(InteractionContext.direction == "inbound")
                .order_by(InteractionContext.created_at.desc())
                .limit(1)
            ).first()
            if ictx is None:
                ictx = session.get(InteractionContext, intentId)

        if ictx is None:
            ictx = session.exec(
                select(InteractionContext)
                .where(InteractionContext.data_type == "confirmation")
                .where(InteractionContext.direction == "inbound")
                .where(InteractionContext.status == "received")
                .order_by(InteractionContext.created_at.desc())
                .limit(1)
            ).first()

        if ictx is None:
            return json.dumps({"error": "No pending plan to accept"})

        contact = session.get(Contact, ictx.contact_id) if ictx.contact_id else None
        if contact is None:
            return json.dumps({"error": "Contact not found"})

        payload_obj = {"type": "confirmed", "status": "confirmed"}

        ctx_data = json.loads(ictx.context_data)
        if "plan" in ctx_data:
            payload_obj["plan"] = ctx_data["plan"]

        ctx_data["response"] = payload_obj
        ictx.context_data = json.dumps(ctx_data)
        ictx.status = "responded"
        ictx.updated_at = _utcnow()
        session.add(ictx)
        session.commit()

        from app.executor import build_envelope

        endpoint = contact.agent_endpoint
        peer_did = contact.did
        body = build_envelope(payload_obj, intent_id=ictx.intent_id or None)

    _fire_and_forget(endpoint, body, peer_did=peer_did)

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
                    "contactId": i.contact_id,
                    "intentId": i.intent_id or "",
                    "contact": contact.name if contact else "Unknown",
                    "direction": i.direction,
                    "status": i.status,
                    "payload": json.loads(i.context_data),
                    "receivedAt": int(i.created_at.timestamp()),
                }
            )
        return json.dumps({"items": results}, indent=2)
